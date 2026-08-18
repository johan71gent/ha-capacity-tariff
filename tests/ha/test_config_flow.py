"""Config flow (sources -> settings) and options flow."""

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.capacity_tariff.const import (
    CONF_ENERGY_ENTITIES,
    CONF_FLOOR_KW,
    CONF_METER_AVERAGE_ENTITY,
    CONF_METER_PEAK_ENTITY,
    CONF_POWER_ENTITY,
    CONF_TARIFF,
    CONF_WARNING_THRESHOLD,
    DOMAIN,
)

from .conftest import ENERGY_1, ENERGY_2, METER_AVG, METER_PEAK, POWER, set_power


async def test_user_flow_creates_entry(hass: HomeAssistant) -> None:
    set_power(hass, 1000)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_POWER_ENTITY: POWER,
            CONF_METER_AVERAGE_ENTITY: METER_AVG,
            CONF_METER_PEAK_ENTITY: METER_PEAK,
            CONF_ENERGY_ENTITIES: [ENERGY_1, ENERGY_2],
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "settings"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_TARIFF: 48.5, CONF_WARNING_THRESHOLD: 85, CONF_FLOOR_KW: 2.5},
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Capaciteitstarief"
    assert result["data"] == {
        CONF_POWER_ENTITY: POWER,
        CONF_METER_AVERAGE_ENTITY: METER_AVG,
        CONF_METER_PEAK_ENTITY: METER_PEAK,
        CONF_ENERGY_ENTITIES: [ENERGY_1, ENERGY_2],
    }
    assert result["options"] == {CONF_TARIFF: 48.5, CONF_WARNING_THRESHOLD: 85, CONF_FLOOR_KW: 2.5}
    entry = result["result"]
    assert entry.unique_id == POWER
    assert entry.state.name == "LOADED"


async def test_user_flow_minimal_and_duplicate_abort(hass: HomeAssistant) -> None:
    set_power(hass, 1000)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_POWER_ENTITY: POWER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_WARNING_THRESHOLD: 90, CONF_FLOOR_KW: 2.5}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_POWER_ENTITY: POWER}
    assert CONF_TARIFF not in result["options"]

    # same power entity again -> abort
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_POWER_ENTITY: POWER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_options_flow_updates_sources_and_settings(hass: HomeAssistant, mock_entry) -> None:
    set_power(hass, 1000)
    assert await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(mock_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_POWER_ENTITY: POWER,
            CONF_METER_AVERAGE_ENTITY: METER_AVG,
            CONF_TARIFF: 52.0,
            CONF_WARNING_THRESHOLD: 80,
            CONF_FLOOR_KW: 2.5,
        },
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_entry.data == {CONF_POWER_ENTITY: POWER, CONF_METER_AVERAGE_ENTITY: METER_AVG}
    assert mock_entry.options == {CONF_TARIFF: 52.0, CONF_WARNING_THRESHOLD: 80, CONF_FLOOR_KW: 2.5}
    # reloaded with the new tariff
    state = hass.states.get("sensor.capaciteitstarief_capacity_cost_per_year")
    assert float(state.state) == 2.5 * 52.0
