"""Clock-quarter boundaries, including DST transitions in Europe/Brussels."""

from datetime import datetime, timedelta

import pytest

from custom_components.capacity_tariff.core import quarter_bounds

from .conftest import BRUSSELS, local, utc


@pytest.mark.parametrize(
    ("ts", "expected_start"),
    [
        (utc(12, 0, 0), utc(12, 0)),
        (utc(12, 14, 59), utc(12, 0)),
        (utc(12, 15, 0), utc(12, 15)),
        (utc(12, 44, 59), utc(12, 30)),
        (utc(12, 59, 59), utc(12, 45)),
    ],
)
def test_bounds_align_to_15_minutes(ts, expected_start):
    start, end = quarter_bounds(ts)
    assert start == expected_start
    assert end - start == timedelta(minutes=15)


def test_bounds_are_returned_in_utc_for_local_input():
    start, end = quarter_bounds(local(2026, 8, 18, 14, 7))  # CEST = UTC+2
    assert start == utc(12, 0)
    assert start.tzinfo is not None and start.utcoffset() == timedelta(0)


def test_naive_datetime_is_rejected():
    with pytest.raises(ValueError):
        quarter_bounds(datetime(2026, 8, 18, 12, 0))


def test_autumn_fallback_hour_exists_twice_and_gives_distinct_quarters():
    # 2026-10-25: 03:00 CEST -> 02:00 CET. Local 02:30 happens twice.
    first = local(2026, 10, 25, 2, 30, fold=0)  # CEST, 00:30 UTC
    second = local(2026, 10, 25, 2, 30, fold=1)  # CET, 01:30 UTC
    assert first.utcoffset() != second.utcoffset()
    s1, _ = quarter_bounds(first)
    s2, _ = quarter_bounds(second)
    assert s1 != s2
    assert s2 - s1 == timedelta(hours=1)
    # both are still real, aligned quarters
    assert s1.minute == 30 and s2.minute == 30


def test_spring_forward_skips_local_quarters_but_utc_quarters_stay_contiguous():
    # 2026-03-29: 02:00 CET -> 03:00 CEST. Local 02:xx does not exist.
    before = local(2026, 3, 29, 1, 59, 59)  # CET  = 00:59:59 UTC
    after = local(2026, 3, 29, 3, 0, 0)  # CEST = 01:00:00 UTC
    s_before, e_before = quarter_bounds(before)
    s_after, _ = quarter_bounds(after)
    assert e_before == s_after  # no gap, no overlap
    assert s_after.astimezone(BRUSSELS).hour == 3


def test_local_quarter_boundaries_coincide_with_utc_boundaries():
    # Belgium's UTC offset is a whole number of hours (1 or 2), so :00/:15/:30/:45 in
    # local time are also :00/:15/:30/:45 in UTC. Check across both DST regimes.
    for probe in (local(2026, 1, 15, 8, 45), local(2026, 7, 15, 8, 45)):
        start, _ = quarter_bounds(probe)
        assert start.astimezone(BRUSSELS).minute == 45
        assert start.astimezone(BRUSSELS).second == 0
