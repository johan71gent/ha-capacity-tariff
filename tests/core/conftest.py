"""Shared helpers for core tests.

The core is HA-free, but it lives inside the integration package whose ``__init__`` imports
Home Assistant. When HA is not installed (fast local runs on Windows) we register a stub package
so ``custom_components.capacity_tariff.core`` imports without executing that ``__init__``.
"""

from __future__ import annotations

import pathlib
import sys
import types
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

try:
    import homeassistant  # noqa: F401
except ImportError:  # pragma: no cover - only on machines without HA
    _pkg = "custom_components.capacity_tariff"
    if _pkg not in sys.modules:
        _stub = types.ModuleType(_pkg)
        _stub.__path__ = [
            str(
                pathlib.Path(__file__).resolve().parents[2]
                / "custom_components"
                / "capacity_tariff"
            )
        ]
        sys.modules[_pkg] = _stub

BRUSSELS = ZoneInfo("Europe/Brussels")


def utc(
    h: int, m: int = 0, s: int = 0, *, day: int = 18, month: int = 8, year: int = 2026
) -> datetime:
    """A UTC datetime on 2026-08-18 by default."""
    return datetime(year, month, day, h, m, s, tzinfo=UTC)


def local(
    year: int, month: int, day: int, h: int, m: int = 0, s: int = 0, *, fold: int = 0
) -> datetime:
    """A Europe/Brussels local datetime (``fold=1`` selects the second occurrence in autumn)."""
    return datetime(year, month, day, h, m, s, tzinfo=BRUSSELS, fold=fold)


def feed_constant_power(tracker, start: datetime, end: datetime, watts: float, step_s: int = 10):
    """Feed ``watts`` every ``step_s`` seconds from ``start`` (inclusive) to ``end`` (exclusive)."""
    closed = []
    t = start
    while t < end:
        closed += tracker.on_power(t, watts)
        t += timedelta(seconds=step_s)
    return closed


def feed_constant_energy(
    tracker, start: datetime, end: datetime, kw: float, kwh0: float, step_s: int = 10
):
    """Feed a kWh register growing linearly at ``kw`` from ``start`` to ``end`` (exclusive)."""
    closed = []
    t = start
    while t < end:
        kwh = kwh0 + kw * (t - start).total_seconds() / 3600
        closed += tracker.on_energy(t, kwh)
        t += timedelta(seconds=step_s)
    return closed


@pytest.fixture
def q_start() -> datetime:
    """Start of a quarter: 12:00 UTC (14:00 Brussels summer time)."""
    return utc(12, 0)
