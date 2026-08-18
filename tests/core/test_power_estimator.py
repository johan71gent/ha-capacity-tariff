"""QuarterTracker fed with an instantaneous power sensor only (fallback 2)."""

from datetime import timedelta

import pytest

from custom_components.capacity_tariff.core import QuarterTracker, Source

from .conftest import feed_constant_power, utc


def test_constant_load_gives_exact_average(q_start):
    t = QuarterTracker()
    end = q_start + timedelta(minutes=15)
    closed = feed_constant_power(t, q_start, end, 1000)
    assert closed == []
    closed = t.tick(end)
    assert len(closed) == 1
    r = closed[0]
    assert r.start == q_start and r.end == end
    assert r.average_w == pytest.approx(1000)
    assert r.source is Source.POWER
    assert r.coverage == pytest.approx(1.0)
    assert r.max_gap_s == pytest.approx(10)
    assert r.energy_wh == pytest.approx(250)


def test_step_load_is_time_weighted(q_start):
    t = QuarterTracker()
    mid = q_start + timedelta(minutes=7, seconds=30)
    end = q_start + timedelta(minutes=15)
    feed_constant_power(t, q_start, mid, 2000)
    feed_constant_power(t, mid, end, 0)
    (r,) = t.tick(end)
    assert r.average_w == pytest.approx(1000)


def test_sparse_updates_use_zero_order_hold(q_start):
    """Sensors that only report on change: one sample holds until the next."""
    t = QuarterTracker()
    end = q_start + timedelta(minutes=15)
    t.on_power(q_start, 4000)
    t.on_power(q_start + timedelta(minutes=5), 1000)  # 5 min at 4 kW
    t.on_power(q_start + timedelta(minutes=14), 1000)  # 9 min at 1 kW (HA re-feeds states)
    (r,) = t.tick(end)  # last minute held
    assert r.average_w == pytest.approx((4000 * 5 + 1000 * 10) / 15)
    assert r.coverage == pytest.approx(1.0)
    assert r.max_gap_s == pytest.approx(540)


def test_long_silence_at_the_end_is_not_held_but_reported_as_partial(q_start):
    """Beyond the hold tolerance we stop pretending: only measured time counts as covered."""
    t = QuarterTracker()
    end = q_start + timedelta(minutes=15)
    t.on_power(q_start, 4000)
    t.on_power(q_start + timedelta(minutes=5), 1000)
    (r,) = t.tick(end)  # silent for the last 10 minutes
    assert r.average_w == pytest.approx(4000)  # only the measured 5 minutes
    assert r.coverage == pytest.approx(5 / 15)
    assert "tail_missing" in r.flags
    assert r.max_gap_s == pytest.approx(600)


def test_late_first_sample_gives_partial_coverage(q_start):
    t = QuarterTracker()
    first = q_start + timedelta(minutes=5)
    end = q_start + timedelta(minutes=15)
    feed_constant_power(t, first, end, 3000)
    (r,) = t.tick(end)
    assert r.coverage == pytest.approx(10 / 15)
    assert r.average_w == pytest.approx(3000)  # average over the covered window, not diluted


def test_hold_carries_across_the_boundary(q_start):
    t = QuarterTracker()
    end = q_start + timedelta(minutes=15)
    feed_constant_power(t, q_start, end - timedelta(seconds=10), 2000)
    # next sample arrives after the boundary: previous quarter closes with the held value
    closed = t.on_power(end + timedelta(seconds=10), 500)
    assert len(closed) == 1
    assert closed[0].average_w == pytest.approx(2000)
    assert closed[0].coverage == pytest.approx(1.0)
    # new quarter started at the boundary with full coverage thanks to the hold
    st = t.status(end + timedelta(seconds=10))
    assert st.start == end
    assert st.coverage == pytest.approx(1.0)
    assert st.running_average_w == pytest.approx(2000)  # 10 s at held 2 kW


def test_negative_power_is_clamped_to_zero(q_start):
    t = QuarterTracker()
    end = q_start + timedelta(minutes=15)
    feed_constant_power(t, q_start, end, -1500)  # net sensor while injecting
    (r,) = t.tick(end)
    assert r.average_w == 0.0


