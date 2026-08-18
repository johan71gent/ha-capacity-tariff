"""Config and options flow for Capaciteitstarief (BE)."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)

from .const import (
    CONF_ENERGY_ENTITIES,
    CONF_FLOOR_KW,
    CONF_GOAL_KW,
    CONF_METER_AVERAGE_ENTITY,
    CONF_METER_PEAK_ENTITY,
    CONF_POWER_ENTITY,
    CONF_TARIFF,
    CONF_WARNING_THRESHOLD,
    DEFAULT_FLOOR_KW,
    DEFAULT_WARNING_THRESHOLD,
    DOMAIN,
)

SOURCE_KEYS = (
    CONF_POWER_ENTITY,
    CONF_METER_AVERAGE_ENTITY,
    CONF_METER_PEAK_ENTITY,
    CONF_ENERGY_ENTITIES,
)
SETTING_KEYS = (CONF_TARIFF, CONF_WARNING_THRESHOLD, CONF_FLOOR_KW, CONF_GOAL_KW)


def _sources_schema() -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_POWER_ENTITY): EntitySelector(
                EntitySelectorConfig(domain="sensor", device_class=SensorDeviceClass.POWER)
            ),
            vol.Optional(CONF_METER_AVERAGE_ENTITY): EntitySelector(
                EntitySelectorConfig(domain="sensor")
            ),
            vol.Optional(CONF_METER_PEAK_ENTITY): EntitySelector(
                EntitySelectorConfig(domain="sensor")
            ),
            vol.Optional(CONF_ENERGY_ENTITIES): EntitySelector(
                EntitySelectorConfig(
                    domain="sensor", device_class=SensorDeviceClass.ENERGY, multiple=True
                )
            ),
        }
    )


def _settings_schema() -> vol.Schema:
    return vol.Schema(
        {
            vol.Optional(CONF_TARIFF): NumberSelector(
                NumberSelectorConfig(
                    min=0,
                    max=500,
                    step=0.01,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="€/kW/jaar",
                )
            ),
            vol.Required(CONF_WARNING_THRESHOLD, default=DEFAULT_WARNING_THRESHOLD): NumberSelector(
                NumberSelectorConfig(
                    min=50,
                    max=100,
                    step=1,
                    mode=NumberSelectorMode.SLIDER,
                    unit_of_measurement="%",
                )
            ),
            vol.Required(CONF_FLOOR_KW, default=DEFAULT_FLOOR_KW): NumberSelector(
                NumberSelectorConfig(
                    min=0,
                    max=10,
                    step=0.1,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="kW",
                )
            ),
            vol.Optional(CONF_GOAL_KW): NumberSelector(
                NumberSelectorConfig(
                    min=0,
                    max=50,
                    step=0.1,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="kW",
                )
            ),
        }
    )


def _clean(values: dict[str, Any]) -> dict[str, Any]:
    """Drop empty optional values so ``.get()`` semantics stay simple downstream."""
    return {k: v for k, v in values.items() if v not in (None, "", [])}


class CapacityTariffConfigFlow(ConfigFlow, domain=DOMAIN):
    """Two steps: sources, then settings."""

    VERSION = 1

    def __init__(self) -> None:
        self._sources: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._sources = _clean(user_input)
            await self.async_set_unique_id(self._sources[CONF_POWER_ENTITY])
            self._abort_if_unique_id_configured()
            return await self.async_step_settings()
        return self.async_show_form(step_id="user", data_schema=_sources_schema())

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                title="Capaciteitstarief", data=self._sources, options=_clean(user_input)
            )
        return self.async_show_form(step_id="settings", data_schema=_settings_schema())

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return CapacityTariffOptionsFlow()


class CapacityTariffOptionsFlow(OptionsFlow):
    """One form with sources and settings; sources go to entry.data, settings to options."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            values = _clean(user_input)
            sources = {k: values[k] for k in SOURCE_KEYS if k in values}
            settings = {k: values[k] for k in SETTING_KEYS if k in values}
            self.hass.config_entries.async_update_entry(self.config_entry, data=sources)
            return self.async_create_entry(data=settings)

        schema = _sources_schema().extend(_settings_schema().schema)
        current = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(schema, current),
        )
