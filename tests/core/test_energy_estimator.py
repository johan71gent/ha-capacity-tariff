"""QuarterTracker fed with the cumulative import register (fallback 1)."""

from datetime import timedelta

import pytest

from custom_components.capacity_tariff.core import QuarterTracker, Source

from .conftest import feed_constant_energy, feed_constant_power


def test_energy_register_gives_exact_average(q_start):
    t = QuarterTracker()
    end = q_start + timedelta(minutes=15)
    feed_constant_energy(t, q_start, end, kw=1.0, kwh0=1234.5)
    (r,) = t.tick(end)
    assert r.source is Source.ENERGY
    assert r.average_w == pytest.approx(1000)
    assert r.coverage == pytest.approx(1.0)


def _feed_biased_power_and_true_energy(power_first: bool, q_start):
    """2 kW according to the register, 2.6 kW according to a badly calibrated power sensor."""
    t = QuarterTracker()
    end = q_start + timedelta(minutes=15)
    ts = q_start
    kwh = 100.0
    closed = []
    while ts <= end:  # the sample at the boundary closes the quarter itself
        if power_first:
            closed += t.on_power(ts, 2600)
            closed += t.on_energy(ts, kwh)
        else:
            closed += t.on_energy(ts, kwh)
            closed += t.on_power(ts, 2600)
        ts += timedelta(seconds=10)
        kwh += 2.0 * 10 / 3600
    (r,) = closed
    return r


def test_energy_wins_over_power_when_both_are_fed(q_start):
    """Sampling jitter or calibration errors on the power sensor must not influence the result."""
    r = _feed_biased_power_and_true_energy(power_first=False, q_start=q_start)
    assert r.source is Source.ENERGY
    assert r.average_w == pytest.approx(2000, rel=1e-6)


def test_power_event_arriving_first_after_boundary_only_affects_the_tail(q_start):
    """If the power event of the boundary telegram is processed before the energy event, the
    quarter closes with a held tail (one sample interval); the register still dominates."""
    r = _feed_biased_power_and_true_energy(power_first=True, q_start=q_start)
    assert r.source is Source.ENERGY
    # 10 s of a 30 % biased sensor in a 900 s quarter: 600 W x 10/900 = 6.7 W
    assert r.average_w == pytest.approx(2000 + 600 * 10 / 900, rel=1e-6)


def test_boundary_is_interpolated_when_a_sample_straddles_it(q_start):
    """Samples at :59:55 and :00:05 -> register at the boundary is interpolated, and the two
    quarters together account for exactly the measured energy."""
    t = QuarterTracker()
    end = q_start + timedelta(minutes=15)
    kwh0 = 500.0
    # 2 kW for the first quarter, sampled every 10 s starting at 12:00:05 (so the last
    # sample before the boundary is at 12:14:55)
    ts = q_start + timedelta(seconds=5)
    while ts < end:
        t.on_energy(ts, kwh0 + 2.0 * (ts - q_start).total_seconds() / 3600)
        ts += timedelta(seconds=10)
    # next sample 5 s after the boundary, but now the load is 4 kW
    kwh_boundary_true = kwh0 + 2.0 * 900 / 3600
    closed = t.on_energy(end + timedelta(seconds=5), kwh_boundary_true + 4.0 * 5 / 3600)
    assert len(closed) == 1
    r = closed[0]
    # interpolated boundary sits between 2 kW and 4 kW slopes: tiny error, no tail flag
    assert r.average_w == pytest.approx(2000, rel=0.005)
    assert "energy_tail_estimated" not in r.flags
    # new quarter is anchored at the boundary, so coverage is complete
    st = t.status(end + timedelta(seconds=5))
    assert st.source is Source.ENERGY
    assert st.coverage == pytest.approx(1.0)


