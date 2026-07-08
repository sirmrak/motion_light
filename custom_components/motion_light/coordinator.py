"""Coordinator for Motion Light."""
import logging
from homeassistant.core import HomeAssistant, callback, Context
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.helpers.event import async_track_state_change_event, async_call_later
from homeassistant.util import dt as dt_util
from .const import (
    DOMAIN,
    CONF_SWITCH_ENTITIES,
    CONF_MAIN_SENSORS,
    CONF_EXTEND_SENSORS,
    CONF_LUX_SENSOR,
    CONF_FORCE_STOP_SENSOR,
    CONF_FORCE_STOP_STATE,
    DEFAULT_MOTION_FILTER,
    DEFAULT_OFF_DELAY,
    DEFAULT_LUX_THRESHOLD,
    DEFAULT_LUX_COOLDOWN,
    DEFAULT_MANUAL_IDLE_TIMEOUT,
    DEFAULT_MANUAL_OFF_COOLDOWN,
    DEFAULT_RESPECT_MANUAL,
    LUX_CHECK_INTERVAL,
    STATE_IDLE,
    STATE_DETECTING,
    STATE_ON,
    STATE_DELAYING,
    STATE_ACTIVE,
    STATE_OFF,
    STATE_MANUAL_ON,
    STATE_MANUAL_OFF_COOLDOWN,
    STATE_FORCE_STOPPED,
    STATE_ERROR,
    STATE_DISABLED,
)

_LOGGER = logging.getLogger(__name__)

class PrefixLoggerAdapter(logging.LoggerAdapter):
    """Logger adapter that adds a prefix to log messages."""
    def process(self, msg, kwargs):
        return f"[{self.extra.get('name', 'Unknown')}] {msg}", kwargs

def _get_config_value(entry, key, default=None):
    """Get config value from options first, then from data, then default."""
    return entry.options.get(key, entry.data.get(key, default))

