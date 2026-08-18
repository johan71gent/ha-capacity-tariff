"""Quarter-hour tracking.

The :class:`QuarterTracker` follows the running clock-bound quarter (``:00 :15 :30 :45``)
and produces a :class:`QuarterResult` every time a quarter closes.

Three estimators can feed it; the best available one wins when reading:

1. **meter** — the meter's own running quarter average (OBIS ``1-0:1.4.0``). Exact.
2. **energy** — the cumulative import register (``1.8.1 + 1.8.2``): ``(kWh_now - kWh_start) x 4``.
3. **power** — zero-order-hold integration of an instantaneous power sensor.

The instantaneous power is always used to *extrapolate* the rest of the quarter.

Design rules
------------
* No wall clock: every method receives the timestamp explicitly.
* Quarter boundaries are computed in UTC. Belgium's offset is a whole number of hours,
  so UTC quarters coincide with local quarters — also around DST changes.
* Samples that arrive after a boundary close the previous quarter first (the HA layer
  also calls :meth:`QuarterTracker.tick` at every boundary so a quarter closes even when
  no sample arrives).
* Nothing is invented for periods without data: a restart across quarter boundaries
  produces a :class:`Gap`, not fake results.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from .model import (
    QUARTER_S,
    Gap,
    QuarterResult,
    QuarterStatus,
    Source,
    as_utc,
)

_QUARTER = timedelta(seconds=QUARTER_S)


def quarter_bounds(ts: datetime) -> tuple[datetime, datetime]:
    """Return the UTC ``(start, end)`` of the clock quarter containing ``ts``."""
    u = as_utc(ts)
    start = u.replace(minute=(u.minute // 15) * 15, second=0, microsecond=0)
    return start, start + _QUARTER


def _h(seconds: float) -> float:
    return seconds / 3600.0


def _isoformat(ts: datetime | None) -> str | None:
    return None if ts is None else as_utc(ts).isoformat()


def _fromiso(value: str | None) -> datetime | None:
    return None if value is None else as_utc(datetime.fromisoformat(value))


class QuarterTracker:
    """Track the running quarter-hour. See module docstring."""

    def __init__(
        self,
        *,
        meter_stale_s: float = 60.0,
        energy_tail_flag_s: float = 5.0,
        hold_tolerance_s: float = 120.0,
    ) -> None:
        self._meter_stale_s = meter_stale_s
        self._energy_tail_flag_s = energy_tail_flag_s
        self._hold_tolerance_s = hold_tolerance_s
        """How long a last known value may be held (zero-order hold) and still count as
        *covered*. Beyond it the quarter is treated as partially covered: honest, not inventive.
        The HA layer re-feeds the current entity states at every boundary tick, so with healthy
        entities the hold never exceeds one sample interval."""

        self._start: datetime | None = None
        self._end: datetime | None = None

        # power estimator (instantaneous import power, W)
        self._power_last_ts: datetime | None = None
        self._power_last_w: float | None = None
        self._power_first_ts: datetime | None = None
        self._power_int_wh = 0.0

        # energy estimator (cumulative import register, kWh)
        self._energy_anchor: tuple[datetime, float] | None = None
        self._energy_last: tuple[datetime, float] | None = None

        # meter estimator (running average reported by the meter, W)
        self._meter: tuple[datetime, float] | None = None
        self._meter_final: tuple[datetime, float] | None = None

        # sample bookkeeping
        self._last_sample_ts: datetime | None = None
        self._max_gap_s = 0.0
        self._flags: set[str] = set()

        # gap bookkeeping
        self._pending_gap_from: datetime | None = None
        self._gap_energy_ref: tuple[datetime, float] | None = None

        self.gap: Gap | None = None
        """Most recent period without data that spanned at least one whole quarter."""

    # ------------------------------------------------------------------ properties

    @property
    def start(self) -> datetime | None:
        return self._start

    @property
    def end(self) -> datetime | None:
        return self._end

    @property
    def active(self) -> bool:
        return self._start is not None

    @property
    def last_power_w(self) -> float | None:
        return self._power_last_w

    # ------------------------------------------------------------------ inputs

    def on_power(self, ts: datetime, watts: float) -> list[QuarterResult]:
        """Feed an instantaneous import power sample (W). Negative values (injection) count as 0."""
        ts = as_utc(ts)
        watts = max(0.0, float(watts))
        closed = self._roll(ts)
        if self._power_last_ts is not None and ts < self._power_last_ts:
            return closed  # out of order: ignore
        if self._power_first_ts is None:
            self._power_first_ts = ts
        else:
            assert self._power_last_ts is not None and self._power_last_w is not None
            self._power_int_wh += self._power_last_w * _h(
                (ts - self._power_last_ts).total_seconds()
            )
        self._power_last_ts = ts
        self._power_last_w = watts
        self._note_sample(ts)
        return closed

    def on_energy(self, ts: datetime, kwh_import: float) -> list[QuarterResult]:
        """Feed the cumulative import register (kWh, sum of 1.8.1 and 1.8.2)."""
        ts = as_utc(ts)
        kwh_import = float(kwh_import)

        if self._energy_last is not None and ts < self._energy_last[0]:
            return []  # out of order: ignore

        if self._energy_last is not None and kwh_import < self._energy_last[1]:
            # Counter went backwards (meter swapped, entity changed): restart the estimator.
            closed = self._roll(ts)
            self._flags.add("counter_decrease")
            self._energy_anchor = (ts, kwh_import)
            self._energy_last = (ts, kwh_import)
            self._gap_energy_ref = None
            self._note_sample(ts)
            return closed

        boundary_kwh: dict[datetime, float] = {}
        if (
            self._start is not None
            and self._end is not None
            and self._end <= ts < self._end + _QUARTER
            and self._energy_last is not None
            and self._energy_last[0] >= self._start
        ):
            # This sample straddles the boundary of the running quarter: interpolate the
            # register at that boundary. Only adjacent quarters inherit it as their anchor.
            prev_ts, prev_kwh = self._energy_last
            boundary_kwh[self._end] = _interpolate(prev_ts, prev_kwh, ts, kwh_import, self._end)

        closed = self._roll(ts, boundary_kwh=boundary_kwh)
        self._resolve_gap_energy(ts, kwh_import)

        if self._energy_anchor is None:
            self._energy_anchor = (ts, kwh_import)
        self._energy_last = (ts, kwh_import)
        self._note_sample(ts)
        return closed

    def on_meter_average(self, ts: datetime, watts: float) -> list[QuarterResult]:
        """Feed the meter's own running quarter average (OBIS 1-0:1.4.0, converted to W)."""
        ts = as_utc(ts)
        watts = max(0.0, float(watts))
        closed = self._roll(ts)
        if self._meter is not None and ts < self._meter[0]:
            return closed
        assert self._start is not None and self._end is not None
        if self._meter is not None and self._meter_final is None:
            prev_ts, prev_w = self._meter
            elapsed_prev = (prev_ts - self._start).total_seconds()
            near_end = (self._end - prev_ts).total_seconds() <= self._meter_stale_s
            # A sudden collapse of the running average in the last minute means the meter's
            # own clock already rolled into the next quarter: keep the pre-drop value as final.
            if near_end and elapsed_prev >= 120 and watts < 0.5 * prev_w:
                self._meter_final = (prev_ts, prev_w)
                self._flags.add("meter_rolled_early")
        self._meter = (ts, watts)
        self._note_sample(ts)
        return closed

    def tick(self, now: datetime) -> list[QuarterResult]:
        """Close the quarter if ``now`` is past its end. Call at every ``:00/:15/:30/:45``."""
        return self._roll(as_utc(now))

    # ------------------------------------------------------------------ reading

    def status(self, now: datetime) -> QuarterStatus | None:
        """Live view of the running quarter at ``now``. ``None`` before the first sample."""
        if self._start is None or self._end is None:
            return None
        now = min(max(as_utc(now), self._start), self._end)
        elapsed_s = (now - self._start).total_seconds()
        remaining_s = (self._end - now).total_seconds()

        source, base_wh, covered_from, base_ts = self._best_estimate()
        if source is Source.NONE:
            return QuarterStatus(
                start=self._start,
                end=self._end,
                now=now,
                source=source,
                elapsed_s=elapsed_s,
                remaining_s=remaining_s,
                coverage=0.0,
                energy_wh_measured=0.0,
                energy_wh_estimated=0.0,
                running_average_w=0.0,
                hold_power_w=self._power_last_w or 0.0,
            )

        covered_s = max(0.0, (now - covered_from).total_seconds())
        base_covered_s = max(0.0, (base_ts - covered_from).total_seconds())
        avg_so_far = base_wh / _h(base_covered_s) if base_covered_s > 0 else 0.0
        hold_w = self._power_last_w if self._power_last_w is not None else avg_so_far

        tail_s = max(0.0, (now - base_ts).total_seconds())
        energy_cov = base_wh + hold_w * _h(tail_s)
        running_avg = energy_cov / _h(covered_s) if covered_s > 0 else hold_w
        energy_est = running_avg * _h(elapsed_s)
        coverage = covered_s / elapsed_s if elapsed_s > 0 else 1.0

        return QuarterStatus(
            start=self._start,
            end=self._end,
            now=now,
            source=source,
            elapsed_s=elapsed_s,
            remaining_s=remaining_s,
            coverage=min(1.0, coverage),
            energy_wh_measured=base_wh,
            energy_wh_estimated=energy_est,
            running_average_w=running_avg,
            hold_power_w=hold_w,
        )

    # ------------------------------------------------------------------ persistence

    def to_dict(self) -> dict:
        """JSON-serialisable snapshot of the running quarter."""
        return {
            "start": _isoformat(self._start),
            "power": {
                "last_ts": _isoformat(self._power_last_ts),
                "last_w": self._power_last_w,
                "first_ts": _isoformat(self._power_first_ts),
                "int_wh": self._power_int_wh,
            },
            "energy": {
                "anchor": _pair_to_dict(self._energy_anchor),
                "last": _pair_to_dict(self._energy_last),
            },
            "meter": _pair_to_dict(self._meter),
            "meter_final": _pair_to_dict(self._meter_final),
            "last_sample_ts": _isoformat(self._last_sample_ts),
            "max_gap_s": self._max_gap_s,
            "flags": sorted(self._flags),
        }

    @classmethod
    def from_dict(cls, data: dict, now: datetime, **kwargs) -> QuarterTracker:
        """Restore a tracker. If ``now`` still lies in the saved quarter, the running quarter
        resumes (flag ``restored``); otherwise the saved quarter is dropped and the downtime is
        reported as :attr:`gap` once data arrives again. The last known power and register value
        are always kept so extrapolation and gap detection can continue."""
        now = as_utc(now)
        t = cls(**kwargs)
        start = _fromiso(data.get("start"))
        power = data.get("power") or {}
        energy = data.get("energy") or {}

        t._power_last_ts = _fromiso(power.get("last_ts"))
        t._power_last_w = power.get("last_w")
        t._energy_last = _pair_from_dict(energy.get("last"))
        last_sample = _fromiso(data.get("last_sample_ts"))

        if start is not None and start <= now < start + _QUARTER:
            t._start = start
            t._end = start + _QUARTER
            t._power_first_ts = _fromiso(power.get("first_ts"))
            t._power_int_wh = float(power.get("int_wh") or 0.0)
            t._energy_anchor = _pair_from_dict(energy.get("anchor"))
            t._meter = _pair_from_dict(data.get("meter"))
            t._meter_final = _pair_from_dict(data.get("meter_final"))
            t._last_sample_ts = last_sample
            t._max_gap_s = float(data.get("max_gap_s") or 0.0)
            t._flags = set(data.get("flags") or ())
            t._flags.add("restored")
        elif last_sample is not None:
            # Saved quarter is over; remember when data stopped so the next sample yields a Gap.
            t._pending_gap_from = last_sample
            t._gap_energy_ref = t._energy_last
        return t

    # ------------------------------------------------------------------ internals

    def _note_sample(self, ts: datetime) -> None:
        if self._last_sample_ts is not None:
            gap = (ts - self._last_sample_ts).total_seconds()
            if gap > self._max_gap_s:
                self._max_gap_s = gap
        self._last_sample_ts = ts

    def _begin(self, start: datetime, kwh_at_start: float | None) -> None:
        self._start = start
        self._end = start + _QUARTER
        self._flags = set()
        self._max_gap_s = 0.0
        self._meter = None
        self._meter_final = None
        # energy: anchor only when the register value at the boundary is known;
        # ``_energy_last`` is kept for gap detection and later interpolation.
        self._energy_anchor = None
        if kwh_at_start is not None:
            self._energy_anchor = (start, kwh_at_start)
            self._energy_last = (start, kwh_at_start)
        # power: continue holding the last known power from the boundary on, if it is recent
        self._power_int_wh = 0.0
        recent_power = (
            self._power_last_w is not None
            and self._power_last_ts is not None
            and (start - self._power_last_ts).total_seconds() <= self._hold_tolerance_s
        )
        if recent_power:
            self._power_first_ts = start
            self._power_last_ts = start
        else:
            self._power_first_ts = None
        has_hold = kwh_at_start is not None or recent_power
        self._last_sample_ts = start if has_hold else None

    def _roll(
        self, ts: datetime, boundary_kwh: dict[datetime, float] | None = None
    ) -> list[QuarterResult]:
        """Ensure the quarter containing ``ts`` is current; close the previous one if needed."""
        boundary_kwh = boundary_kwh or {}
        closed: list[QuarterResult] = []
        new_start, _ = quarter_bounds(ts)

        if self._start is None:
            if self._pending_gap_from is not None:
                self.gap = Gap(start=self._pending_gap_from, end=ts, average_w=None)
                self._pending_gap_from = None
            self._begin(new_start, None)
            return closed

        assert self._end is not None
        if ts < self._end:
            return closed

        result = self._finalize(boundary_kwh.get(self._end))
        if result is not None:
            closed.append(result)

        if new_start > self._end:
            # At least one whole quarter without data.
            self.gap = Gap(start=self._last_sample_ts or self._end, end=ts, average_w=None)
            self._gap_energy_ref = (
                self._energy_last
                if self._energy_last is not None and self._energy_last[0] <= self._end
                else None
            )
            self._begin(new_start, None)
            return closed

        kwh_at_start = boundary_kwh.get(self._end)
        if kwh_at_start is None and self._energy_anchor is not None:
            # No straddling sample yet: estimate the register at the boundary with the held power.
            kwh_at_start = self._estimated_kwh_at(self._end)
        self._begin(new_start, kwh_at_start)
        return closed

    def _resolve_gap_energy(self, ts: datetime, kwh: float) -> None:
        """Upgrade the last :class:`Gap` with an average power once the register is seen again."""
        if self._gap_energy_ref is None or self.gap is None:
            return
        ref_ts, ref_kwh = self._gap_energy_ref
        self._gap_energy_ref = None
        span_s = (ts - ref_ts).total_seconds()
        if span_s <= 0:
            return
        avg_w = (kwh - ref_kwh) * 1000.0 / _h(span_s)
        self.gap = Gap(start=ref_ts, end=ts, average_w=avg_w)

    def _estimated_kwh_at(self, ts: datetime) -> float | None:
        """Register value at ``ts`` extrapolated from the last sample with the held power
        (or, without a power sensor, with the quarter's running average so far)."""
        if self._energy_last is None:
            return None
        last_ts, last_kwh = self._energy_last
        hold_w = self._power_last_w
        if hold_w is None:
            hold_w = 0.0
            if self._energy_anchor is not None:
                a_ts, a_kwh = self._energy_anchor
                span_h = _h((last_ts - a_ts).total_seconds())
                if span_h > 0:
                    hold_w = (last_kwh - a_kwh) * 1000.0 / span_h
        return last_kwh + hold_w * _h((ts - last_ts).total_seconds()) / 1000.0

    def _best_estimate(self, *, use_meter: bool = True) -> tuple[Source, float, datetime, datetime]:
        """Return ``(source, measured_wh, covered_from, measured_until)`` for this quarter."""
        assert self._start is not None and self._end is not None
        if use_meter and self._meter is not None and self._meter[0] >= self._start:
            m_ts, m_w = self._meter_final or self._meter
            return Source.METER, m_w * _h((m_ts - self._start).total_seconds()), self._start, m_ts
        if self._energy_anchor is not None and self._energy_last is not None:
            a_ts, a_kwh = self._energy_anchor
            l_ts, l_kwh = self._energy_last
            return Source.ENERGY, (l_kwh - a_kwh) * 1000.0, a_ts, l_ts
        if self._power_first_ts is not None and self._power_last_ts is not None:
            return Source.POWER, self._power_int_wh, self._power_first_ts, self._power_last_ts
        return Source.NONE, 0.0, self._start, self._start

    def _finalize(self, boundary_kwh: float | None) -> QuarterResult | None:
        assert self._start is not None and self._end is not None
        start, end = self._start, self._end
        flags = set(self._flags)
        source, _base_wh, covered_from, _base_ts = self._best_estimate()

        if source is Source.METER:
            m_ts, m_w = self._meter_final or self._meter  # type: ignore[misc]
            if (end - m_ts).total_seconds() <= self._meter_stale_s:
                return QuarterResult(
                    start=start,
                    end=end,
                    average_w=m_w,
                    source=Source.METER,
                    coverage=1.0,
                    max_gap_s=self._max_gap_s,
                    flags=tuple(sorted(flags)),
                )
            flags.add("meter_stale")
            source, _base_wh, covered_from, _base_ts = self._best_estimate(use_meter=False)

        if source is Source.NONE:
            return None

        gap_to_end = (end - (self._last_sample_ts or covered_from)).total_seconds()
        max_gap = max(self._max_gap_s, gap_to_end)
        hold_ok = gap_to_end <= self._hold_tolerance_s
        if not hold_ok:
            flags.add("tail_missing")

        if source is Source.ENERGY:
            assert self._energy_anchor is not None and self._energy_last is not None
            _a_ts, a_kwh = self._energy_anchor
            l_ts, l_kwh = self._energy_last
            if boundary_kwh is not None:
                end_kwh, covered_to = boundary_kwh, end
            elif hold_ok:
                end_kwh = self._estimated_kwh_at(end)
                assert end_kwh is not None
                covered_to = end
                if (end - l_ts).total_seconds() > self._energy_tail_flag_s:
                    flags.add("energy_tail_estimated")
            else:
                end_kwh, covered_to = l_kwh, l_ts  # only what was really measured
            energy_wh = (end_kwh - a_kwh) * 1000.0
        else:  # POWER
            assert self._power_last_ts is not None and self._power_last_w is not None
            if hold_ok:
                covered_to = end
                energy_wh = self._power_int_wh + self._power_last_w * _h(
                    (end - self._power_last_ts).total_seconds()
                )
            else:
                covered_to = self._power_last_ts
                energy_wh = self._power_int_wh

        covered_s = (covered_to - covered_from).total_seconds()
        if covered_s <= 0:
            return None
        avg_w = energy_wh / _h(covered_s)
        return QuarterResult(
            start=start,
            end=end,
            average_w=avg_w,
            source=source,
            coverage=min(1.0, covered_s / QUARTER_S),
            max_gap_s=max_gap,
            flags=tuple(sorted(flags)),
        )


def _interpolate(t0: datetime, v0: float, t1: datetime, v1: float, at: datetime) -> float:
    span = (t1 - t0).total_seconds()
    if span <= 0:
        return v1
    frac = (at - t0).total_seconds() / span
    return v0 + (v1 - v0) * frac


def _pair_to_dict(pair: tuple[datetime, float] | None) -> dict | None:
    if pair is None:
        return None
    return {"ts": _isoformat(pair[0]), "value": pair[1]}


def _pair_from_dict(data: dict | None) -> tuple[datetime, float] | None:
    if not data or data.get("ts") is None:
        return None
    ts = _fromiso(data["ts"])
    assert ts is not None
    return ts, float(data["value"])


__all__ = ["QuarterTracker", "quarter_bounds"]
