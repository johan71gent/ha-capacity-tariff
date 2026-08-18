"""Data model for the capacity-tariff calculation core.

Everything in ``core`` is plain Python: no Home Assistant imports, no wall clock.
All timestamps are timezone-aware ``datetime`` objects and are normalised to UTC.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

QUARTER_S = 900
"""Length of a Fluvius quarter-hour in seconds."""

QUARTER_H = QUARTER_S / 3600
"""Length of a quarter-hour in hours (0.25)."""

DEFAULT_FLOOR_KW = 2.5
"""Minimum monthly peak the grid operator bills (kW)."""


class Source(StrEnum):
    """Where a value came from, in decreasing order of trust."""

    MANUAL = "manual"
    """Set by the user through a service call (correction)."""

    METER = "meter"
    """Reported by the digital meter itself (OBIS 1.4.0 / 1.6.0 / 98.1.0)."""

    ENERGY = "energy"
    """Derived from cumulative import registers: (kWh_end - kWh_start) x 4."""

    POWER = "power"
    """Derived by time-weighted (zero-order-hold) integration of a power sensor."""

    NONE = "none"
    """No data at all."""


def as_utc(ts: datetime) -> datetime:
    """Return ``ts`` in UTC; reject naive datetimes."""
    if ts.tzinfo is None or ts.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware")
    return ts.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class QuarterResult:
    """A closed (finished) quarter-hour."""

    start: datetime
    """UTC start of the quarter (inclusive)."""

    end: datetime
    """UTC end of the quarter (exclusive)."""

    average_w: float
    """Estimated average import power over the quarter (W)."""

    source: Source
    """Which estimator produced ``average_w``."""

    coverage: float
    """Fraction (0..1) of the quarter for which measured data was available."""

    max_gap_s: float
    """Largest interval without any sample during the quarter (seconds)."""

    flags: tuple[str, ...] = ()
    """Quality annotations, e.g. ``restored``, ``energy_tail_estimated``, ``counter_decrease``."""

    @property
    def average_kw(self) -> float:
        return self.average_w / 1000.0

    @property
    def energy_wh(self) -> float:
        """Estimated energy for the full quarter (Wh)."""
        return self.average_w * QUARTER_H


@dataclass(frozen=True, slots=True)
class QuarterStatus:
    """Live view on the running quarter at a given instant ``now``."""

    start: datetime
    end: datetime
    now: datetime
    source: Source
    elapsed_s: float
    remaining_s: float
    coverage: float
    """Fraction of the *elapsed* time that is backed by measurements (0..1)."""

    energy_wh_measured: float
    """Energy actually measured so far (covered window only, no extrapolation)."""

    energy_wh_estimated: float
    """Energy since quarter start, covered energy scaled over the elapsed time."""

    running_average_w: float
    """Average power so far (over the covered window)."""

    hold_power_w: float
    """Power assumed for the rest of the quarter (last known instantaneous power)."""

    @property
    def predicted_end_w(self) -> float:
        """Expected quarter average if ``hold_power_w`` continues until the end."""
        return (self.energy_wh_estimated + self.hold_power_w * self.remaining_s / 3600) / QUARTER_H

    def margin_w(self, target_w: float) -> float:
        """Constant power you may still draw for the rest of the quarter without the
        quarter average exceeding ``target_w``. Negative means the target is already
        unreachable. With (almost) no time left the value grows large — that is real."""
        remaining_h = max(self.remaining_s, 1.0) / 3600
        return (target_w * QUARTER_H - self.energy_wh_estimated) / remaining_h

    def is_certain_break(self, target_w: float) -> bool:
        """True when the energy *already measured* exceeds the quarter budget, so the
        average ends above ``target_w`` even at 0 W for the rest of the quarter."""
        return self.energy_wh_measured > target_w * QUARTER_H

    def is_at_risk(self, target_w: float, threshold: float) -> bool:
        """True when the prediction exceeds ``threshold`` (fraction, e.g. 0.9) of the target."""
        return self.predicted_end_w > threshold * target_w


@dataclass(frozen=True, slots=True)
class Gap:
    """A period without data (typically Home Assistant downtime)."""

    start: datetime
    end: datetime
    average_w: float | None
    """Average import power over the gap when the import register allowed computing it.
    This is a *lower bound* for the highest quarter inside the gap."""

    @property
    def seconds(self) -> float:
        return (self.end - self.start).total_seconds()


@dataclass(frozen=True, slots=True)
class PeakEntry:
    """One quarter-hour peak candidate."""

    kw: float
    at: datetime | None
    """UTC end of the quarter the peak was measured in (meter convention); ``None`` if unknown."""

    source: Source = Source.POWER


@dataclass(frozen=True, slots=True)
class MonthPeak:
    """The peak of one calendar month as it will be billed."""

    month: str
    """``YYYY-MM`` in the local timezone."""

    peak_kw: float
    """Billed peak: raw peak floored at the minimum (default 2.5 kW)."""

    raw_kw: float | None
    """Highest measured quarter, or ``None`` when nothing was measured."""

    at: datetime | None
    source: Source
    top: tuple[PeakEntry, ...] = field(default_factory=tuple)
    """Highest quarters measured by this integration, best first."""
