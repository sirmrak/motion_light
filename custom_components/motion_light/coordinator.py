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
        
        super().__init__(hass, self.logger, name=f"Motion Light {entry.title}")
        
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

        # Flags
        self._lux_cooldown_active = False

    @property
    def state(self):
        return self._state

    @property
    def attributes(self):
        attrs = self._attributes.copy()
        attrs.update({
            "switch_entities": self.switch_entities,
            "main_sensors": self.main_sensors,
            "extend_sensors": self.extend_sensors,
            "lux_sensor": self.lux_sensor,
            "force_stop_sensor": self.force_stop_sensor,
            "force_stop_state": self.force_stop_state,
            "force_stop_active": self._state == STATE_FORCE_STOPPED,
            "active_main_sensors": self._get_active_sensors(self.main_sensors),
            "active_extend_sensors": self._get_active_sensors(self.extend_sensors),
            "lux_value": self._get_current_lux(),
            "lux_cooldown_active": self._lux_cooldown_active,
            "lux_check_active": self._lux_check_timer is not None,
        })
        return attrs

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    async def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        self.logger.info("Motion Light %s", "enabled" if enabled else "disabled")
        if not enabled:
            if self._state in (STATE_ON, STATE_DELAYING, STATE_ACTIVE):
                await self._turn_off_switches()
            self._stop_lux_check_timer()
            await self._update_state(STATE_DISABLED)
        elif self._state == STATE_DISABLED:
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
        if self.manual_idle_timeout <= 0:
            self._cancel_timer("_manual_idle_timer")

    def set_manual_off_cooldown(self, value: float) -> None:
        self.manual_off_cooldown = int(value)
        self.logger.info("Manual off cooldown set to %d sec", self.manual_off_cooldown)

    def set_respect_manual(self, value: bool) -> None:
        self.respect_manual = value
        self.logger.info("Respect manual set to %s", value)

    async def async_setup(self):
        self.logger.info("Setting up Motion Light coordinator")
        
        if self.force_stop_sensor:
            state_obj = self.hass.states.get(self.force_stop_sensor)
            if state_obj and state_obj.state == self.force_stop_state:
                self.logger.info("Force stop sensor is already in stop state at startup")
                await self._update_state(STATE_FORCE_STOPPED)
                await self._start_listening()
                return

        any_on = any(self.hass.states.get(s) and self.hass.states.get(s).state == "on" for s in self.switch_entities)
        if any_on:
            self.logger.info("Some switches are ON at startup, entering manual_on")
            await self._enter_manual_on()
        else:
            await self._update_state(STATE_IDLE)
            
        await self._start_listening()

    async def async_shutdown(self):
        self.logger.info("Shutting down Motion Light coordinator")
        await self._stop_listening()
        self._cancel_all_timers()

    async def _update_state(self, state, **attributes):
        old_state = self._state
        self._state = state
        self._attributes.update(attributes)
        self.logger.debug("State changed: %s → %s", old_state, state)
        self.async_set_updated_data({"state": state, "attributes": self.attributes})

    async def _start_listening(self):
        for sensor in self.main_sensors:
            self._unsub_main_listeners.append(async_track_state_change_event(self.hass, [sensor], self._main_sensor_state_changed))
        for sensor in self.extend_sensors:
            self._unsub_extend_listeners.append(async_track_state_change_event(self.hass, [sensor], self._extend_sensor_state_changed))
        for switch in self.switch_entities:
            self._unsub_target_listeners.append(async_track_state_change_event(self.hass, [switch], self._target_state_changed))
        if self.force_stop_sensor:
            self._unsub_force_stop_listener = async_track_state_change_event(self.hass, [self.force_stop_sensor], self._force_stop_state_changed)

    async def _stop_listening(self):
        for unsub in self._unsub_main_listeners + self._unsub_extend_listeners + self._unsub_target_listeners:
            unsub()
        self._unsub_main_listeners = self._unsub_extend_listeners = self._unsub_target_listeners = []
        if self._unsub_force_stop_listener:
            self._unsub_force_stop_listener()
            self._unsub_force_stop_listener = None

    @callback
    def _main_sensor_state_changed(self, event):
        new_state = event.data.get("new_state")
        if not new_state: return
        old_s = event.data.get("old_state").state if event.data.get("old_state") else None
        new_s = new_state.state
        if new_s == "on" and old_s != "on":
            self.hass.async_create_task(self._handle_sensor_on(event.data["entity_id"], is_main=True))
        elif old_s == "on" and new_s != "on":
            self.hass.async_create_task(self._handle_main_sensor_off())

    @callback
    def _extend_sensor_state_changed(self, event):
        new_state = event.data.get("new_state")
        if not new_state: return
        old_s = event.data.get("old_state").state if event.data.get("old_state") else None
        new_s = new_state.state
        if new_s == "on" and old_s != "on":
            self.hass.async_create_task(self._handle_sensor_on(event.data["entity_id"], is_main=False))

    async def _handle_sensor_on(self, triggered_by: str, is_main: bool):
        """Universal handler for sensor ON events (main or extend)."""
        if not self._enabled or self._state == STATE_FORCE_STOPPED or self._state == STATE_MANUAL_OFF_COOLDOWN:
            return

        sensor_type = "Main" if is_main else "Extend"
        self.logger.debug("%s sensor ON by %s, current state: %s", sensor_type, triggered_by, self._state)

        if self._state == STATE_MANUAL_ON:
            if is_main:
                all_on = all(self.hass.states.get(s) and self.hass.states.get(s).state == "on" for s in self.switch_entities)
                if not all_on:
                    self.logger.info("Motion during manual_on, turning on remaining switches and switching to auto mode.")
                    self._cancel_timer("_manual_idle_timer")
                    await self._turn_on_switches()
                    await self._update_state(STATE_ON, triggered_by=triggered_by)
                    return
            if self.manual_idle_timeout > 0:
                self._reset_manual_idle_timer()
            return

        if self._state == STATE_ON:
            self._attributes["last_motion_time"] = dt_util.utcnow().isoformat()
            return

        if self._state == STATE_ACTIVE:
            self._attributes["last_motion_time"] = dt_util.utcnow().isoformat()
            self._cancel_timer("_off_delay_timer")
            self._start_timer("_off_delay_timer", self.off_delay, self._turn_off_after_delay)
            return

        if self._state == STATE_DETECTING:
            return

        if self._state == STATE_DELAYING:
            self.logger.info("%s sensor ON during off-delay, extending", sensor_type)
            self._cancel_timer("_off_delay_timer")
            await self._update_state(STATE_ACTIVE)
            self._start_timer("_off_delay_timer", self.off_delay, self._turn_off_after_delay)
            return

        # IDLE state
        if not is_main:
            return  # Extend sensors cannot turn on light from idle

        await self._update_state(STATE_DETECTING, triggered_by=triggered_by)
        if self.motion_filter > 0:
            self._start_timer("_motion_detect_timer", self.motion_filter, self._turn_on_after_filter)
        else:
            await self._turn_on_after_filter(None)

    async def _handle_main_sensor_off(self):
        if self._is_any_sensor_from_list_active(self.main_sensors):
            return
        self._stop_lux_check_timer()

        if self._state in (STATE_ON, STATE_ACTIVE):
            await self._update_state(STATE_DELAYING)
            self._cancel_timer("_off_delay_timer")
            self._start_timer("_off_delay_timer", self.off_delay, self._turn_off_after_delay)
        elif self._state == STATE_DETECTING:
            self._cancel_timer("_motion_detect_timer")
            await self._update_state(STATE_IDLE)

    @callback
    def _target_state_changed(self, event):
        if not self.respect_manual or self._state == STATE_FORCE_STOPPED:
            return
        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")
        if not new_state or not old_state or new_state.state == old_state.state:
            return

        ctx = new_state.context
        if ctx and ctx.id and ctx.id.startswith(f"motion_light_{self.entry.entry_id}_"):
            return

        entity_id = event.data["entity_id"]
        self.logger.info("Manual change detected on %s: %s → %s", entity_id, old_state.state, new_state.state)

        if new_state.state == "off" and old_state.state == "on":
            if self._state in (STATE_ON, STATE_DELAYING, STATE_ACTIVE, STATE_MANUAL_ON):
                self._cancel_timer("_off_delay_timer")
                self._cancel_timer("_manual_idle_timer")
                self._stop_lux_check_timer()
                self.hass.async_create_task(self._enter_manual_off_cooldown())
        elif new_state.state == "on" and old_state.state == "off":
            if self._state in (STATE_IDLE, STATE_DETECTING, STATE_MANUAL_OFF_COOLDOWN):
                self._cancel_timer("_motion_detect_timer")
                self._stop_lux_check_timer()
                self.hass.async_create_task(self._enter_manual_on())

    @callback
    def _force_stop_state_changed(self, event):
        new_state = event.data.get("new_state")
        if not new_state: return
        if new_state.state == self.force_stop_state:
            self.hass.async_create_task(self._enter_force_stop())
        else:
            self.hass.async_create_task(self._exit_force_stop())

    async def _enter_force_stop(self):
        self._cancel_all_timers()
        if self._state in (STATE_ON, STATE_DELAYING, STATE_ACTIVE, STATE_MANUAL_ON):
            await self._turn_off_switches()
        await self._update_state(STATE_FORCE_STOPPED)

    async def _exit_force_stop(self):
        await self._update_state(STATE_IDLE)

    # --- Универсальные методы для сенсоров ---
    def _is_any_sensor_from_list_active(self, sensors: list) -> bool:
        return any(self.hass.states.get(s) and self.hass.states.get(s).state == "on" for s in sensors)

    def _get_active_sensors(self, sensors: list) -> list:
        return [s for s in sensors if self.hass.states.get(s) and self.hass.states.get(s).state == "on"]

    def _is_any_main_sensor_active(self) -> bool:
        return self._is_any_sensor_from_list_active(self.main_sensors)

    def _is_any_extend_sensor_active(self) -> bool:
        return self._is_any_sensor_from_list_active(self.extend_sensors)

    def _is_any_sensor_active(self) -> bool:
        return self._is_any_main_sensor_active() or self._is_any_extend_sensor_active()

    # --- Lux и таймеры ---
    def _get_current_lux(self) -> float | None:
        if not self.lux_sensor: return None
        state = self.hass.states.get(self.lux_sensor)
        if not state or state.state in ("unknown", "unavailable"): return None
        try: return float(state.state)
        except (ValueError, TypeError): return None

    async def _should_turn_on_by_lux(self) -> bool:
        if not self.lux_sensor or self._lux_cooldown_active: return True
        lux = self._get_current_lux()
        return lux is None or lux < self.lux_threshold

    def _start_lux_check_timer(self):
        if not self.lux_sensor or self._lux_check_timer: return
        self._lux_check_timer = async_call_later(self.hass, LUX_CHECK_INTERVAL, self._check_lux_periodically)
        self.async_set_updated_data({"state": self._state, "attributes": self.attributes})

    def _stop_lux_check_timer(self):
        if self._lux_check_timer:
            self._cancel_timer("_lux_check_timer")
            self.async_set_updated_data({"state": self._state, "attributes": self.attributes})

    def _start_lux_cooldown(self):
        self._lux_cooldown_active = True
        if self.lux_cooldown > 0:
            self._cancel_timer("_lux_cooldown_timer")
            self._lux_cooldown_timer = async_call_later(self.hass, self.lux_cooldown, self._lux_cooldown_expired)
            self.async_set_updated_data({"state": self._state, "attributes": self.attributes})

    def _cancel_lux_cooldown(self):
        if self._lux_cooldown_active:
            self._lux_cooldown_active = False
            self._cancel_timer("_lux_cooldown_timer")
            self.async_set_updated_data({"state": self._state, "attributes": self.attributes})

    @callback
    def _check_lux_periodically(self, _=None):
        self._lux_check_timer = None
        if not self._is_any_sensor_active() or self._state not in (STATE_IDLE, STATE_DETECTING):
            return
        lux = self._get_current_lux()
        if lux is None:
            self._start_lux_check_timer()
            return
        if lux < self.lux_threshold:
            self.hass.async_create_task(self._turn_on_after_lux_check())
        else:
            self._start_lux_check_timer()

    async def _turn_on_after_lux_check(self):
        if self._lux_cooldown_active or self._state not in (STATE_IDLE, STATE_DETECTING) or not self._is_any_sensor_active():
            return
        self._cancel_lux_cooldown()
        await self._turn_on_switches()
        await self._update_state(STATE_ON, triggered_by=self._attributes.get("triggered_by"))

    async def _turn_on_after_filter(self, _=None):
        self._cancel_timer("_motion_detect_timer")
        if not await self._should_turn_on_by_lux():
            await self._update_state(STATE_IDLE)
            self._start_lux_check_timer()
            return
        self._cancel_lux_cooldown()
        await self._turn_on_switches()
        await self._update_state(STATE_ON, triggered_by=self._attributes.get("triggered_by"))

    async def _turn_off_after_delay(self, _=None):
        self._cancel_timer("_off_delay_timer")
        if self._is_any_sensor_active():
            await self._update_state(STATE_ON)
            return
        await self._turn_off_switches()
        await self._start_lux_cooldown()
        await self._update_state(STATE_OFF)
        async_call_later(self.hass, 1, self._transition_to_idle)

    @callback
    def _transition_to_idle(self, _=None):
        if self._state == STATE_OFF:
            self.hass.async_create_task(self._update_state(STATE_IDLE))

    # --- Управление переключателями ---
    async def _turn_on_switches(self) -> None:
        ctx = Context(id=f"motion_light_{self.entry.entry_id}_{dt_util.utcnow().timestamp()}")
        await self.hass.services.async_call("homeassistant", "turn_on", {"entity_id": self.switch_entities}, context=ctx)

    async def _turn_off_switches(self) -> None:
        ctx = Context(id=f"motion_light_{self.entry.entry_id}_{dt_util.utcnow().timestamp()}")
        await self.hass.services.async_call("homeassistant", "turn_off", {"entity_id": self.switch_entities}, context=ctx)

    # --- Ручное управление ---
    async def _enter_manual_on(self):
        self._cancel_lux_cooldown()
        await self._update_state(STATE_MANUAL_ON)
        if self.manual_idle_timeout > 0:
            self._reset_manual_idle_timer()

    def _reset_manual_idle_timer(self):
        if self.manual_idle_timeout <= 0: return
        self._cancel_timer("_manual_idle_timer")
        self._manual_idle_timer = async_call_later(self.hass, self.manual_idle_timeout, self._manual_idle_timeout_expired)

    @callback
    def _manual_idle_timeout_expired(self, _=None):
        self.hass.async_create_task(self._turn_off_switches_manual())

    async def _turn_off_switches_manual(self):
        await self.hass.services.async_call("homeassistant", "turn_off", {"entity_id": self.switch_entities})
        await self._start_lux_cooldown()
        await self._update_state(STATE_OFF)
        async_call_later(self.hass, 1, self._transition_to_idle)

    async def _enter_manual_off_cooldown(self):
        await self._start_lux_cooldown()
        await self._update_state(STATE_MANUAL_OFF_COOLDOWN)
        if self.manual_off_cooldown > 0:
            self._start_timer("_manual_off_cooldown_timer", self.manual_off_cooldown, self._manual_off_cooldown_expired)
        else:
            await self._update_state(STATE_IDLE)

    @callback
    def _manual_off_cooldown_expired(self, _=None):
        self.hass.async_create_task(self._update_state(STATE_IDLE))

    @callback
    def _lux_cooldown_expired(self, _=None):
        self._lux_cooldown_active = False
        self._cancel_timer("_lux_cooldown_timer")
        self.async_set_updated_data({"state": self._state, "attributes": self.attributes})

    # --- Универсальные методы управления таймерами ---
    def _cancel_timer(self, timer_attr: str):
        timer = getattr(self, timer_attr, None)
        if timer:
            timer()
            setattr(self, timer_attr, None)

    def _start_timer(self, timer_attr: str, delay: float, callback):
        if delay > 0:
            setattr(self, timer_attr, async_call_later(self.hass, delay, callback))

    def _cancel_all_timers(self):
        self._cancel_timer("_motion_detect_timer")
        self._cancel_timer("_off_delay_timer")
        self._cancel_timer("_lux_cooldown_timer")
        self._cancel_timer("_lux_check_timer")
        self._cancel_timer("_manual_idle_timer")
        self._cancel_timer("_manual_off_cooldown_timer")