"""Switch platform for Motion Light."""
import logging
from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.device_registry import DeviceInfo
from .const import DOMAIN, ENTITY_RESPECT_MANUAL, DEFAULT_RESPECT_MANUAL

_LOGGER = logging.getLogger(__name__)


class PrefixLoggerAdapter(logging.LoggerAdapter):
    """Logger adapter that adds a prefix to log messages."""
    
    def process(self, msg, kwargs):
        """Add prefix to the log message."""
        return f"[{self.extra.get('name', 'Unknown')}] {msg}", kwargs


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Motion Light switches."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        MotionLightEnabledSwitch(coordinator, entry),
        MotionLightRespectManualSwitch(coordinator, entry),
    ])


class MotionLightEnabledSwitch(CoordinatorEntity, SwitchEntity, RestoreEntity):
    """Representation of a Motion Light enabled switch."""
    _attr_translation_key = "motion_light_enabled"
    _attr_has_entity_name = True

    def __init__(self, coordinator, entry):
        """Initialize the switch."""
        super().__init__(coordinator)
        self.entry = entry
        
        self.logger = PrefixLoggerAdapter(_LOGGER, {"name": entry.title})
        
        self._attr_unique_id = f"{entry.entry_id}_enabled"
        self._attr_icon = "mdi:lightbulb-auto"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Motion Light",
            model="Switch Control Integration",
        )

    @property
    def is_on(self) -> bool:
        """Return True if integration is enabled."""
        return self.coordinator.is_enabled

    async def async_turn_on(self, **kwargs) -> None:
        """Turn on integration."""
        self.logger.info("Switch turned ON, enabling integration")
        await self.coordinator.set_enabled(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Turn off integration."""
        self.logger.info("Switch turned OFF, disabling integration")
        await self.coordinator.set_enabled(False)
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Handle entity which will be added."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None:
            is_enabled = last_state.state == STATE_ON
            self.logger.info("Restored enabled switch state: %s", last_state.state)
            if self.coordinator.is_enabled != is_enabled:
                await self.coordinator.set_enabled(is_enabled)
            self.async_write_ha_state()
        else:
            self.logger.info("Enabled switch added for the first time, defaulting to enabled")

    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()


class MotionLightRespectManualSwitch(CoordinatorEntity, SwitchEntity, RestoreEntity):
    """Representation of a Motion Light respect_manual switch."""
    _attr_translation_key = "motion_light_priority_manual"
    _attr_has_entity_name = True

    def __init__(self, coordinator, entry):
        """Initialize the switch."""
        super().__init__(coordinator)
        self.entry = entry
        
        self.logger = PrefixLoggerAdapter(_LOGGER, {"name": entry.title})
        
        self._attr_unique_id = f"{entry.entry_id}_{ENTITY_RESPECT_MANUAL}"
        self._attr_icon = "mdi:hand-back-left"
        self._is_on = DEFAULT_RESPECT_MANUAL
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Motion Light",
            model="Switch Control Integration",
        )

    @property
    def is_on(self) -> bool:
        """Return True if respect_manual is enabled."""
        return self._is_on

    async def async_turn_on(self, **kwargs) -> None:
        """Turn on respect_manual."""
        self.logger.info("Respect manual turned ON")
        self._is_on = True
        self.coordinator.set_respect_manual(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Turn off respect_manual."""
        self.logger.info("Respect manual turned OFF")
        self._is_on = False
        self.coordinator.set_respect_manual(False)
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Handle entity which will be added."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None:
            self._is_on = last_state.state == STATE_ON
            self.logger.info("Restored respect_manual state: %s", last_state.state)
            self.coordinator.set_respect_manual(self._is_on)
            self.async_write_ha_state()
        else:
            self.logger.info("Respect manual switch added for the first time, defaulting to %s", self._is_on)

    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()