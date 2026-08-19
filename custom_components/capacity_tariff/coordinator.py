"""Push-mode coordinator: feeds the calculation core from source entities and fans out."""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_change,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    CONF_ENERGY_ENTITIES,
    CONF_FLOOR_KW,
    CONF_GOAL_KW,
    CONF_METER_AVERAGE_ENTITY,
    CONF_METER_PEAK_ENTITY,
    CONF_NET_AREA,
    CONF_POWER_ENTITY,
    CONF_TARIFF,
    CONF_WARNING_THRESHOLD,
    DEFAULT_FLOOR_KW,
    DEFAULT_WARNING_THRESHOLD,
    DOMAIN,
    SAVE_DELAY_S,
    STATUS_REFRESH_INTERVAL,
    STORAGE_VERSION,
)
from .core import (
    Gap,
    MonthLedger,
    MonthPeak,
    QuarterResult,
    QuarterStatus,
    QuarterTracker,
    Source,
    effective_target_kw,
    month_cost,
    year_cost,
)
from .core.tariffs import lookup_tariff

_LOGGER = logging.getLogger(__name__)

_POWER_FACTORS = {"W": 1.0, "kW": 1000.0, "MW": 1_000_000.0}
_ENERGY_FACTORS = {"Wh": 0.001, "kWh": 1.0, "MWh": 1000.0}
REAFFIRM_AFTER = timedelta(seconds=60)
"""Sources quiet for longer than this are re-fed at their current value (see refresh)."""

RECENT_RESULTS = 96
"""Closed quarters kept in memory for diagnostics (24 h)."""


@dataclass(frozen=True, slots=True)
class CapacityData:
    """Everything the entities need, computed once per update."""

    updated_at: datetime
    status: QuarterStatus | None
    last_result: QuarterResult | None
    month_key: str
    month_peak: MonthPeak
    average_12m_kw: float
    target_kw: float
    goal_kw: float | None
    tariff: float | None
    month_cost: float | None
    year_cost: float | None
    threshold: float
    at_risk: bool
    certain_break: bool
    gap: Gap | None
    tariff_source: str = "none"
    tariff_year: int | None = None
    net_area: str | None = None

    @property
    def target_w(self) -> float:
        return self.target_kw * 1000.0

    @property
    def margin_w(self) -> float | None:
        return None if self.status is None else self.status.margin_w(self.target_w)

    @property
    def predicted_end_w(self) -> float | None:
        return None if self.status is None else self.status.predicted_end_w


