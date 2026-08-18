"""Persistence: snapshot/restore of the running quarter, restarts and data gaps."""

import json
from datetime import timedelta

import pytest

from custom_components.capacity_tariff.core import QuarterTracker, Source

from .conftest import feed_constant_energy, feed_constant_power


def _roundtrip(tracker: QuarterTracker, now) -> QuarterTracker:
    payload = json.loads(json.dumps(tracker.to_dict()))  # must be JSON-serialisable
    return QuarterTracker.from_dict(payload, now)


def test_restart_mid_quarter_with_energy_register_is_exact(q_start):
    """HA restarts at :05, comes back at :07. With the register anchored at the quarter start,
    the quarter is reconstructed exactly."""
    t = QuarterTracker()
    end = q_start + timedelta(minutes=15)
    kwh0 = 250.0
    feed_constant_energy(t, q_start, q_start + timedelta(minutes=5), kw=2.0, kwh0=kwh0)
    t2 = _roundtrip(t, now=q_start + timedelta(minutes=7))
    assert t2.active and t2.start == q_start
    # data resumes at :07, load unchanged (2 kW): the register just continued
    feed_constant_energy(t2, q_start + timedelta(minutes=7), end, kw=2.0, kwh0=kwh0 + 2.0 * 7 / 60)
    (r,) = t2.tick(end)
    assert r.source is Source.ENERGY
    assert r.average_w == pytest.approx(2000, rel=1e-6)
    assert r.coverage == pytest.approx(1.0)
    assert "restored" in r.flags
    assert r.max_gap_s == pytest.approx(130)  # the restart is visible as a gap in samples


def test_restart_mid_quarter_with_energy_register_sees_load_during_downtime(q_start):
    """Load changed while HA was down; the register still captures it."""
    t = QuarterTracker()
    end = q_start + timedelta(minutes=15)
    feed_constant_energy(t, q_start, q_start + timedelta(minutes=5), kw=1.0, kwh0=0.0)
    t2 = _roundtrip(t, now=q_start + timedelta(minutes=10))
    # during the 5 min downtime a 10 kW load ran: register jumped by 10 kW x 5/60 h
    kwh_at_10 = 1.0 * 5 / 60 + 10.0 * 5 / 60
    feed_constant_energy(t2, q_start + timedelta(minutes=10), end, kw=1.0, kwh0=kwh_at_10)
    (r,) = t2.on_energy(end, kwh_at_10 + 1.0 * 5 / 60)  # boundary sample closes it exactly
    assert r.average_w == pytest.approx((1000 * 10 + 10000 * 5) / 15, rel=1e-6)


def test_restart_mid_quarter_power_only_holds_last_power(q_start):
    t = QuarterTracker()
    end = q_start + timedelta(minutes=15)
    feed_constant_power(t, q_start, q_start + timedelta(minutes=5), 3000)
    t2 = _roundtrip(t, now=q_start + timedelta(minutes=6))
    feed_constant_power(t2, q_start + timedelta(minutes=6), end, 3000)
    (r,) = t2.tick(end)
    assert r.source is Source.POWER
    assert r.average_w == pytest.approx(3000)
    assert "restored" in r.flags


def test_restore_after_quarter_passed_drops_it_and_reports_gap(q_start):
    t = QuarterTracker()
    feed_constant_energy(t, q_start, q_start + timedelta(minutes=5), kw=1.0, kwh0=0.0)
    last_sample = q_start + timedelta(minutes=4, seconds=50)
    # HA was down for an hour
    back = q_start + timedelta(hours=1, minutes=3)
    t2 = _roundtrip(t, now=back)
    assert not t2.active
    # first sample after the restart: register shows what was consumed meanwhile
    kwh_back = 1.0 * (back - q_start).total_seconds() / 3600 + 2.0  # +2 kWh extra during downtime
    closed = t2.on_energy(back, kwh_back)
    assert closed == []  # nothing invented for the missed quarters
    assert t2.gap is not None
    assert t2.gap.start == last_sample and t2.gap.end == back
    expected_avg_w = (
        (kwh_back - 1.0 * (290 / 3600)) * 1000 / ((back - last_sample).total_seconds() / 3600)
    )
    assert t2.gap.average_w == pytest.approx(expected_avg_w, rel=1e-6)
    # the new quarter starts at the first sample: partial coverage, nothing pretended
    st = t2.status(back)
    assert st.start == q_start + timedelta(hours=1)
    assert st.coverage == pytest.approx(0.0)


def test_restore_after_quarter_passed_power_only_gap_has_no_average(q_start):
    t = QuarterTracker()
    feed_constant_power(t, q_start, q_start + timedelta(minutes=5), 1000)
    back = q_start + timedelta(minutes=40)
    t2 = _roundtrip(t, now=back)
    t2.on_power(back, 1000)
    assert t2.gap is not None and t2.gap.average_w is None
    assert t2.gap.start == q_start + timedelta(minutes=4, seconds=50)


def test_multi_quarter_silence_without_restart_yields_single_result_and_gap(q_start):
    """Source entity silent for an hour (no restart): the running quarter closes with the held
    value, the quarters in between are reported as a Gap, not as results."""
    t = QuarterTracker()
    feed_constant_power(t, q_start, q_start + timedelta(minutes=10), 1000)
    closed = t.on_power(q_start + timedelta(hours=1, minutes=2), 1000)
    assert len(closed) == 1
    assert closed[0].start == q_start
    assert closed[0].coverage == pytest.approx(590 / 900)  # not held for 5 minutes
    assert "tail_missing" in closed[0].flags
    assert t.gap is not None
    assert t.gap.start == q_start + timedelta(minutes=9, seconds=50)
    assert t.gap.end == q_start + timedelta(hours=1, minutes=2)
    assert t.start == q_start + timedelta(hours=1)


def test_multi_quarter_silence_with_energy_gives_gap_average(q_start):
    t = QuarterTracker()
    feed_constant_energy(t, q_start, q_start + timedelta(minutes=10), kw=1.0, kwh0=0.0)
    last_ts = q_start + timedelta(minutes=9, seconds=50)
    later = q_start + timedelta(hours=1, minutes=3)
    # 4 kW on average between the last sample and now
    kwh_later = 1.0 * (590 / 3600) + 4.0 * (later - last_ts).total_seconds() / 3600
    closed = t.on_energy(later, kwh_later)
    assert len(closed) == 1  # only the quarter that was running
    assert closed[0].average_w == pytest.approx(1000, rel=1e-6)  # not polluted by the gap
    assert closed[0].coverage == pytest.approx(590 / 900)
    assert t.gap is not None
    assert t.gap.average_w == pytest.approx(4000, rel=1e-6)
    # the new quarter did NOT inherit an interpolated anchor across the gap
    st = t.status(later)
    assert st.start == q_start + timedelta(hours=1)
    assert st.coverage == pytest.approx(0.0)


def test_snapshot_is_json_and_round_trips_fields(q_start):
    t = QuarterTracker()
    t.on_power(q_start, 1234)
    t.on_energy(q_start, 10.5)
    t.on_meter_average(q_start + timedelta(seconds=1), 1200)
    d = t.to_dict()
    json.dumps(d)
    t2 = QuarterTracker.from_dict(d, now=q_start + timedelta(seconds=2))
    assert t2.start == q_start
    assert t2.last_power_w == 1234
    st = t2.status(q_start + timedelta(seconds=2))
    assert st.source is Source.METER


def test_from_empty_dict_is_a_fresh_tracker(q_start):
    t = QuarterTracker.from_dict({}, now=q_start)
    assert not t.active
    assert t.status(q_start) is None
