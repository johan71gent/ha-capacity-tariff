"""MonthLedger: month attribution, peak precedence, floor, rolling average, persistence."""

import json
from datetime import timedelta

import pytest

from custom_components.capacity_tariff.core import (
    MonthLedger,
    QuarterResult,
    Source,
    month_key_for,
    shift_month,
)

from .conftest import BRUSSELS, local, utc


def result(start, kw, *, source=Source.ENERGY, coverage=1.0):
    return QuarterResult(
        start=start,
        end=start + timedelta(minutes=15),
        average_w=kw * 1000,
        source=source,
        coverage=coverage,
        max_gap_s=1.0,
    )


@pytest.fixture
def ledger():
    return MonthLedger(tz=BRUSSELS)


# ---------------------------------------------------------------- month keys


@pytest.mark.parametrize(
    ("key", "delta", "expected"),
    [
        ("2026-08", -1, "2026-07"),
        ("2026-01", -1, "2025-12"),
        ("2026-12", 1, "2027-01"),
        ("2026-03", -12, "2025-03"),
        ("2026-03", -14, "2025-01"),
    ],
)
def test_shift_month(key, delta, expected):
    assert shift_month(key, delta) == expected


def test_month_key_uses_local_time_not_utc():
    # 2026-09-01 00:05 Brussels = 2026-08-31 22:05 UTC -> belongs to September
    ts = local(2026, 9, 1, 0, 5)
    assert ts.astimezone(BRUSSELS).month == 9
    assert month_key_for(ts, BRUSSELS) == "2026-09"
    # 2026-08-31 23:50 Brussels is still August
    assert month_key_for(local(2026, 8, 31, 23, 50), BRUSSELS) == "2026-08"


def test_quarter_belongs_to_month_of_its_start(ledger):
    # the quarter 23:45-00:00 of Aug 31 (local) is recorded in August
    start = local(2026, 8, 31, 23, 45)
    ledger.record(result(start, 5.0))
    assert ledger.month_peak("2026-08").raw_kw == 5.0
    assert ledger.month_peak("2026-09").raw_kw is None


# ---------------------------------------------------------------- recording


def test_record_tracks_highest_quarter_and_top5(ledger):
    base = utc(10, 0)
    kws = [3.0, 4.5, 2.0, 4.4, 6.1, 1.0, 5.0]
    raised = [
        ledger.record(result(base + timedelta(minutes=15 * i), kw)) for i, kw in enumerate(kws)
    ]
    assert raised == [True, True, False, False, True, False, False]
    mp = ledger.month_peak("2026-08")
    assert mp.raw_kw == 6.1 and mp.peak_kw == 6.1
    assert mp.source is Source.ENERGY
    assert mp.at == base + timedelta(minutes=15 * 4 + 15)  # end of the peak quarter
    assert [e.kw for e in mp.top] == [6.1, 5.0, 4.5, 4.4, 3.0]


def test_floor_applies_when_peak_is_low_or_absent(ledger):
    assert ledger.month_peak("2026-08").peak_kw == 2.5
    assert ledger.month_peak("2026-08").raw_kw is None
    assert ledger.month_peak("2026-08").source is Source.NONE
    ledger.record(result(utc(10, 0), 1.2))
    mp = ledger.month_peak("2026-08")
    assert mp.raw_kw == 1.2 and mp.peak_kw == 2.5


def test_custom_floor():
    ledger = MonthLedger(tz=BRUSSELS, floor_kw=1.0)
    ledger.record(result(utc(10, 0), 1.2))
    assert ledger.month_peak("2026-08").peak_kw == 1.2


def test_low_coverage_and_no_data_results_are_ignored(ledger):
    assert ledger.record(result(utc(10, 0), 9.0, coverage=0.5)) is False
    assert ledger.record(result(utc(10, 15), 9.0, source=Source.NONE)) is False
    assert ledger.month_peak("2026-08").raw_kw is None
    assert ledger.month_peak("2026-08").top == ()


