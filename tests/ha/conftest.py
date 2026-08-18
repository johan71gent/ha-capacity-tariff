"""Fixtures for the Home Assistant layer (skipped when HA is not installed, e.g. on Windows)."""

import pytest

pytest.importorskip("homeassistant")
pytest.importorskip("pytest_homeassistant_custom_component")

from pytest_homeassistant_custom_component.common import MockConfigEntry  # noqa: E402

from custom_components.capacity_tariff.const import (  # noqa: E402
    CONF_FLOOR_KW,
    CONF_POWER_ENTITY,
    CONF_TARIFF,
    CONF_WARNING_THRESHOLD,
    DOMAIN,
)

POWER = "sensor.p1_power"
METER_AVG = "sensor.p1_current_average_demand"
METER_PEAK = "sensor.p1_maximum_demand_current_month"
ENERGY_1 = "sensor.p1_energy_t1"
ENERGY_2 = "sensor.p1_energy_t2"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture(autouse=True)
async def brussels_time_zone(hass):
    """The HA test instance defaults to US/Pacific; the integration is about Belgium."""
    await hass.config.async_set_time_zone("Europe/Brussels")


@pytest.fixture
def entry_options():
    return {CONF_TARIFF: 48.0, CONF_WARNING_THRESHOLD: 90, CONF_FLOOR_KW: 2.5}


@pytest.fixture
def entry_data():
    return {CONF_POWER_ENTITY: POWER}


@pytest.fixture
def mock_entry(hass, entry_data, entry_options) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Capaciteitstarief",
        data=entry_data,
        options=entry_options,
        unique_id=POWER,
    )
    entry.add_to_hass(hass)
    return entry


def set_power(hass, watts, unit="W"):
    hass.states.async_set(POWER, str(watts), {"unit_of_measurement": unit, "device_class": "power"})


def set_energy(hass, t1_kwh, t2_kwh):
    hass.states.async_set(
        ENERGY_1, str(t1_kwh), {"unit_of_measurement": "kWh", "device_class": "energy"}
    )
    hass.states.async_set(
        ENERGY_2, str(t2_kwh), {"unit_of_measurement": "kWh", "device_class": "energy"}
    )


def set_meter_avg(hass, kw):
    hass.states.async_set(
        METER_AVG, str(kw), {"unit_of_measurement": "kW", "device_class": "power"}
    )


def set_meter_peak(hass, kw):
    hass.states.async_set(
        METER_PEAK, str(kw), {"unit_of_measurement": "kW", "device_class": "power"}
    )
