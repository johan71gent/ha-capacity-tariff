"""Constants for the Capaciteitstarief (BE) integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "capacity_tariff"
STORAGE_VERSION = 1

# --- config entry data (sources) ---------------------------------------------
CONF_POWER_ENTITY = "power_entity"
"""Instantaneous import power sensor (W or kW). Required."""

CONF_METER_AVERAGE_ENTITY = "meter_average_entity"
"""Meter's own running quarter average (OBIS 1-0:1.4.0, kW). Recommended."""

CONF_METER_PEAK_ENTITY = "meter_peak_entity"
"""Meter's own maximum demand of the running month (OBIS 1-0:1.6.0, kW). Recommended."""

CONF_ENERGY_ENTITIES = "energy_entities"
"""Cumulative import registers (kWh); several are summed (e.g. 1.8.1 + 1.8.2). Fallback."""

# --- config entry options (settings) ------------------------------------------
CONF_TARIFF = "tariff_eur_per_kw_year"
CONF_WARNING_THRESHOLD = "warning_threshold_pct"
CONF_FLOOR_KW = "floor_kw"
CONF_GOAL_KW = "goal_kw"

DEFAULT_WARNING_THRESHOLD = 90
DEFAULT_FLOOR_KW = 2.5

# --- runtime -------------------------------------------------------------------
STATUS_REFRESH_INTERVAL = timedelta(seconds=30)
"""Recompute prediction/margin even when no source update arrives."""

SAVE_DELAY_S = 30
"""Debounce for persisting the running quarter to storage."""

ATTR_SOURCE = "source"
ATTR_REMAINING_S = "remaining_seconds"
ATTR_ELAPSED_S = "elapsed_seconds"
ATTR_COVERAGE = "coverage"
ATTR_ENERGY_WH = "energy_wh"
ATTR_MONTH = "month"
ATTR_TOP = "top_quarters"
ATTR_FLAGS = "flags"
ATTR_GAP = "last_gap"
ATTR_TARIFF = "tariff_eur_per_kw_year"
ATTR_AVERAGE_12M = "average_peak_12m_kw"