def test_precedence_manual_over_meter_over_calc(ledger):
    ledger.record(result(utc(10, 0), 4.0))
    assert ledger.month_peak("2026-08").source is Source.ENERGY
    ledger.set_meter_peak("2026-08", 3.8, utc(10, 15))
    mp = ledger.month_peak("2026-08")
    assert mp.source is Source.METER and mp.raw_kw == 3.8  # meter wins even when lower
    ledger.set_manual_peak("2026-08", 4.2, None)
    mp = ledger.month_peak("2026-08")
    assert mp.source is Source.MANUAL and mp.raw_kw == 4.2 and mp.at is None
    ledger.clear_manual_peak("2026-08")
    assert ledger.month_peak("2026-08").source is Source.METER
    # calculated top-5 stays available for diagnostics regardless
    assert ledger.month_peak("2026-08").top[0].kw == 4.0


def test_meter_peak_only_rises_within_a_month(ledger):
    assert ledger.set_meter_peak("2026-08", 3.0, utc(9, 0)) is True
    assert ledger.set_meter_peak("2026-08", 2.0, utc(9, 15)) is False  # stale/lower value ignored
    assert ledger.set_meter_peak("2026-08", 3.5, utc(9, 30)) is True
    assert ledger.month_peak("2026-08").raw_kw == 3.5


def test_reset_month_forgets_everything(ledger):
    ledger.record(result(utc(10, 0), 4.0))
    ledger.set_meter_peak("2026-08", 4.1, None)
    ledger.reset_month("2026-08")
    assert not ledger.has_data("2026-08")
    assert ledger.month_peak("2026-08").peak_kw == 2.5


# ---------------------------------------------------------------- rolling average


def test_rolling_average_counts_missing_months_at_floor(ledger):
    ledger.record(result(utc(10, 0), 5.5))  # 2026-08 only
    # 11 months at 2.5 + one at 5.5
    assert ledger.rolling_average("2026-08") == pytest.approx((11 * 2.5 + 5.5) / 12)


def test_rolling_average_window_is_12_months_ending_at_key(ledger):
    for i in range(14):
        key = shift_month("2026-08", -i)
        ledger.set_meter_peak(key, 4.0, None)
    ledger.set_meter_peak("2025-08", 40.0, None)  # 13 months back: outside the window
    assert ledger.rolling_average("2026-08") == pytest.approx(4.0)
    ledger.set_meter_peak("2025-09", 16.0, None)  # exactly 12 months back: inside
    assert ledger.rolling_average("2026-08") == pytest.approx((11 * 4.0 + 16.0) / 12)


def test_prune_keeps_13_months(ledger):
    for i in range(20):
        ledger.set_meter_peak(shift_month("2026-08", -i), 3.0, None)
    ledger.prune("2026-08")
    assert ledger.months()[0] == "2025-08"
    assert len(ledger.months()) == 13


# ---------------------------------------------------------------- persistence


def test_to_dict_from_dict_round_trip(ledger):
    ledger.record(result(utc(10, 0), 4.0))
    ledger.record(result(utc(10, 15), 3.0))
    ledger.set_meter_peak("2026-07", 3.3, utc(9, 0, day=3, month=7))
    ledger.set_manual_peak("2026-06", 2.9, None)
    payload = json.loads(json.dumps(ledger.to_dict()))
    restored = MonthLedger.from_dict(payload, tz=BRUSSELS)
    for key in ("2026-06", "2026-07", "2026-08"):
        assert restored.month_peak(key) == ledger.month_peak(key)
    assert restored.rolling_average("2026-08") == ledger.rolling_average("2026-08")


def test_from_dict_tolerates_empty_or_partial_payload():
    assert MonthLedger.from_dict({}, tz=BRUSSELS).months() == []
    partial = {"months": {"2026-08": {"meter": {"kw": 3.0, "at": None, "source": "meter"}}}}
    ledger = MonthLedger.from_dict(partial, tz=BRUSSELS)
    assert ledger.month_peak("2026-08").raw_kw == 3.0
    assert ledger.month_peak("2026-08").top == ()


def test_invalid_month_key_is_rejected(ledger):
    with pytest.raises(ValueError):
        ledger.set_meter_peak("2026-13", 1.0, None)
