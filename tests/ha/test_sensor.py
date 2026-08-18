"""Integration setup, sensors, quarter ticks and persistence through Home Assistant."""

from datetime import timedelta

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.capacity_tariff.const import (
    CONF_ENERGY_ENTITIES,
    CONF_METER_AVERAGE_ENTITY,
    CONF_METER_PEAK_ENTITY,
    CONF_POWER_ENTITY,
    DOMAIN,
)

from .conftest import (
    ENERGY_1,
    ENERGY_2,
    METER_AVG,
    METER_PEAK,
    POWER,
    set_energy,
    set_meter_avg,
    set_meter_peak,
    set_power,
)

T0 = "2026-08-18T12:00:00+00:00"  # 14:00 Brussels, start of a quarter

E = {
    "running": "sensor.capaciteitstarief_running_quarter_average",
    "prediction": "sensor.capaciteitstarief_quarter_prediction",
    "margin": "sensor.capaciteitstarief_quarter_margin",
    "last": "sensor.capaciteitstarief_last_quarter",
    "peak": "sensor.capaciteitstarief_month_peak",
    "peak_time": "sensor.capaciteitstarief_month_peak_time",
    "target": "sensor.capaciteitstarief_target_peak",
    "avg12": "sensor.capaciteitstarief_average_peak_12_months",
    "cost_month": "sensor.capaciteitstarief_capacity_cost_this_month",
    "cost_year": "sensor.capaciteitstarief_capacity_cost_per_year",
}


async def _setup(hass: HomeAssistant, entry) -> None:
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def _advance(hass: HomeAssistant, freezer, seconds: float) -> None:
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()


def _f(hass: HomeAssistant, key: str) -> float:
    return float(hass.states.get(E[key]).state)


async def test_entities_created_with_power_only(hass: HomeAssistant, freezer, mock_entry):
    freezer.move_to(T0)
    set_power(hass, 1000)
    await _setup(hass, mock_entry)

    for entity_id in E.values():
        assert hass.states.get(entity_id) is not None, entity_id
    assert _f(hass, "peak") == 2.5  # floor, nothing measured yet
    assert _f(hass, "target") == 2.5
    assert _f(hass, "avg12") == 2.5
    assert _f(hass, "cost_month") == pytest.approx(2.5 * 48 / 12)
    assert _f(hass, "cost_year") == pytest.approx(2.5 * 48)
    assert hass.states.get(E["last"]).state == "unknown"
    assert hass.states.get(E["peak_time"]).state == "unknown"


async def test_running_quarter_prediction_and_margin(hass: HomeAssistant, freezer, mock_entry):
    freezer.move_to(T0)
    set_power(hass, 3000)
    await _setup(hass, mock_entry)

    await _advance(hass, freezer, 300)  # 12:05, still 3 kW (state re-affirmed by refresh)
    set_power(hass, 3000.1)  # a new sample stamps the tracker at 12:05
    await hass.async_block_till_done()

    assert _f(hass, "running") == pytest.approx(3000, rel=1e-3)
    assert _f(hass, "prediction") == pytest.approx(3000, rel=1e-3)
    # target 2.5 kW: (625 - 250) Wh over 10 min -> 2250 W
    assert _f(hass, "margin") == pytest.approx(2250, rel=1e-2)
    attrs = hass.states.get(E["margin"]).attributes
    assert attrs["at_risk"] is True  # 3000 > 0.9 x 2500
    assert attrs["certain_break"] is False
    assert hass.states.get(E["running"]).attributes["source"] == "power"


async def test_quarter_tick_closes_quarter_and_records_peak(
    hass: HomeAssistant, freezer, mock_entry
):
    freezer.move_to(T0)
    set_power(hass, 4000)
    await _setup(hass, mock_entry)

    # 4 kW for the whole quarter, samples every 30 s via the refresh re-affirmation
    for _ in range(30):
        await _advance(hass, freezer, 30)
    # now 12:15:00 -> the boundary tick fired
    last = hass.states.get(E["last"])
    assert float(last.state) == pytest.approx(4000, rel=1e-3)
    assert last.attributes["coverage"] == pytest.approx(1.0)
    assert _f(hass, "peak") == pytest.approx(4.0, rel=1e-3)
    assert _f(hass, "target") == pytest.approx(4.0, rel=1e-3)
    assert hass.states.get(E["peak"]).attributes["source"] == "power"
    assert hass.states.get(E["peak_time"]).state == "2026-08-18T12:15:00+00:00"
    assert _f(hass, "cost_month") == pytest.approx(4.0 * 48 / 12, rel=1e-3)
    assert _f(hass, "avg12") == pytest.approx((11 * 2.5 + 4.0) / 12, rel=1e-3)


