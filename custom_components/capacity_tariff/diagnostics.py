"""Diagnostics: everything needed to answer "my Fluvius invoice says something else"."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Any

from homeassistant.core import HomeAssistant

from . import CapacityTariffConfigEntry
from .core import QuarterResult


def _iso(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _iso(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_iso(v) for v in value]
    return value


def _result(r: QuarterResult) -> dict[str, Any]:
    est = r.estimates_w
    meter = est.get("meter")
    calc = est.get("energy", est.get("power"))
    return {
        "start": r.start.isoformat(),
        "end": r.end.isoformat(),
        "average_w": round(r.average_w, 1),
        "source": str(r.source),
        "coverage": round(r.coverage, 3),
        "max_gap_s": round(r.max_gap_s),
        "flags": list(r.flags),
        "estimates_w": est,
        # own calculation vs meter, when both are known: the number to quote in issues
        "calc_minus_meter_w": None if meter is None or calc is None else round(calc - meter, 1),
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: CapacityTariffConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    data = coordinator.data
    sources = {}
    for entity_id in coordinator.source_entities:
        state = hass.states.get(entity_id)
        sources[entity_id] = (
            None
            if state is None
            else {
                "state": state.state,
                "unit": state.attributes.get("unit_of_measurement"),
                "last_updated": state.last_updated.isoformat(),
                "last_changed": state.last_changed.isoformat(),
            }
        )
    return {
        "entry": {"data": dict(entry.data), "options": dict(entry.options)},
        "time_zone": str(coordinator.tz),
        "sources": sources,
        "current": {
            "month": data.month_key,
            "month_peak": _iso(asdict(data.month_peak)),
            "target_kw": data.target_kw,
            "goal_kw": data.goal_kw,
            "average_12m_kw": data.average_12m_kw,
            "tariff": data.tariff,
            "month_cost": data.month_cost,
            "year_cost": data.year_cost,
            "at_risk": data.at_risk,
            "certain_break": data.certain_break,
            "status": None if data.status is None else _iso(asdict(data.status)),
            "gap": None if data.gap is None else _iso(asdict(data.gap)),
        },
        "recent_quarters": [_result(r) for r in coordinator.recent_results],
        "tracker": coordinator.tracker.to_dict(),
        "ledger": coordinator.ledger.to_dict(),
    }
