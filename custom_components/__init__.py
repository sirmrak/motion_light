"""The Motion Light integration."""
import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from .const import DOMAIN, CONF_LOG_LEVEL, DEFAULT_LOG_LEVEL
from .coordinator import MotionLightCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor", "switch", "number"]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Motion Light from a config entry."""
    log_level = entry.options.get(
        CONF_LOG_LEVEL,
        entry.data.get(CONF_LOG_LEVEL, DEFAULT_LOG_LEVEL)
    )
    logging.getLogger(f"custom_components.{DOMAIN}").setLevel(
        getattr(logging, log_level, logging.INFO)
    )
    
    # Добавили entry.title в лог для идентификации
    _LOGGER.info("Motion Light '%s' loaded with log level: %s", entry.title, log_level)
    
    hass.data.setdefault(DOMAIN, {})
    coordinator = MotionLightCoordinator(hass, entry)
    await coordinator.async_setup()
    hass.data[DOMAIN][entry.entry_id] = coordinator
    
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    await coordinator.async_shutdown()
    
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok

async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    _LOGGER.info("Options updated, reloading Motion Light '%s'", entry.title)
    await hass.config_entries.async_reload(entry.entry_id)