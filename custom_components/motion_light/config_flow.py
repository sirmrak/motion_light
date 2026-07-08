"""Config flow for Motion Light."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector
import voluptuous as vol

from .const import (
    DOMAIN,
    CONF_SWITCH_ENTITIES,
    CONF_MAIN_SENSORS,
    CONF_EXTEND_SENSORS,
    CONF_LUX_SENSOR,
    CONF_FORCE_STOP_SENSOR,
    CONF_FORCE_STOP_STATE,
    CONF_LOG_LEVEL,
    DEFAULT_NAME,
    DEFAULT_FORCE_STOP_STATE,
    DEFAULT_LOG_LEVEL,
)

_LOGGER = logging.getLogger(__name__)


class MotionLightConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Motion Light."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        
        if user_input is not None:
            try:
                await self.async_set_unique_id(user_input[CONF_MAIN_SENSORS][0])
                self._abort_if_unique_id_configured()
                
                return self.async_create_entry(
                    title=user_input.get("name", DEFAULT_NAME),
                    data=user_input,
                )
            except Exception as err:
                _LOGGER.error("Error creating entry: %s", err)
                errors["base"] = "unknown"

        data_schema = vol.Schema({
            vol.Required("name", default=DEFAULT_NAME): str,
            
            # Главный триггер (Телевизор, медиаплеер и т.д.)
            vol.Required(CONF_MAIN_SENSORS): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain=["binary_sensor", "switch", "input_boolean", "media_player", "remote"], 
                    multiple=True
                )
            ),
            
            # Датчики только для продления (Движение)
            vol.Optional(CONF_EXTEND_SENSORS): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="binary_sensor", multiple=True)
            ),
            
            vol.Required(CONF_SWITCH_ENTITIES): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["switch", "light"], multiple=True)
            ),
            vol.Optional(CONF_LUX_SENSOR): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="sensor",
                    device_class="illuminance",
                )
            ),
            vol.Optional(CONF_FORCE_STOP_SENSOR): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain=["binary_sensor", "switch", "input_boolean"],
                    multiple=False,
                )
            ),
            vol.Required(CONF_FORCE_STOP_STATE, default=DEFAULT_FORCE_STOP_STATE): str,
            vol.Required(CONF_LOG_LEVEL, default=DEFAULT_LOG_LEVEL): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        "DEBUG",
                        "INFO",
                        "WARNING",
                        "ERROR",
                    ],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
        })

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> MotionLightOptionsFlow:
        """Get the options flow for this handler."""
        return MotionLightOptionsFlow()


class MotionLightOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for Motion Light."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        # HA сам подставляет self.config_entry
        current_data = {**self.config_entry.data, **self.config_entry.options}

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(
                    CONF_MAIN_SENSORS,
                    default=current_data.get(CONF_MAIN_SENSORS, []),
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["binary_sensor", "switch", "input_boolean", "media_player", "remote"], 
                        multiple=True
                    )
                ),
                vol.Optional(
                    CONF_EXTEND_SENSORS,
                    description={"suggested_value": current_data.get(CONF_EXTEND_SENSORS)},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="binary_sensor", multiple=True)
                ),
                vol.Required(
                    CONF_SWITCH_ENTITIES,
                    default=current_data.get(CONF_SWITCH_ENTITIES, []),
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["switch", "light"], multiple=True)
                ),
                vol.Optional(
                    CONF_LUX_SENSOR,
                    description={"suggested_value": current_data.get(CONF_LUX_SENSOR)},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="sensor",
                        device_class="illuminance",
                    )
                ),
                vol.Optional(
                    CONF_FORCE_STOP_SENSOR,
                    description={"suggested_value": current_data.get(CONF_FORCE_STOP_SENSOR)},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["binary_sensor", "switch", "input_boolean"],
                        multiple=False,
                    )
                ),
                vol.Required(
                    CONF_FORCE_STOP_STATE,
                    default=current_data.get(CONF_FORCE_STOP_STATE, DEFAULT_FORCE_STOP_STATE),
                ): str,
                vol.Required(
                    CONF_LOG_LEVEL,
                    default=current_data.get(CONF_LOG_LEVEL, DEFAULT_LOG_LEVEL),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=["DEBUG", "INFO", "WARNING", "ERROR"],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
            }),
        )