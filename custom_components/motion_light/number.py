"""Number platform for Motion Light settings."""
import logging
from homeassistant.components.number import NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.device_registry import DeviceInfo
from .const import (
    DOMAIN,
    CONF_LUX_SENSOR,
    ENTITY_MOTION_FILTER,
    ENTITY_OFF_DELAY,
    ENTITY_LUX_THRESHOLD,
    ENTITY_LUX_COOLDOWN,
    ENTITY_MANUAL_IDLE_TIMEOUT,
    ENTITY_MANUAL_OFF_COOLDOWN,
    DEFAULT_MOTION_FILTER,
    DEFAULT_OFF_DELAY,
    DEFAULT_LUX_THRESHOLD,
    DEFAULT_LUX_COOLDOWN,
    DEFAULT_MANUAL_IDLE_TIMEOUT,
    DEFAULT_MANUAL_OFF_COOLDOWN,
)

_LOGGER = logging.getLogger(__name__)


class PrefixLoggerAdapter(logging.LoggerAdapter):
    """Logger adapter that adds a prefix to log messages."""
    
    def process(self, msg, kwargs):
        """Add prefix to the log message."""
        return f"[{self.extra.get('name', 'Unknown')}] {msg}", kwargs


TRANSLATION_KEYS = {
    ENTITY_MOTION_FILTER: "motion_light_motion_filter",
    ENTITY_OFF_DELAY: "motion_light_off_delay",
    ENTITY_LUX_THRESHOLD: "motion_light_lux_threshold",
    ENTITY_LUX_COOLDOWN: "motion_light_lux_cooldown",
    ENTITY_MANUAL_IDLE_TIMEOUT: "motion_light_manual_idle_timeout",
    ENTITY_MANUAL_OFF_COOLDOWN: "motion_light_manual_off_cooldown",
}

ICONS = {
    ENTITY_MOTION_FILTER: "mdi:timer-outline",
    ENTITY_OFF_DELAY: "mdi:timer-sand",
    ENTITY_LUX_THRESHOLD: "mdi:brightness-5",
    ENTITY_LUX_COOLDOWN: "mdi:timer-pause",
    ENTITY_MANUAL_IDLE_TIMEOUT: "mdi:timer-alert",
    ENTITY_MANUAL_OFF_COOLDOWN: "mdi:timer-off",
}

UNITS = {
    ENTITY_MOTION_FILTER: UnitOfTime.SECONDS,
    ENTITY_OFF_DELAY: UnitOfTime.SECONDS,
    ENTITY_LUX_THRESHOLD: "lx",
    ENTITY_LUX_COOLDOWN: UnitOfTime.SECONDS,
    ENTITY_MANUAL_IDLE_TIMEOUT: UnitOfTime.SECONDS,
    ENTITY_MANUAL_OFF_COOLDOWN: UnitOfTime.SECONDS,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Motion Light number entities."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    
    lux_sensor = entry.options.get(CONF_LUX_SENSOR) or entry.data.get(CONF_LUX_SENSOR)
    
    entities = [
        MotionLightNumber(coordinator, entry, ENTITY_MOTION_FILTER, 0, 10, 1, DEFAULT_MOTION_FILTER),
        MotionLightNumber(coordinator, entry, ENTITY_OFF_DELAY, 0, 600, 5, DEFAULT_OFF_DELAY),
        MotionLightNumber(coordinator, entry, ENTITY_MANUAL_IDLE_TIMEOUT, 0, 3600, 30, DEFAULT_MANUAL_IDLE_TIMEOUT),
        MotionLightNumber(coordinator, entry, ENTITY_MANUAL_OFF_COOLDOWN, 0, 300, 5, DEFAULT_MANUAL_OFF_COOLDOWN),
    ]
    
    if lux_sensor:
        entities.extend([
            MotionLightNumber(coordinator, entry, ENTITY_LUX_THRESHOLD, 1, 1000, 10, DEFAULT_LUX_THRESHOLD),
            MotionLightNumber(coordinator, entry, ENTITY_LUX_COOLDOWN, 0, 300, 5, DEFAULT_LUX_COOLDOWN),
        ])
        
    async_add_entities(entities)

class MotionLightNumber(CoordinatorEntity, NumberEntity, RestoreEntity):
    """Representation of a Motion Light setting as a number entity."""
    _attr_has_entity_name = True

    def __init__(self, coordinator, entry, entity_id, min_val, max_val, step, default):
        """Initialize the number entity."""
        super().__init__(coordinator)
        self.entry = entry
        
        self.logger = PrefixLoggerAdapter(_LOGGER, {"name": entry.title})
        
        self._entity_suffix = entity_id
        self._attr_unique_id = f"{entry.entry_id}_{entity_id}"
        self._attr_translation_key = TRANSLATION_KEYS[entity_id]
        self._attr_native_min_value = min_val
        self._attr_native_max_value = max_val
        self._attr_native_step = step
        self._attr_native_unit_of_measurement = UNITS[entity_id]
        self._attr_icon = ICONS[entity_id]
        self._default_value = default
        self._attr_native_value = default
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Motion Light",
            model="Switch Control Integration",
        )

    @property
    def native_value(self) -> float:
        """Return the current value."""
        return self._attr_native_value

    async def async_set_native_value(self, value: float) -> None:
        """Update the current value."""
        self._attr_native_value = value
        self.logger.info("Setting %s to %s", self._entity_suffix, value)
        
        if self._entity_suffix == ENTITY_MOTION_FILTER:
            self.coordinator.set_motion_filter(value)
        elif self._entity_suffix == ENTITY_OFF_DELAY:
            self.coordinator.set_off_delay(value)
        elif self._entity_suffix == ENTITY_LUX_THRESHOLD:
            self.coordinator.set_lux_threshold(value)
        elif self._entity_suffix == ENTITY_LUX_COOLDOWN:
            self.coordinator.set_lux_cooldown(value)
        elif self._entity_suffix == ENTITY_MANUAL_IDLE_TIMEOUT:
            self.coordinator.set_manual_idle_timeout(value)
        elif self._entity_suffix == ENTITY_MANUAL_OFF_COOLDOWN:
            self.coordinator.set_manual_off_cooldown(value)
            
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Handle entity which will be added."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None:
            try:
                value = float(last_state.state)
                self._attr_native_value = value
                self.logger.info("Restored %s: %s", self._entity_suffix, value)
                
                if self._entity_suffix == ENTITY_MOTION_FILTER:
                    self.coordinator.set_motion_filter(value)
                elif self._entity_suffix == ENTITY_OFF_DELAY:
                    self.coordinator.set_off_delay(value)
                elif self._entity_suffix == ENTITY_LUX_THRESHOLD:
                    self.coordinator.set_lux_threshold(value)
                elif self._entity_suffix == ENTITY_LUX_COOLDOWN:
                    self.coordinator.set_lux_cooldown(value)
                elif self._entity_suffix == ENTITY_MANUAL_IDLE_TIMEOUT:
                    self.coordinator.set_manual_idle_timeout(value)
                elif self._entity_suffix == ENTITY_MANUAL_OFF_COOLDOWN:
                    self.coordinator.set_manual_off_cooldown(value)
            except (ValueError, TypeError):
                self.logger.warning("Could not restore %s, using default", self._entity_suffix)
        self.async_write_ha_state()

    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()