async def test_units_are_normalised(hass: HomeAssistant, freezer, mock_entry):
    freezer.move_to(T0)
    set_power(hass, 2.5, unit="kW")
    await _setup(hass, mock_entry)
    await _advance(hass, freezer, 60)
    set_power(hass, 2.5001, unit="kW")
    await hass.async_block_till_done()
    assert _f(hass, "running") == pytest.approx(2500, rel=1e-3)


@pytest.mark.parametrize(
    "entry_data",
    [
        {
            CONF_POWER_ENTITY: POWER,
            CONF_METER_AVERAGE_ENTITY: METER_AVG,
            CONF_METER_PEAK_ENTITY: METER_PEAK,
            CONF_ENERGY_ENTITIES: [ENERGY_1, ENERGY_2],
        }
    ],
)
async def test_meter_values_take_precedence(hass: HomeAssistant, freezer, mock_entry):
    freezer.move_to(T0)
    set_power(hass, 3900)  # badly calibrated power sensor
    set_meter_avg(hass, 3.21)  # the meter says 3.21 kW
    set_meter_peak(hass, 5.4)  # and the month peak so far is 5.4 kW
    set_energy(hass, 1000.0, 2000.0)
    await _setup(hass, mock_entry)

    assert hass.states.get(E["running"]).attributes["source"] == "meter"
    assert _f(hass, "peak") == pytest.approx(5.4)
    assert hass.states.get(E["peak"]).attributes["source"] == "meter"
    assert _f(hass, "target") == pytest.approx(5.4)

    # meter average keeps coming in every second; the register also grows (2 kW-ish)
    for i in range(1, 900):
        await _advance(hass, freezer, 1)
        if i % 10 == 0:
            set_meter_avg(hass, 3.21 + i * 1e-6)  # tiny changes so the state actually updates
            set_energy(hass, 1000.0 + 2.0 * i / 3600, 2000.0)
    await _advance(hass, freezer, 1)  # 12:15:00 -> boundary tick
    last = hass.states.get(E["last"])
    assert last.attributes["source"] == "meter"
    assert float(last.state) == pytest.approx(3210, rel=1e-3)
    # our own quarter (3.21 kW) is below the meter's month peak -> peak of record unchanged
    assert _f(hass, "peak") == pytest.approx(5.4)


@pytest.mark.parametrize(
    "entry_data",
    [{CONF_POWER_ENTITY: POWER, CONF_METER_PEAK_ENTITY: METER_PEAK}],
)
async def test_meter_peak_from_previous_month_is_ignored(hass: HomeAssistant, freezer, mock_entry):
    """Right after a month rollover the 1.6.0 sensor may still show last month's value."""
    freezer.move_to("2026-08-31T21:00:00+00:00")  # 23:00 Brussels, still August
    set_power(hass, 1000)
    set_meter_peak(hass, 6.0)  # August's peak, last_changed in August
    freezer.move_to("2026-08-31T22:05:00+00:00")  # 00:05 Brussels on 1 September
    await _setup(hass, mock_entry)
    assert _f(hass, "peak") == 2.5  # not 6.0
    assert hass.states.get(E["peak"]).attributes["month"] == "2026-09"
    # once the meter reports a value *in* September it is accepted
    set_meter_peak(hass, 3.1)
    await hass.async_block_till_done()
    assert _f(hass, "peak") == pytest.approx(3.1)


async def test_state_survives_reload(hass: HomeAssistant, freezer, mock_entry, hass_storage):
    freezer.move_to(T0)
    set_power(hass, 4000)
    await _setup(hass, mock_entry)
    for _ in range(30):
        await _advance(hass, freezer, 30)
    assert _f(hass, "peak") == pytest.approx(4.0, rel=1e-3)

    # 12:20 -> restart HA (unload + setup) in the middle of a quarter
    await _advance(hass, freezer, 300)
    assert await hass.config_entries.async_unload(mock_entry.entry_id)
    await hass.async_block_till_done()
    assert f"{DOMAIN}.{mock_entry.entry_id}" in hass_storage

    await _advance(hass, freezer, 60)
    await _setup(hass, mock_entry)
    assert _f(hass, "peak") == pytest.approx(4.0, rel=1e-3)  # month peak restored
    running = hass.states.get(E["running"])
    assert (
        running.attributes["quarter_start"] == "2026-08-18T12:15:00+00:00"
    )  # same quarter resumed


async def test_unavailable_source_is_ignored(hass: HomeAssistant, freezer, mock_entry):
    freezer.move_to(T0)
    set_power(hass, 1000)
    await _setup(hass, mock_entry)
    hass.states.async_set(POWER, "unavailable")
    await hass.async_block_till_done()
    await _advance(hass, freezer, 60)
    assert hass.states.get(E["running"]).state not in ("unknown", "unavailable")
