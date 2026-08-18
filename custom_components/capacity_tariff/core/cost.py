"""Cost model and target logic for the capacity tariff.

The grid operator bills ``average of the last 12 monthly peaks (kW) x tariff (EUR/kW/year)``.
Each month therefore contributes ``peak_kw x tariff / 12``. The tariff differs per grid
area and year and is configured by the user; nothing here knows actual Fluvius prices.
"""

from __future__ import annotations

from .model import DEFAULT_FLOOR_KW


def month_cost(peak_kw: float, tariff_eur_per_kw_year: float) -> float:
    """Contribution of one month (with an already floored peak) to the yearly bill (EUR)."""
    return peak_kw * tariff_eur_per_kw_year / 12.0


def year_cost(average_peak_kw: float, tariff_eur_per_kw_year: float) -> float:
    """Yearly capacity cost for a 12-month average peak (EUR)."""
    return average_peak_kw * tariff_eur_per_kw_year


def effective_target_kw(
    month_peak_kw: float,
    goal_kw: float | None = None,
    floor_kw: float = DEFAULT_FLOOR_KW,
) -> float:
    """The peak we try not to exceed in the running quarter.

    * Never below the billing floor: staying under 2.5 kW does not save anything.
    * Never below the month's current peak: it cannot be lowered any more.
    * The user's optional goal raises the target ("I accept up to 4 kW this month").
    """
    return max(floor_kw, month_peak_kw, goal_kw or 0.0)


__all__ = ["month_cost", "year_cost", "effective_target_kw"]