def test_tick_before_next_sample_estimates_tail_with_held_power(q_start):
    t = QuarterTracker()
    end = q_start + timedelta(minutes=15)
    ts = q_start
    kwh = 10.0
    while ts < end - timedelta(seconds=30):  # last sample 30 s before the boundary
        t.on_power(ts, 1000)
        t.on_energy(ts, kwh)
        ts += timedelta(seconds=10)
        kwh += 1.0 * 10 / 3600
    (r,) = t.tick(end)
    assert r.source is Source.ENERGY
    assert r.average_w == pytest.approx(1000, rel=1e-6)  # tail estimated at the held 1 kW
    assert "energy_tail_estimated" in r.flags
    # the new quarter continues from the estimated boundary value: energy is conserved
    closed = t.on_energy(end + timedelta(seconds=10), kwh + 1.0 * 40 / 3600)
    assert closed == []
    st = t.status(end + timedelta(seconds=10))
    assert st.source is Source.ENERGY
    assert st.running_average_w == pytest.approx(1000, rel=1e-6)


def test_short_tail_is_not_flagged(q_start):
    t = QuarterTracker()
    end = q_start + timedelta(minutes=15)
    feed_constant_energy(t, q_start, end, kw=1.0, kwh0=0.0, step_s=1)  # last sample at :14:59
    (r,) = t.tick(end)
    assert "energy_tail_estimated" not in r.flags


def test_counter_decrease_restarts_estimator_and_flags(q_start):
    t = QuarterTracker()
    end = q_start + timedelta(minutes=15)
    t.on_energy(q_start, 900.0)
    t.on_energy(q_start + timedelta(minutes=5), 900.5)
    # meter swapped: register drops
    t.on_energy(q_start + timedelta(minutes=5, seconds=10), 0.0)
    t.on_energy(q_start + timedelta(minutes=10), 0.0 + 1.0 * (290 / 3600))
    (r,) = t.tick(end)
    assert "counter_decrease" in r.flags
    # only the part after the reset is trusted (partial coverage) and averages 1 kW
    assert r.coverage < 0.9
    assert r.average_w == pytest.approx(1000, rel=1e-6)


def test_first_sample_mid_quarter_yields_partial_coverage(q_start):
    t = QuarterTracker()
    end = q_start + timedelta(minutes=15)
    feed_constant_energy(t, q_start + timedelta(minutes=6), end, kw=3.0, kwh0=42.0)
    (r,) = t.tick(end)
    assert r.source is Source.ENERGY
    assert r.coverage == pytest.approx(9 / 15, rel=0.02)
    assert r.average_w == pytest.approx(3000, rel=1e-6)


def test_out_of_order_energy_sample_is_ignored(q_start):
    t = QuarterTracker()
    t.on_energy(q_start + timedelta(seconds=20), 10.0)
    t.on_energy(q_start + timedelta(seconds=10), 99.0)
    st = t.status(q_start + timedelta(seconds=20))
    assert st.energy_wh_measured == 0.0


def test_status_with_energy_source_uses_power_for_tail_and_prediction(q_start):
    t = QuarterTracker()
    ts = q_start
    kwh = 0.0
    while ts <= q_start + timedelta(minutes=5):
        t.on_energy(ts, kwh)
        t.on_power(ts, 2000)
        ts += timedelta(seconds=10)
        kwh += 2.0 * 10 / 3600
    st = t.status(q_start + timedelta(minutes=5))
    assert st.source is Source.ENERGY
    assert st.running_average_w == pytest.approx(2000, rel=1e-6)
    assert st.predicted_end_w == pytest.approx(2000, rel=1e-6)
    assert st.margin_w(2500) == pytest.approx((625 - 2000 * 5 / 60) / (10 / 60), rel=1e-6)


def test_power_only_quarter_followed_by_energy_quarter(q_start):
    """Estimator choice is per quarter: energy appears mid-way -> anchor at first sample."""
    t = QuarterTracker()
    end = q_start + timedelta(minutes=15)
    feed_constant_power(t, q_start, end, 1000)
    (r1,) = t.tick(end)
    assert r1.source is Source.POWER
    feed_constant_energy(
        t, end + timedelta(seconds=30), end + timedelta(minutes=15), 2.0, 5.0, step_s=1
    )
    (r2,) = t.tick(end + timedelta(minutes=15))
    assert r2.source is Source.ENERGY
    assert r2.average_w == pytest.approx(2000, rel=2e-3)  # 1 s tail held at the old 1 kW
    assert r2.coverage == pytest.approx(870 / 900, rel=0.02)
