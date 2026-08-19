"""Binary sensors, goal-peak number, services and diagnostics."""

import json
from datetime import timedelta

import pytest
import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.capacity_tariff.const import DOMAIN
from custom_components.capacity_tariff.diagnostics import async_get_config_entry_diagnostics

from .conftest import set_power

T0 = "2026-08-18T12:00:00+00:00"
AT_RISK = "binary_sensor.capaciteitstarief_peak_demand_at_risk"
EXCEEDED = "binary_sensor.capaciteitstarief_peak_demand_will_be_exceeded"
GOAL = "number.capaciteitstarief_desired_peak_limit"
TARGET = "sensor.capaciteitstarief_peak_limit_target"
MARGIN = "sensor.capaciteitstarief_power_still_available_this_quarter"
PEAK = "sensor.capaciteitstarief_peak_demand_current_month"
AVG12 = "sensor.capaciteitstarief_average_peak_demand_12_months"


async def _setup(hass, entry):
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def _advance(hass, freezer, seconds):
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()


async def test_binary_sensors_follow_prediction_and_certainty(
    hass: HomeAssistant, freezer, mock_entry
):
    freezer.move_to(T0)
    set_power(hass, 1000)
    await _setup(hass, mock_entry)
    assert hass.states.get(AT_RISK).state == "off"
    assert hass.states.get(EXCEEDED).state == "off"

    # a 6 kW load starts: prediction 6 kW > 90 % x 2.5 kW -> at risk, but not yet certain
    await _advance(hass, freezer, 60)
    set_power(hass, 6000)
    await hass.async_block_till_done()
    assert hass.states.get(AT_RISK).state == "on"
    assert hass.states.get(EXCEEDED).state == "off"
    attrs = hass.states.get(AT_RISK).attributes
    assert attrs["target_kw"] == 2.5
    assert attrs["predicted_w"] == pytest.approx(6000 * 14 / 15 + 1000 / 15, rel=1e-2)

    # after ~7 more minutes at 6 kW the quarter budget (625 Wh) is spent: certain break
    for _ in range(14):
        await _advance(hass, freezer, 30)
        set_power(hass, 6000 + _)  # keep samples flowing
        await hass.async_block_till_done()
    assert hass.states.get(EXCEEDED).state == "on"
    assert float(hass.states.get(MARGIN).state) < 0


async def test_goal_peak_number_raises_target_and_persists(
    hass: HomeAssistant, freezer, mock_entry, hass_storage
):
    freezer.move_to(T0)
    set_power(hass, 1000)
    await _setup(hass, mock_entry)
    assert float(hass.states.get(GOAL).state) == 0.0
    assert float(hass.states.get(TARGET).state) == 2.5

    await hass.services.async_call(
        "number", "set_value", {"entity_id": GOAL, "value": 4.0}, blocking=True
    )
    await hass.async_block_till_done()
    assert float(hass.states.get(GOAL).state) == 4.0
    assert float(hass.states.get(TARGET).state) == 4.0
    assert hass.states.get(AT_RISK).state == "off"  # 1 kW is far below a 4 kW target
    assert hass_storage[f"{DOMAIN}.{mock_entry.entry_id}"]["data"]["goal_kw"] == 4.0

    # survives a reload
    await hass.config_entries.async_reload(mock_entry.entry_id)
    await hass.async_block_till_done()
    assert float(hass.states.get(GOAL).state) == 4.0
    assert float(hass.states.get(TARGET).state) == 4.0

    # 0 clears the goal
    await hass.services.async_call(
        "number", "set_value", {"entity_id": GOAL, "value": 0}, blocking=True
    )
    await hass.async_block_till_done()
    assert float(hass.states.get(TARGET).state) == 2.5


async def test_services_set_reset_and_import(
    hass: HomeAssistant, freezer, mock_entry, hass_storage
):
    freezer.move_to(T0)
    set_power(hass, 1000)
    await _setup(hass, mock_entry)

    await hass.services.async_call(
        DOMAIN,
        "set_month_peak",
        {"peak_kw": 5.25, "timestamp": "2026-08-10T17:15:00+00:00"},
        blocking=True,
    )
    await hass.async_block_till_done()
    peak = hass.states.get(PEAK)
    assert float(peak.state) == 5.25
    assert peak.attributes["source"] == "manual"
    assert peak.attributes["peak_at"] == "2026-08-10T17:15:00+00:00"
    assert float(hass.states.get(TARGET).state) == 5.25

    await hass.services.async_call(
        DOMAIN,
        "import_history",
        {"peaks": {"2026-06": 3.0, "2026-07": 6.0}, "source": "meter"},
        blocking=True,
    )
    await hass.async_block_till_done()
    # 9 x 2.5 + 3.0 + 6.0 + 5.25
    assert float(hass.states.get(AVG12).state) == pytest.approx((9 * 2.5 + 3 + 6 + 5.25) / 12)
    stored = hass_storage[f"{DOMAIN}.{mock_entry.entry_id}"]["data"]["ledger"]["months"]
    assert stored["2026-07"]["meter"]["kw"] == 6.0

    await hass.services.async_call(DOMAIN, "reset_month", {"month": "2026-08"}, blocking=True)
    await hass.async_block_till_done()
    assert float(hass.states.get(PEAK).state) == 2.5
    assert hass.states.get(PEAK).attributes["source"] == "none"

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "reset_month", {"config_entry_id": "does-not-exist"}, blocking=True
        )
    with pytest.raises(vol.Invalid):  # schema: month must be YYYY-MM
        await hass.services.async_call(DOMAIN, "reset_month", {"month": "2026-13"}, blocking=True)


async def test_diagnostics(hass: HomeAssistant, freezer, mock_entry):
    freezer.move_to(T0)
    set_power(hass, 2000)
    await _setup(hass, mock_entry)
    for _ in range(31):
        await _advance(hass, freezer, 30)
    diag = await async_get_config_entry_diagnostics(hass, mock_entry)
    json.dumps(diag)  # must be serialisable for the download
    assert diag["entry"]["data"] == dict(mock_entry.data)
    assert diag["time_zone"] == "Europe/Brussels"
    assert diag["sources"]["sensor.p1_power"]["state"] == "2000"
    assert diag["current"]["month"] == "2026-08"
    assert diag["current"]["status"]["source"] == "power"
    assert len(diag["recent_quarters"]) == 1
    q = diag["recent_quarters"][0]
    assert q["average_w"] == pytest.approx(2000, rel=1e-3)
    assert q["estimates_w"] == {"power": pytest.approx(2000, rel=1e-3)}
    assert q["calc_minus_meter_w"] is None
    assert "tracker" in diag and "ledger" in diag