class MotionLightCoordinator(DataUpdateCoordinator):
    """Motion Light coordinator."""

    def __init__(self, hass: HomeAssistant, entry) -> None:
        """Initialize coordinator."""
        self.entry = entry
        self.logger = PrefixLoggerAdapter(_LOGGER, {"name": entry.title})
        
        super().__init__(
            hass,
            self.logger,
            name=f"Motion Light {entry.title}",
        )
        
        self.hass = hass
        
        self.switch_entities = _get_config_value(entry, CONF_SWITCH_ENTITIES, [])
        self.main_sensors = _get_config_value(entry, CONF_MAIN_SENSORS, [])
        self.extend_sensors = _get_config_value(entry, CONF_EXTEND_SENSORS, [])
        self.lux_sensor = _get_config_value(entry, CONF_LUX_SENSOR)
        self.force_stop_sensor = _get_config_value(entry, CONF_FORCE_STOP_SENSOR)
        self.force_stop_state = _get_config_value(entry, CONF_FORCE_STOP_STATE, "off")

        # Settings
        self.motion_filter = DEFAULT_MOTION_FILTER
        self.off_delay = DEFAULT_OFF_DELAY
        self.lux_threshold = DEFAULT_LUX_THRESHOLD
        self.lux_cooldown = DEFAULT_LUX_COOLDOWN
        self.manual_idle_timeout = DEFAULT_MANUAL_IDLE_TIMEOUT
        self.manual_off_cooldown = DEFAULT_MANUAL_OFF_COOLDOWN
        self.respect_manual = DEFAULT_RESPECT_MANUAL

        # State management
        self._state = STATE_IDLE
        self._attributes = {}
        self._enabled = True

        # Listeners
        self._unsub_main_listeners = []
        self._unsub_extend_listeners = []
        self._unsub_target_listeners = []
        self._unsub_force_stop_listener = None

        # Timers
        self._motion_detect_timer = None
        self._off_delay_timer = None
        self._lux_cooldown_timer = None
        self._lux_check_timer = None
        self._manual_idle_timer = None
        self._manual_off_cooldown_timer = None

        # Context & Flags
        self._lux_cooldown_active = False

    @property
    def state(self):
        """Return current state."""
        return self._state

    @property
    def attributes(self):
        """Return current attributes."""
        attrs = self._attributes.copy()
        attrs["switch_entities"] = self.switch_entities
        attrs["main_sensors"] = self.main_sensors
        attrs["extend_sensors"] = self.extend_sensors
        attrs["lux_sensor"] = self.lux_sensor
        attrs["force_stop_sensor"] = self.force_stop_sensor
        attrs["force_stop_state"] = self.force_stop_state
        attrs["force_stop_active"] = self._state == STATE_FORCE_STOPPED
        attrs["active_main_sensors"] = self._get_active_main_sensors()
        attrs["active_extend_sensors"] = self._get_active_extend_sensors()
        attrs["lux_value"] = self._get_current_lux()
        attrs["lux_cooldown_active"] = self._lux_cooldown_active
        attrs["lux_check_active"] = self._lux_check_timer is not None
        return attrs

    @property
    def is_enabled(self) -> bool:
        """Return if integration is enabled."""
        return self._enabled

    async def set_enabled(self, enabled: bool) -> None:
        """Set enabled state."""
        self._enabled = enabled
        self.logger.info("Motion Light %s", "enabled" if enabled else "disabled")
        if not enabled:
            if self._state in (STATE_ON, STATE_DELAYING, STATE_ACTIVE):
                await self._turn_off_switches()
            self._stop_lux_check_timer()
            await self._update_state(STATE_DISABLED)
        else:
            if self._state == STATE_DISABLED:
                await self._update_state(STATE_IDLE)

    def set_motion_filter(self, value: float) -> None:
        self.motion_filter = int(value)
        self.logger.info("Motion filter set to %d sec", self.motion_filter)

    def set_off_delay(self, value: float) -> None:
        self.off_delay = int(value)
        self.logger.info("Off delay set to %d sec", self.off_delay)

    def set_lux_threshold(self, value: float) -> None:
        self.lux_threshold = int(value)
        self.logger.info("Lux threshold set to %d", self.lux_threshold)

    def set_lux_cooldown(self, value: float) -> None:
        self.lux_cooldown = int(value)
        self.logger.info("Lux cooldown set to %d sec", self.lux_cooldown)

    def set_manual_idle_timeout(self, value: float) -> None:
        self.manual_idle_timeout = int(value)
        self.logger.info("Manual idle timeout set to %d sec", self.manual_idle_timeout)
        if self.manual_idle_timeout <= 0 and self._manual_idle_timer:
            self.logger.info("Manual idle timeout set to 0, cancelling active timer")
            self._manual_idle_timer()
            self._manual_idle_timer = None

    def set_manual_off_cooldown(self, value: float) -> None:
        self.manual_off_cooldown = int(value)
        self.logger.info("Manual off cooldown set to %d sec", self.manual_off_cooldown)

    def set_respect_manual(self, value: bool) -> None:
        self.respect_manual = value
        self.logger.info("Respect manual set to %s", value)

    async def async_setup(self):
        """Set up the coordinator."""
        self.logger.info("Setting up Motion Light coordinator")
        self.logger.info("Switches: %s, Main sensors: %s, Extend sensors: %s, Lux: %s",
                         self.switch_entities, self.main_sensors, self.extend_sensors, self.lux_sensor)
        
        # Проверяем состояние force_stop_sensor при старте
        if self.force_stop_sensor:
            force_stop_state_obj = self.hass.states.get(self.force_stop_sensor)
            if force_stop_state_obj and force_stop_state_obj.state == self.force_stop_state:
                self.logger.info("Force stop sensor is already in stop state at startup")
                await self._update_state(STATE_FORCE_STOPPED)
                await self._start_listening()
                return

        any_on = any(
            self.hass.states.get(s) and self.hass.states.get(s).state == "on"
            for s in self.switch_entities
        )
        if any_on:
            self.logger.info("Some switches are ON at startup, entering manual_on")
            await self._enter_manual_on()
        else:
            await self._update_state(STATE_IDLE)
            
        await self._start_listening()

    async def async_shutdown(self):
        """Shut down the coordinator."""
        self.logger.info("Shutting down Motion Light coordinator")
        await self._stop_listening()
        self._cancel_all_timers()

    async def _update_state(self, state, **attributes):
        """Update state and attributes."""
        old_state = self._state
        self._state = state
        self._attributes.update(attributes)
        self.logger.debug("State changed: %s → %s", old_state, state)
        self.async_set_updated_data({
            "state": state,
            "attributes": self.attributes,
        })

    async def _start_listening(self):
        """Start listening to sensors."""
        self.logger.info("Starting to listen to main sensors: %s", self.main_sensors)
        for sensor in self.main_sensors:
            unsub = async_track_state_change_event(
                self.hass, [sensor], self._main_sensor_state_changed
            )
            self._unsub_main_listeners.append(unsub)

        self.logger.info("Starting to listen to extend sensors: %s", self.extend_sensors)
        for sensor in self.extend_sensors:
            unsub = async_track_state_change_event(
                self.hass, [sensor], self._extend_sensor_state_changed
            )
            self._unsub_extend_listeners.append(unsub)

        self.logger.info("Starting to listen to target switches: %s", self.switch_entities)
        for switch in self.switch_entities:
            unsub = async_track_state_change_event(
                self.hass, [switch], self._target_state_changed
            )
            self._unsub_target_listeners.append(unsub)

        if self.force_stop_sensor:
            self.logger.info("Force stop sensor: %s → %s",
                             self.force_stop_sensor, self.force_stop_state)
            self._unsub_force_stop_listener = async_track_state_change_event(
                self.hass, [self.force_stop_sensor], self._force_stop_state_changed
            )

    async def _stop_listening(self):
        """Stop listening to sensors."""
        for unsub in self._unsub_main_listeners:
            unsub()
        self._unsub_main_listeners = []
        for unsub in self._unsub_extend_listeners:
            unsub()
        self._unsub_extend_listeners = []
        for unsub in self._unsub_target_listeners:
            unsub()
        self._unsub_target_listeners = []
        if self._unsub_force_stop_listener:
            self._unsub_force_stop_listener()
            self._unsub_force_stop_listener = None

    @callback
    def _main_sensor_state_changed(self, event):
        """Handle main sensor state change."""
        old_state = event.data.get("old_state")
        new_state = event.data.get("new_state")
        if not new_state:
            return

        sensor_entity = event.data.get("entity_id")
        old_s = old_state.state if old_state else None
        new_s = new_state.state

        self.logger.debug("Main sensor event: %s %s → %s", sensor_entity, old_s, new_s)

        if new_s == "on" and old_s != "on":
            self.logger.debug("Main sensor FRONT UP: %s", sensor_entity)
            self.hass.async_create_task(self._handle_main_sensor_on(sensor_entity))
        elif old_s == "on" and new_s != "on":
            self.logger.debug("Main sensor FRONT DOWN: %s", sensor_entity)
            self.hass.async_create_task(self._handle_main_sensor_off())

    @callback
    def _extend_sensor_state_changed(self, event):
        """Handle extend sensor state change."""
        old_state = event.data.get("old_state")
        new_state = event.data.get("new_state")
        if not new_state:
            return

        sensor_entity = event.data.get("entity_id")
        old_s = old_state.state if old_state else None
        new_s = new_state.state

        self.logger.debug("Extend sensor event: %s %s → %s", sensor_entity, old_s, new_s)

        if new_s == "on" and old_s != "on":
            self.logger.debug("Extend sensor FRONT UP: %s", sensor_entity)
            self.hass.async_create_task(self._handle_extend_sensor_on(sensor_entity))

    async def _handle_main_sensor_on(self, triggered_by):
        """Handle main sensor ON - can turn on light."""
        if not self._enabled:
            self.logger.debug("Integration disabled, ignoring")
            return

        # БЛОКИРОВЩИК: Игнорируем движение, если активна принудительная остановка
        if self._state == STATE_FORCE_STOPPED:
            self.logger.debug("Ignoring during force_stopped")
            return

        self.logger.debug("Main sensor ON by %s, current state: %s", triggered_by, self._state)

        if self._state == STATE_MANUAL_OFF_COOLDOWN:
            self.logger.debug("Ignoring during manual_off_cooldown")
            return

        if self._state == STATE_MANUAL_ON:
            self.logger.debug("During manual_on, resetting idle timer")
            if self.manual_idle_timeout > 0:
                self._reset_manual_idle_timer()
            return

        if self._state in (STATE_ON, STATE_ACTIVE):
            self.logger.debug("Already on/active, updating time")
            self._attributes["last_motion_time"] = dt_util.utcnow().isoformat()
            return

        if self._state == STATE_DETECTING:
            self.logger.debug("Already detecting, ignoring")
            return

        if self._state == STATE_DELAYING:
            self.logger.info("Main sensor ON during off-delay, extending")
            if self._off_delay_timer:
                self._off_delay_timer()
                self._off_delay_timer = None
            await self._update_state(STATE_ACTIVE)
            if self.off_delay > 0:
                self._off_delay_timer = async_call_later(
                    self.hass,
                    self.off_delay,
                    self._turn_off_after_delay,
                )
            return

        if self._off_delay_timer:
            self._off_delay_timer()
            self._off_delay_timer = None

        await self._update_state(STATE_DETECTING, triggered_by=triggered_by)

        if self.motion_filter > 0:
            self.logger.debug("Starting motion filter timer for %d seconds", self.motion_filter)
            try:
                self._motion_detect_timer = async_call_later(
                    self.hass,
                    self.motion_filter,
                    self._turn_on_after_filter,
                )
            except Exception as err:
                self.logger.error("Failed to create motion filter timer: %s", err)
                await self._turn_on_after_filter(None)
        else:
            await self._turn_on_after_filter(None)

    async def _handle_main_sensor_off(self):
        """Handle main sensor OFF - start delay."""
        self.logger.debug("Main sensor OFF, current state: %s", self._state)

        if self._is_any_main_sensor_active():
            self.logger.debug("Some main sensor still active, ignoring")
            return

        self.logger.debug("All main sensors are off")
        self._stop_lux_check_timer()

        if self._state in (STATE_ON, STATE_ACTIVE):
            self.logger.debug("Transitioning to DELAYING state")
            await self._update_state(STATE_DELAYING)
            if self._off_delay_timer:
                self._off_delay_timer()
                self._off_delay_timer = None
            if self.off_delay > 0:
                self.logger.debug("Starting off-delay timer for %d seconds", self.off_delay)
                try:
                    self._off_delay_timer = async_call_later(
                        self.hass,
                        self.off_delay,
                        self._turn_off_after_delay,
                    )
                except Exception as err:
                    self.logger.error("Failed to create off-delay timer: %s", err)
                    await self._turn_off_after_delay(None)
            else:
                self.logger.debug("No off-delay, turning off immediately")
                await self._turn_off_after_delay(None)

        elif self._state == STATE_DETECTING:
            if self._motion_detect_timer:
                self._motion_detect_timer()
                self._motion_detect_timer = None
            await self._update_state(STATE_IDLE)

    async def _handle_extend_sensor_on(self, triggered_by):
        """Handle extend sensor ON - only extend, never turn on."""
        if not self._enabled:
            self.logger.debug("Integration disabled, ignoring")
            return

        # БЛОКИРОВЩИК: Игнорируем движение, если активна принудительная остановка
        if self._state == STATE_FORCE_STOPPED:
            self.logger.debug("Ignoring during force_stopped")
            return

        self.logger.debug("Extend sensor ON by %s, current state: %s", triggered_by, self._state)

        if self._state == STATE_IDLE:
            self.logger.debug("Extend sensor ignored: in idle state")
            return

        if self._state == STATE_MANUAL_OFF_COOLDOWN:
            self.logger.debug("Ignoring during manual_off_cooldown")
            return

        if self._state == STATE_MANUAL_ON:
            self.logger.debug("During manual_on, resetting idle timer")
            if self.manual_idle_timeout > 0:
                self._reset_manual_idle_timer()
            return

        if self._state in (STATE_ON, STATE_ACTIVE):
            self.logger.debug("Already on/active, updating time")
            self._attributes["last_motion_time"] = dt_util.utcnow().isoformat()
            return

        if self._state == STATE_DETECTING:
            self.logger.debug("Already detecting, ignoring")
            return

        if self._state == STATE_DELAYING:
            self.logger.info("Extend sensor ON during off-delay, extending")
            if self._off_delay_timer:
                self._off_delay_timer()
                self._off_delay_timer = None
            await self._update_state(STATE_ACTIVE)
            if self.off_delay > 0:
                self._off_delay_timer = async_call_later(
                    self.hass,
                    self.off_delay,
                    self._turn_off_after_delay,
                )
            return

    @callback
    def _target_state_changed(self, event):
        """Handle target switch state change."""
        if not self.respect_manual:
            return

        # БЛОКИРОВЩИК: Игнорируем ручные переключения, если активна принудительная остановка
        if self._state == STATE_FORCE_STOPPED:
            self.logger.debug("Ignoring manual change during force_stopped")
            return
            
        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")
        if not new_state or not old_state:
            return
            
        if new_state.state == old_state.state:
            return

        ctx = new_state.context
        if ctx and ctx.id and ctx.id.startswith(f"motion_light_{self.entry.entry_id}_"):
            self.logger.debug("State change from our context (%s), ignoring", ctx.id)
            return

        entity_id = event.data["entity_id"]
        self.logger.info("Manual change detected on %s: %s → %s", 
                         entity_id, old_state.state, new_state.state)

        if new_state.state == "off" and old_state.state == "on":
            if self._state in (STATE_ON, STATE_DELAYING, STATE_ACTIVE, STATE_MANUAL_ON):
                self.logger.info("Manual OFF during our control → entering cooldown")
                self._cancel_off_delay()
                self._stop_lux_check_timer()
                
                if self._manual_idle_timer:
                    self._manual_idle_timer()
                    self._manual_idle_timer = None
                    
                self.hass.async_create_task(self._enter_manual_off_cooldown())
                return

        if new_state.state == "on" and old_state.state == "off":
            if self._state in (STATE_IDLE, STATE_DETECTING, STATE_MANUAL_OFF_COOLDOWN):
                self.logger.info("Manual ON → entering manual_on with idle timeout")
                self._cancel_motion_filter()
                self._stop_lux_check_timer()
                self.hass.async_create_task(self._enter_manual_on())
                return

    @callback
    def _force_stop_state_changed(self, event):
        """Handle force stop sensor state change."""
        new_state = event.data.get("new_state")
        if not new_state:
            return

        # Если датчик перешел в блокирующее состояние
        if new_state.state == self.force_stop_state:
            self.logger.info("Force stop triggered by %s", event.data.get("entity_id"))
            self.hass.async_create_task(self._enter_force_stop())
        # Если датчик вышел из блокирующего состояния
        else:
            self.logger.info("Force stop released by %s", event.data.get("entity_id"))
            self.hass.async_create_task(self._exit_force_stop())

    async def _enter_force_stop(self):
        """Enter force_stopped state."""
        self.logger.info("Entering force_stopped state")
        self._cancel_all_timers()
        if self._state in (STATE_ON, STATE_DELAYING, STATE_ACTIVE, STATE_MANUAL_ON):
            await self._turn_off_switches()
        await self._update_state(STATE_FORCE_STOPPED)

    async def _exit_force_stop(self):
        """Exit force_stopped state to idle."""
        self.logger.info("Exiting force_stopped state")
        await self._update_state(STATE_IDLE)

    def _is_any_main_sensor_active(self) -> bool:
        """Check if any main sensor is currently in 'on' state."""
        for sensor in self.main_sensors:
            state = self.hass.states.get(sensor)
            if state and state.state == "on":
                return True
        return False

    def _is_any_extend_sensor_active(self) -> bool:
        """Check if any extend sensor is currently in 'on' state."""
        for sensor in self.extend_sensors:
            state = self.hass.states.get(sensor)
            if state and state.state == "on":
                return True
        return False

    def _is_any_sensor_active(self) -> bool:
        """Check if any sensor (main or extend) is active."""
        return self._is_any_main_sensor_active() or self._is_any_extend_sensor_active()

    def _get_active_main_sensors(self) -> list:
        """Return list of active main sensors."""
        return [
            s for s in self.main_sensors
            if self.hass.states.get(s) and self.hass.states.get(s).state == "on"
        ]

    def _get_active_extend_sensors(self) -> list:
        """Return list of active extend sensors."""
        return [
            s for s in self.extend_sensors
            if self.hass.states.get(s) and self.hass.states.get(s).state == "on"
        ]

    def _get_current_lux(self) -> float | None:
        """Get current lux value from sensor."""
        if not self.lux_sensor:
            return None
        state = self.hass.states.get(self.lux_sensor)
        if not state or state.state in ("unknown", "unavailable"):
            return None
        try:
            return float(state.state)
        except (ValueError, TypeError):
            return None

    async def _should_turn_on_by_lux(self) -> bool:
        """Check if we should turn on based on lux."""
        if not self.lux_sensor:
            return True
        if self._lux_cooldown_active:
            self.logger.debug("Lux cooldown active, ignoring sensor")
            return True
        lux = self._get_current_lux()
        if lux is None:
            return True
        return lux < self.lux_threshold

    def _start_lux_check_timer(self):
        """Start periodic lux check timer."""
        if not self.lux_sensor:
            self.logger.debug("No lux sensor, not starting lux check timer")
            return
        if self._lux_check_timer:
            self.logger.debug("Lux check timer already running")
            return
        self.logger.info("Starting lux check timer (interval=%d sec)", LUX_CHECK_INTERVAL)
        self._lux_check_timer = async_call_later(
            self.hass,
            LUX_CHECK_INTERVAL,
            self._check_lux_periodically,
        )

    def _stop_lux_check_timer(self):
        """Stop periodic lux check timer."""
        if self._lux_check_timer:
            self.logger.debug("Stopping lux check timer")
            self._lux_check_timer()
            self._lux_check_timer = None

    @callback
    def _check_lux_periodically(self, _=None):
        """Check lux periodically."""
        self._lux_check_timer = None
        if not self._is_any_sensor_active():
            self.logger.debug("No sensors active, not checking lux")
            return
        if self._state not in (STATE_IDLE, STATE_DETECTING):
            self.logger.debug("State is %s, not checking lux", self._state)
            return

        lux = self._get_current_lux()
        if lux is None:
            self.logger.debug("Lux value unavailable, restarting timer")
            self._start_lux_check_timer()
            return

        self.logger.debug("[Lux check] lux=%.1f, threshold=%d", lux, self.lux_threshold)
        if lux < self.lux_threshold:
            self.logger.info("[Lux check] Dark enough, turning on lights")
            self.hass.async_create_task(self._turn_on_after_lux_check())
        else:
            self.logger.debug("[Lux check] Still bright, restarting timer")
            self._start_lux_check_timer()

    async def _turn_on_after_lux_check(self):
        """Turn on lights after periodic lux check."""
        if self._lux_cooldown_active:
            self.logger.debug("Lux cooldown active, not turning on")
            return
        if self._state not in (STATE_IDLE, STATE_DETECTING):
            self.logger.debug("State changed to %s, not turning on", self._state)
            return
        if not self._is_any_sensor_active():
            self.logger.debug("No sensors active, not turning on")
            return

        triggered_by = self._attributes.get("triggered_by")
        await self._turn_on_switches()
        await self._update_state(STATE_ON, triggered_by=triggered_by)

    async def _turn_on_after_filter(self, _=None):
        """Turn on after motion filter."""
        self.logger.debug("Turning on after filter")
        self._motion_detect_timer = None

        if not await self._should_turn_on_by_lux():
            self.logger.debug("Too bright, not turning on — starting lux check timer")
            await self._update_state(STATE_IDLE)
            self._start_lux_check_timer()
            return

        triggered_by = self._attributes.get("triggered_by")
        await self._turn_on_switches()
        await self._update_state(STATE_ON, triggered_by=triggered_by)

    async def _turn_off_after_delay(self, _=None):
        """Turn off after off-delay."""
        self.logger.debug("Off-delay timer expired")
        self._off_delay_timer = None

        if self._is_any_sensor_active():
            self.logger.info("Sensor is still active — staying on")
            await self._update_state(STATE_ON)
            return

        self.logger.info("No sensors active, turning off")
        await self._turn_off_switches()
        
        self._lux_cooldown_active = True
        if self.lux_cooldown > 0:
            self._lux_cooldown_timer = async_call_later(
                self.hass,
                self.lux_cooldown,
                self._lux_cooldown_expired,
            )
            self.logger.info("Lux cooldown started for %d sec", self.lux_cooldown)
            
        await self._update_state(STATE_OFF)
        async_call_later(self.hass, 1, self._transition_to_idle)

    @callback
    def _transition_to_idle(self, _=None):
        """Transition from off to idle."""
        if self._state == STATE_OFF:
            self.logger.debug("Transitioning from off to idle")
            self.hass.async_create_task(self._update_state(STATE_IDLE))

    async def _turn_on_switches(self) -> None:
        """Turn on switches/lights with our context."""
        ctx = Context(
            id=f"motion_light_{self.entry.entry_id}_{dt_util.utcnow().timestamp()}"
        )
        self.logger.info("Turning ON entities: %s", self.switch_entities)
        await self.hass.services.async_call(
            "homeassistant",
            "turn_on",
            {"entity_id": self.switch_entities},
            context=ctx,
        )

    async def _turn_off_switches(self) -> None:
        """Turn off switches/lights with our context."""
        ctx = Context(
            id=f"motion_light_{self.entry.entry_id}_{dt_util.utcnow().timestamp()}"
        )
        self.logger.info("Turning OFF entities: %s", self.switch_entities)
        await self.hass.services.async_call(
            "homeassistant",
            "turn_off",
            {"entity_id": self.switch_entities},
            context=ctx,
        )

    async def _enter_manual_on(self):
        """Enter manual_on state."""
        await self._update_state(STATE_MANUAL_ON)
        if self.manual_idle_timeout > 0:
            self._reset_manual_idle_timer()
        else:
            self.logger.info("Manual idle timeout is 0. 'Forgot to turn off' timer is disabled.")

    def _reset_manual_idle_timer(self):
        """Reset manual idle timer."""
        if self.manual_idle_timeout <= 0:
            return

        if self._manual_idle_timer:
            self._manual_idle_timer()
        self._manual_idle_timer = async_call_later(
            self.hass,
            self.manual_idle_timeout,
            self._manual_idle_timeout_expired,
        )
        self.logger.debug("Manual idle timer reset for %d sec", self.manual_idle_timeout)

    @callback
    def _manual_idle_timeout_expired(self, _=None):
        """Manual idle timeout expired — turn off."""
        self._manual_idle_timer = None
        self.logger.info("Manual idle timeout expired, turning off")
        self.hass.async_create_task(self._turn_off_switches_manual())

    async def _turn_off_switches_manual(self):
        """Turn off switches/lights in manual mode."""
        self.logger.info("Turning OFF entities (manual timeout): %s", self.switch_entities)
        await self.hass.services.async_call(
            "homeassistant",
            "turn_off",
            {"entity_id": self.switch_entities},
        )
        await self._update_state(STATE_OFF)
        async_call_later(self.hass, 1, self._transition_to_idle)

    async def _enter_manual_off_cooldown(self):
        """Enter manual_off_cooldown state."""
        await self._update_state(STATE_MANUAL_OFF_COOLDOWN)
        if self._manual_off_cooldown_timer:
            self._manual_off_cooldown_timer()
            
        if self.manual_off_cooldown > 0:
            self._manual_off_cooldown_timer = async_call_later(
                self.hass,
                self.manual_off_cooldown,
                self._manual_off_cooldown_expired,
            )
            self.logger.info("Manual off cooldown started for %d sec",
                             self.manual_off_cooldown)
        else:
            await self._update_state(STATE_IDLE)

    @callback
    def _manual_off_cooldown_expired(self, _=None):
        """Manual off cooldown expired."""
        self._manual_off_cooldown_timer = None
        self.logger.info("Manual off cooldown expired → idle")
        self.hass.async_create_task(self._update_state(STATE_IDLE))

    @callback
    def _lux_cooldown_expired(self, _=None):
        """Lux cooldown expired."""
        self._lux_cooldown_active = False
        self._lux_cooldown_timer = None
        self.logger.info("Lux cooldown expired")

    def _cancel_all_timers(self):
        """Cancel all timers."""
        if self._motion_detect_timer:
            self._motion_detect_timer()
            self._motion_detect_timer = None
        if self._off_delay_timer:
            self._off_delay_timer()
            self._off_delay_timer = None
        if self._lux_cooldown_timer:
            self._lux_cooldown_timer()
            self._lux_cooldown_timer = None
        if self._lux_check_timer:
            self._lux_check_timer()
            self._lux_check_timer = None
        if self._manual_idle_timer:
            self._manual_idle_timer()
            self._manual_idle_timer = None
        if self._manual_off_cooldown_timer:
            self._manual_off_cooldown_timer()
            self._manual_off_cooldown_timer = None

    def _cancel_motion_filter(self):
        """Cancel motion filter timer."""
        if self._motion_detect_timer:
            self._motion_detect_timer()
            self._motion_detect_timer = None

    def _cancel_off_delay(self):
        """Cancel off-delay timer."""
        if self._off_delay_timer:
            self._off_delay_timer()
            self._off_delay_timer = None