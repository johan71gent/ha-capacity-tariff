"""End-to-end scenarios through tracker + ledger: DST nights, month rollover, a full day."""

from datetime import timedelta

import pytest

from custom_components.capacity_tariff.core import (
    MonthLedger,
    QuarterTracker,
    effective_target_kw,
    month_key_for,
)

from .conftest import BRUSSELS, local, utc


def run(tracker, ledger, start, end, watts_fn, step_s=10):
    """Drive tracker+ledger with a power sensor and boundary ticks from ``start`` to ``end``."""
    results = []
    ts = start
    while ts <= end:
        # HA fires the boundary tick before the sample of that same second is processed
        if tracker.end is not None and ts >= tracker.end:
            for r in tracker.tick(tracker.end):
                results.append(r)
                ledger.record(r)
        for r in tracker.on_power(ts, watts_fn(ts)):
            results.append(r)
            ledger.record(r)
        ts += timedelta(seconds=step_s)
    return results


def test_autumn_dst_night_produces_one_result_per_utc_quarter():
    """2026-10-25: 03:00 CEST -> 02:00 CET. Between 00:00 UTC and 02:00 UTC there are exactly
    eight quarters even though local clocks show 02:xx twice."""
    t, ledger = QuarterTracker(), MonthLedger(tz=BRUSSELS)
    start = utc(0, 0, day=25, month=10)
    end = utc(2, 0, day=25, month=10)
    results = run(t, ledger, start, end, lambda ts: 1000)
    assert len(results) == 8
    starts = [r.start for r in results]
    assert starts == sorted(set(starts))
    local_labels = [r.start.astimezone(BRUSSELS).strftime("%H:%M") for r in results]
    # 02:00 CEST, 02:15, 02:30, 02:45, then 02:00 CET again ...
    assert local_labels == ["02:00", "02:15", "02:30", "02:45", "02:00", "02:15", "02:30", "02:45"]
    assert all(r.average_w == pytest.approx(1000) for r in results)


def test_spring_dst_night_has_no_missing_or_double_quarters():
    """2026-03-29: 02:00 CET -> 03:00 CEST. 00:30 UTC .. 02:00 UTC = 6 contiguous quarters."""
    t, ledger = QuarterTracker(), MonthLedger(tz=BRUSSELS)
    start = utc(0, 30, day=29, month=3)
    end = utc(2, 0, day=29, month=3)
    results = run(t, ledger, start, end, lambda ts: 500)
    assert len(results) == 6
    for a, b in zip(results, results[1:], strict=False):
        assert a.end == b.start
    labels = [r.start.astimezone(BRUSSELS).strftime("%H:%M") for r in results]
    assert labels == ["01:30", "01:45", "03:00", "03:15", "03:30", "03:45"]


def test_month_rollover_assigns_last_quarter_to_old_month_and_resets_target():
    t, ledger = QuarterTracker(), MonthLedger(tz=BRUSSELS)
    # 23:30 local Aug 31 .. 00:30 local Sep 1 (CEST): 21:30 .. 22:30 UTC
    start = local(2026, 8, 31, 23, 30)
    end = local(2026, 9, 1, 0, 30)

    def load(ts):
        # a 6 kW peak in the very last quarter of August, 1 kW otherwise
        return 6000 if local(2026, 8, 31, 23, 45) <= ts < local(2026, 9, 1, 0, 0) else 1000

    results = run(t, ledger, start, end, load)
    assert [month_key_for(r.start, BRUSSELS) for r in results] == [
        "2026-08",
        "2026-08",
        "2026-09",
        "2026-09",
    ]
    assert ledger.month_peak("2026-08").raw_kw == pytest.approx(6.0)
    assert ledger.month_peak("2026-09").raw_kw == pytest.approx(1.0)
    # September starts with a fresh target: floor, not August's 6 kW
    assert effective_target_kw(ledger.month_peak("2026-09").peak_kw) == 2.5
    assert effective_target_kw(ledger.month_peak("2026-08").peak_kw) == pytest.approx(6.0)


def test_full_day_with_ev_charging_peak_and_margin_signal():
    """A day at 800 W baseline with a 7 kW EV session 18:00-19:30 local. Checks the recorded
    peak, the top-5 and the margin/at-risk signals just after the charger starts."""
    t, ledger = QuarterTracker(), MonthLedger(tz=BRUSSELS)
    day_start = local(2026, 8, 18, 0, 0)
    day_end = local(2026, 8, 19, 0, 0)
    ev_from, ev_to = local(2026, 8, 18, 18, 0), local(2026, 8, 18, 19, 30)

    def load(ts):
        return 800 + (7000 if ev_from <= ts < ev_to else 0)

    results = run(t, ledger, day_start, day_end, load, step_s=30)
    assert len(results) == 96
    mp = ledger.month_peak("2026-08")
    assert mp.raw_kw == pytest.approx(7.8)
    assert mp.at == ev_from + timedelta(minutes=15)  # first EV quarter ends here (ties keep first)
    assert len(mp.top) == 5 and all(e.kw == pytest.approx(7.8) for e in mp.top)

    # Replay the moment 2 minutes into the first EV quarter with a fresh tracker/ledger state
    # where the month peak so far is the baseline (0.8 kW -> target = floor 2.5 kW).
    t2 = QuarterTracker()
    ts = ev_from
    while ts <= ev_from + timedelta(minutes=2):
        t2.on_power(ts, 7800)
        ts += timedelta(seconds=10)
    st = t2.status(ev_from + timedelta(minutes=2))
    target_w = effective_target_kw(2.5) * 1000
    assert st.predicted_end_w == pytest.approx(7800)
    assert st.is_at_risk(target_w, 0.9)
    assert not st.is_certain_break(target_w)  # 260 Wh used < 625 Wh budget
    # margin: (625 - 260) Wh over the remaining 13 min -> ~1685 W allowed on average
    assert st.margin_w(target_w) == pytest.approx((625 - 7800 * 2 / 60) / (13 / 60))
    # ... and 5 minutes in, the peak can no longer be saved
    ts = ev_from + timedelta(minutes=2, seconds=10)
    while ts <= ev_from + timedelta(minutes=5):
        t2.on_power(ts, 7800)
        ts += timedelta(seconds=10)
    st = t2.status(ev_from + timedelta(minutes=5))
    assert st.is_certain_break(target_w)  # 650 Wh > 625 Wh