class CapacityTariffCoordinator(DataUpdateCoordinator[CapacityData]):
    """Event-driven coordinator (no polling): source entity updates and quarter ticks push data."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}:{entry.entry_id}",
            update_interval=None,
        )
        self.entry = entry
        self.tz = dt_util.get_default_time_zone()
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        floor = float(entry.options.get(CONF_FLOOR_KW, DEFAULT_FLOOR_KW))
        self.tracker = QuarterTracker()
        self.ledger = MonthLedger(tz=self.tz, floor_kw=floor)
        self._last_result: QuarterResult | None = None
        self._goal_kw: float | None = None
        self.recent_results: deque[QuarterResult] = deque(maxlen=RECENT_RESULTS)
        self._unsubs: list[Callable[[], None]] = []

    # ------------------------------------------------------------------ config

    @property
    def power_entity(self) -> str:
        return self.entry.data[CONF_POWER_ENTITY]

    @property
    def meter_average_entity(self) -> str | None:
        return self.entry.data.get(CONF_METER_AVERAGE_ENTITY) or None

    @property
    def meter_peak_entity(self) -> str | None:
        return self.entry.data.get(CONF_METER_PEAK_ENTITY) or None

    @property
    def energy_entities(self) -> list[str]:
        return list(self.entry.data.get(CONF_ENERGY_ENTITIES) or [])

    @property
    def source_entities(self) -> list[str]:
        ids = [self.power_entity]
        if self.meter_average_entity:
            ids.append(self.meter_average_entity)
        if self.meter_peak_entity:
            ids.append(self.meter_peak_entity)
        ids.extend(self.energy_entities)
        return ids

    @property
    def tariff(self) -> float | None:
        """EUR/kW/year: manual value wins, else the built-in table for the chosen area."""
        return self.tariff_info()[0]

    def tariff_info(self) -> tuple[float | None, str, int | None, str | None]:
        """(tariff, source, year_used, area) — source is 'manual', 'table' or 'none'."""
        value = self.entry.options.get(CONF_TARIFF)
        if value not in (None, ""):
            return float(value), "manual", None, None
        area = self.entry.options.get(CONF_NET_AREA)
        found = lookup_tariff(area, dt_util.now().year)
        if found is None:
            return None, "none", None, area or None
        return found[0], "table", found[1], area

    @property
    def goal_kw(self) -> float | None:
        """Optional goal peak (kW) set through ``number.streefpiek``; ``None`` = no goal."""
        return self._goal_kw

    @property
    def threshold(self) -> float:
        return (
            float(self.entry.options.get(CONF_WARNING_THRESHOLD, DEFAULT_WARNING_THRESHOLD)) / 100
        )

    # ------------------------------------------------------------------ lifecycle

    async def async_setup(self) -> None:
        """Load persisted state, prime from current entity states and subscribe to events."""
        now = dt_util.utcnow()
        stored = await self._store.async_load()
        if stored:
            try:
                self.tracker = QuarterTracker.from_dict(stored.get("tracker") or {}, now)
                self.ledger = MonthLedger.from_dict(
                    stored.get("ledger") or {}, tz=self.tz, floor_kw=self.ledger.floor_kw
                )
                goal = stored.get(CONF_GOAL_KW)
                self._goal_kw = None if goal in (None, 0) else float(goal)
            except (KeyError, ValueError, TypeError) as err:  # corrupt storage: start fresh
                _LOGGER.warning("Ignoring corrupt storage for %s: %s", self.entry.title, err)

        for entity_id in self.source_entities:
            state = self.hass.states.get(entity_id)
            if state is not None:
                self._feed(entity_id, state, min(state.last_updated, now))

        self._unsubs.append(
            async_track_state_change_event(
                self.hass, self.source_entities, self._async_state_changed
            )
        )
        self._unsubs.append(
            async_track_time_change(self.hass, self._async_tick, minute=[0, 15, 30, 45], second=0)
        )
        self._unsubs.append(
            async_track_time_interval(
                self.hass, self._async_refresh_status, STATUS_REFRESH_INTERVAL
            )
        )
        self._recompute(now)

    async def async_shutdown(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        await self._store.async_save(self._to_store())
        await super().async_shutdown()

    # ------------------------------------------------------------------ event handlers

    @callback
    def _async_state_changed(self, event: Event[EventStateChangedData]) -> None:
        new_state = event.data["new_state"]
        if new_state is None:
            return
        now = event.time_fired
        self._feed(event.data["entity_id"], new_state, min(new_state.last_updated, now))
        self._recompute(now)
        self._store.async_delay_save(self._to_store, SAVE_DELAY_S)

    @callback
    def _async_tick(self, now: datetime) -> None:
        """Quarter boundary: close the quarter even when no sample arrives."""
        now = dt_util.as_utc(now)
        self._record(self.tracker.tick(now))
        self._recompute(now)
        self.hass.async_create_task(self._store.async_save(self._to_store()))

    @callback
    def _async_refresh_status(self, now: datetime) -> None:
        """Every 30 s: re-affirm quiet-but-available sources (a Home Assistant state stays valid
        until it changes, so a hold longer than one sample interval is legitimate as long as the
        entity is available), catch a missed boundary tick and refresh prediction/margin."""
        now = dt_util.as_utc(now)
        for entity_id in (self.power_entity, *self.energy_entities):
            state = self.hass.states.get(entity_id)
            if state is not None and now - state.last_updated > REAFFIRM_AFTER:
                self._feed(entity_id, state, now)
        self._record(self.tracker.tick(now))
        self._recompute(now)

    # ------------------------------------------------------------------ feeding the core

    def _feed(self, entity_id: str, state: State, ts: datetime) -> None:
        """Push one entity state into the core, stamped at ``ts``."""
        if state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE, ""):
            return
        try:
            value = float(state.state)
        except (TypeError, ValueError):
            return
        unit = state.attributes.get("unit_of_measurement")

        if entity_id == self.power_entity:
            factor = _POWER_FACTORS.get(unit, 1.0)
            self._record(self.tracker.on_power(ts, value * factor))
        elif entity_id == self.meter_average_entity:
            factor = _POWER_FACTORS.get(unit, 1000.0)  # DSMR reports kW
            self._record(self.tracker.on_meter_average(ts, value * factor))
        elif entity_id == self.meter_peak_entity:
            self._feed_meter_peak(state, value, unit, ts)
        elif entity_id in self.energy_entities:
            total = self._sum_energy_kwh()
            if total is not None:
                self._record(self.tracker.on_energy(ts, total))

    def _feed_meter_peak(self, state: State, value: float, unit: str | None, now: datetime) -> None:
        """OBIS 1.6.0 (kW). Only trust it for the month in which it last changed: right after a
        month rollover the sensor may still show last month's peak."""
        kw = value * _POWER_FACTORS.get(unit, 1000.0) / 1000.0
        current = self.ledger.month_key(now)
        if self.ledger.month_key(state.last_changed) != current:
            return
        self.ledger.set_meter_peak(current, kw, None)

    def _sum_energy_kwh(self) -> float | None:
        total = 0.0
        for entity_id in self.energy_entities:
            state = self.hass.states.get(entity_id)
            if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE, ""):
                return None
            try:
                value = float(state.state)
            except (TypeError, ValueError):
                return None
            total += value * _ENERGY_FACTORS.get(state.attributes.get("unit_of_measurement"), 1.0)
        return total

    def _record(self, results: list[QuarterResult]) -> None:
        for result in results:
            self._last_result = result
            self.recent_results.append(result)
            if self.ledger.record(result):
                _LOGGER.debug("New month peak %.3f kW at %s", result.average_kw, result.end)
        if results:
            self.ledger.prune(self.ledger.month_key(results[-1].start))
            self._store.async_delay_save(self._to_store, 1)

    # ------------------------------------------------------------------ user actions

    async def async_set_goal(self, goal_kw: float | None) -> None:
        """Set/clear the goal peak (``number.streefpiek``); persisted with the peaks."""
        self._goal_kw = None if goal_kw in (None, 0) else float(goal_kw)
        await self._commit()

    async def async_set_month_peak(
        self, month: str | None, peak_kw: float, at: datetime | None
    ) -> None:
        """Manual correction: overrides meter and calculated values for that month."""
        key = month or self.ledger.month_key(dt_util.utcnow())
        self.ledger.set_manual_peak(key, peak_kw, at)
        await self._commit()

    async def async_reset_month(self, month: str | None) -> None:
        """Forget everything about a month (default: the running month)."""
        key = month or self.ledger.month_key(dt_util.utcnow())
        self.ledger.reset_month(key)
        await self._commit()

    async def async_import_history(self, peaks: dict[str, float], source: str) -> None:
        """Seed past months, e.g. from an invoice (manual) or the meter's 13-month history."""
        for key, kw in peaks.items():
            if source == str(Source.METER):
                self.ledger.set_meter_peak(key, float(kw), None)
            else:
                self.ledger.set_manual_peak(key, float(kw), None)
        await self._commit()

    async def _commit(self) -> None:
        now = dt_util.utcnow()
        self.ledger.prune(self.ledger.month_key(now))
        self._recompute(now)
        await self._store.async_save(self._to_store())

    # ------------------------------------------------------------------ output

    def _recompute(self, now: datetime) -> None:
        month_key = self.ledger.month_key(now)
        peak = self.ledger.month_peak(month_key)
        target_kw = effective_target_kw(peak.peak_kw, self.goal_kw, self.ledger.floor_kw)
        status = self.tracker.status(now)
        tariff, tariff_source, tariff_year, net_area = self.tariff_info()
        avg12 = self.ledger.rolling_average(month_key)
        target_w = target_kw * 1000.0
        data = CapacityData(
            updated_at=now,
            status=status,
            last_result=self._last_result,
            month_key=month_key,
            month_peak=peak,
            average_12m_kw=avg12,
            target_kw=target_kw,
            goal_kw=self.goal_kw,
            tariff=tariff,
            tariff_source=tariff_source,
            tariff_year=tariff_year,
            net_area=net_area,
            month_cost=None if tariff is None else month_cost(peak.peak_kw, tariff),
            year_cost=None if tariff is None else year_cost(avg12, tariff),
            threshold=self.threshold,
            at_risk=bool(status and status.is_at_risk(target_w, self.threshold)),
            certain_break=bool(status and status.is_certain_break(target_w)),
            gap=self.tracker.gap,
        )
        self.async_set_updated_data(data)

    def _to_store(self) -> dict[str, Any]:
        return {
            "tracker": self.tracker.to_dict(),
            "ledger": self.ledger.to_dict(),
            CONF_GOAL_KW: self._goal_kw,
        }
