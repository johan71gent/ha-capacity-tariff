"""Cost formula and effective target."""

import pytest

from custom_components.capacity_tariff.core import effective_target_kw, month_cost, year_cost


def test_month_cost_is_one_twelfth_of_yearly_tariff():
    assert month_cost(4.0, 48.0) == pytest.approx(16.0)


def test_year_cost_uses_average_peak():
    assert year_cost(3.5, 48.0) == pytest.approx(168.0)


def test_effective_target_never_below_floor():
    assert effective_target_kw(0.0) == 2.5
    assert effective_target_kw(1.9) == 2.5
    assert effective_target_kw(1.9, goal_kw=2.0) == 2.5


def test_effective_target_is_month_peak_when_no_goal():
    assert effective_target_kw(3.7) == 3.7


def test_goal_raises_target_but_cannot_lower_it_below_current_peak():
    assert effective_target_kw(3.0, goal_kw=4.0) == 4.0
    assert effective_target_kw(5.0, goal_kw=4.0) == 5.0
    assert effective_target_kw(3.0, goal_kw=None) == 3.0


def test_custom_floor():
    assert effective_target_kw(0.5, floor_kw=1.0) == 1.0