def test_out_of_order_sample_is_ignored(q_start):
    t = QuarterTracker()
    t.on_power(q_start + timedelta(seconds=20), 1000)
    t.on_power(q_start + timedelta(seconds=10), 9000)  # older than the previous sample
    assert t.last_power_w == 1000


def test_tick_before_end_does_nothing(q_start):
    t = QuarterTracker()
    t.on_power(q_start, 1000)
    assert t.tick(q_start + timedelta(minutes=14, seconds=59)) == []
    assert t.active and t.start == q_start


def test_status_before_any_sample_is_none():
    assert QuarterTracker().status(utc(12, 3)) is None


class TestStatusMaths:
    """Prediction, margin and certainty on a simple constant-load quarter."""

    @pytest.fixture
    def tracker(self, q_start):
        t = QuarterTracker()
        feed_constant_power(t, q_start, q_start + timedelta(minutes=5, seconds=1), 3000)
        return t

    def test_running_average_and_energy(self, tracker, q_start):
        st = tracker.status(q_start + timedelta(minutes=5))
        assert st.source is Source.POWER
        assert st.elapsed_s == 300 and st.remaining_s == 600
        assert st.running_average_w == pytest.approx(3000)
        assert st.energy_wh_estimated == pytest.approx(250)  # 3 kW x 5 min
        assert st.coverage == pytest.approx(1.0)

    def test_prediction_holds_current_power(self, tracker, q_start):
        st = tracker.status(q_start + timedelta(minutes=5))
        assert st.predicted_end_w == pytest.approx(3000)
        assert st.hold_power_w == 3000

    def test_margin_against_target(self, tracker, q_start):
        st = tracker.status(q_start + timedelta(minutes=5))
        # budget for 2.5 kW = 625 Wh, used 250 Wh, 10 min left -> 375 Wh / (10/60 h) = 2250 W
        assert st.margin_w(2500) == pytest.approx(2250)
        # a 4 kW target leaves 750 Wh -> 4500 W
        assert st.margin_w(4000) == pytest.approx(4500)
        # already over budget -> negative margin
        assert st.margin_w(500) < 0

    def test_certain_break_only_when_measured_energy_exceeds_budget(self, tracker, q_start):
        st = tracker.status(q_start + timedelta(minutes=5))
        assert not st.is_certain_break(2500)  # 250 Wh < 625 Wh
        assert st.is_certain_break(900)  # 250 Wh > 225 Wh

    def test_at_risk_uses_threshold_fraction(self, tracker, q_start):
        st = tracker.status(q_start + timedelta(minutes=5))
        assert st.is_at_risk(target_w=3200, threshold=0.9)  # 3000 > 2880
        assert not st.is_at_risk(target_w=3400, threshold=0.9)  # 3000 < 3060

    def test_certain_break_becomes_true_late_in_quarter(self, q_start):
        t = QuarterTracker()
        feed_constant_power(t, q_start, q_start + timedelta(minutes=14), 3000)
        st = t.status(q_start + timedelta(minutes=14))
        # measured = integrated up to the last sample (13:59:50), no extrapolated tail
        assert st.energy_wh_measured == pytest.approx(3000 * (14 * 60 - 10) / 3600)
        assert st.is_certain_break(2500)  # 700 Wh > 625 Wh, even at 0 W from now on

    def test_status_is_clamped_to_quarter_end(self, tracker, q_start):
        st = tracker.status(q_start + timedelta(minutes=20))  # not rolled yet
        assert st.remaining_s == 0
        assert st.now == q_start + timedelta(minutes=15)


def test_partial_coverage_scales_estimated_energy(q_start):
    """After a mid-quarter start the covered average is extrapolated over the elapsed time,
    so margin/prediction stay protective instead of assuming 0 W before the first sample."""
    t = QuarterTracker()
    first = q_start + timedelta(minutes=5)
    feed_constant_power(t, first, first + timedelta(minutes=5, seconds=1), 3000)
    st = t.status(q_start + timedelta(minutes=10))
    assert st.coverage == pytest.approx(0.5)
    assert st.energy_wh_measured == pytest.approx(250)  # 5 measured minutes
    assert st.energy_wh_estimated == pytest.approx(500)  # scaled over 10 elapsed minutes
    assert st.predicted_end_w == pytest.approx(3000)
