"""QuarterTracker fed with the meter's own running average (OBIS 1.4.0) — the primary source."""

from datetime import timedelta

import pytest

from custom_components.capacity_tariff.core import QuarterTracker, Source

from .conftest import feed_constant_power


def feed_meter_average(tracker, start, end, watts, step_s=1, power_w=None):
    """Simulate a meter reporting a constant running average every ``step_s`` seconds."""
    closed = []
    ts = start
    while ts < end:
        if power_w is not None:
            closed += tracker.on_power(ts, power_w)
        closed += tracker.on_meter_average(ts, watts)
        ts += timedelta(seconds=step_s)
    return closed


def test_meter_average_is_taken_verbatim_at_close(q_start):
    t = QuarterTracker()
    end = q_start + timedelta(minutes=15)
    # our own power sensor disagrees (bias) — the meter is the truth
    feed_meter_average(t, q_start, end, watts=3210, power_w=3900)
    (r,) = t.tick(end)
    assert r.source is Source.METER
    assert r.average_w == 3210
    assert r.coverage == 1.0


def test_status_prefers_meter_and_extrapolates_with_power(q_start):
    t = QuarterTracker()
    feed_meter_average(
        t, q_start, q_start + timedelta(minutes=5, seconds=1), watts=2000, power_w=5000
    )
    st = t.status(q_start + timedelta(minutes=5))
    assert st.source is Source.METER
    assert st.running_average_w == pytest.approx(2000)
    assert st.energy_wh_estimated == pytest.approx(2000 * 5 / 60)
    assert st.hold_power_w == 5000
    # 5 min at 2 kW + 10 min at 5 kW -> 4 kW quarter average
    assert st.predicted_end_w == pytest.approx(4000)
    assert st.margin_w(4000) == pytest.approx(5000)  # exactly the current draw keeps us at 4 kW


def test_stale_meter_sample_falls_back_to_own_estimate(q_start):
    t = QuarterTracker()
    end = q_start + timedelta(minutes=15)
    # meter stops reporting after 5 minutes (e.g. DSMR entity became unavailable)
    feed_meter_average(t, q_start, q_start + timedelta(minutes=5), watts=1000, power_w=1000)
    feed_constant_power(t, q_start + timedelta(minutes=5), end, 1000)
    (r,) = t.tick(end)
    assert r.source is Source.POWER
    assert "meter_stale" in r.flags
    assert r.average_w == pytest.approx(1000)


def test_meter_clock_slightly_ahead_does_not_lose_the_peak(q_start):
    """The meter rolls into the next quarter one second before HA's clock does: its running
    average collapses. The value just before the collapse is the quarter's real average."""
    t = QuarterTracker()
    end = q_start + timedelta(minutes=15)
    feed_meter_average(t, q_start, end - timedelta(seconds=1), watts=6000, power_w=6000)
    # meter already restarted its quarter: reports 6 kW x 1 s / 900 s ~ 7 W
    t.on_meter_average(end - timedelta(seconds=1), 7)
    (r,) = t.tick(end)
    assert r.source is Source.METER
    assert r.average_w == 6000
    assert "meter_rolled_early" in r.flags


def test_genuine_drop_early_in_quarter_is_not_mistaken_for_rollover(q_start):
    t = QuarterTracker()
    # 30 s at 6 kW then a big load switches off: running average halves quickly, but we're
    # nowhere near the end of the quarter, so this is a real drop.
    t.on_meter_average(q_start + timedelta(seconds=30), 6000)
    t.on_meter_average(q_start + timedelta(seconds=60), 3000)
    t.on_meter_average(q_start + timedelta(seconds=90), 2000)
    st = t.status(q_start + timedelta(seconds=90))
    assert st.running_average_w == pytest.approx(2000)


def test_meter_sample_after_boundary_closes_previous_quarter(q_start):
    t = QuarterTracker()
    end = q_start + timedelta(minutes=15)
    feed_meter_average(t, q_start, end, watts=2500)
    closed = t.on_meter_average(end + timedelta(seconds=1), 3)
    assert len(closed) == 1
    assert closed[0].average_w == 2500
    st = t.status(end + timedelta(seconds=1))
    assert st.start == end and st.source is Source.METER


def test_meter_sample_from_previous_quarter_is_not_used_for_the_new_one(q_start):
    t = QuarterTracker()
    end = q_start + timedelta(minutes=15)
    feed_meter_average(t, q_start, end, watts=2500, power_w=1000)
    t.on_power(end + timedelta(seconds=5), 1000)  # rolls the quarter; no meter sample yet
    st = t.status(end + timedelta(seconds=5))
    assert st.source is Source.POWER
