"""Sensor platform for Motion Light."""
from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.device_registry import DeviceInfo
from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Motion Light sensor."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([MotionLightStatusSensor(coordinator, entry)])


class MotionLightStatusSensor(CoordinatorEntity, SensorEntity):
    """Representation of a Motion Light status sensor."""

    _attr_translation_key = "motion_light_status"
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator, entry):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entry = entry
        self._attr_unique_id = f"{entry.entry_id}_status"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Motion Light",
            model="Switch Control Integration",
        )
        self._icon_map = {
            "idle": "mdi:sleep",
            "detecting": "mdi:motion-sensor",
            "on": "mdi:lightbulb-on",
            "delaying": "mdi:timer-sand",
            "active": "mdi:lightbulb-on-outline",
            "off": "mdi:lightbulb-off-outline",
            "manual_on": "mdi:hand-back-left",
            "manual_off_cooldown": "mdi:timer-pause",
            "error": "mdi:alert-circle",
            "disabled": "mdi:lightbulb-off",
        }

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self.coordinator.state

    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        return self.coordinator.attributes

    @property
    def icon(self):
        """Return the icon."""
        return self._icon_map.get(self.coordinator.state, "mdi:lightbulb")

    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()