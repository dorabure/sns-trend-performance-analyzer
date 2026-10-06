from decimal import Decimal as N

import pytest

from app.services.trend_calculation import (RAW_QUANTUM, calculate_acceleration,
    WindowAggregate, calculate_engagement, calculate_engagement_growth,
    calculate_growth_rate, calculate_trend_score, rounded)


@pytest.mark.parametrize("values,expected", [((None, None, None, None), None),
    ((10, None, 3, None), 13), ((0, 0, 0, 0), 0), ((0, None, None, None), 0),
    ((1, 2, 3, 4), 10), ((2**63 - 1, 0, None, None), 2**63 - 1)])
def test_engagement(values, expected):
    assert calculate_engagement(*values) == expected


@pytest.mark.parametrize("total,known,expected", [(30, 2, "15"), (0, 0, None), (0, 2, "0"), (1, 3, "0.3333")])
def test_known_average(total, known, expected):
    result = rounded(WindowAggregate(3, total, known).avg_engagement, RAW_QUANTUM)
    assert result == (N(expected) if expected is not None else None)


@pytest.mark.parametrize("current,previous,expected", [((150, 1), (100, 1), "50"),
    ((0, 1), (100, 1), "-100"), ((10, 1), (0, 1), None),
    ((0, 0), (100, 1), None), ((100, 1), (0, 0), None),
    ((100, 2), (100, 1), "0")])
def test_engagement_total_growth(current, previous, expected):
    result = calculate_engagement_growth(WindowAggregate(2, *current), WindowAggregate(2, *previous))
    assert result == (N(expected) if expected is not None else None)


@pytest.mark.parametrize("current,previous,expected", [(20, 10, "100"), (5, 10, "-50"),
    (0, 10, "-100"), (10, 10, "0"), (10, 0, None), (0, 0, None),
    (None, 10, None), (10, None, None), (1, 3, "-66.6667"),
    (10**18, 10**18, "0"), (N("1.5"), N("1"), "50")])
def test_growth(current, previous, expected):
    result = rounded(calculate_growth_rate(current, previous), RAW_QUANTUM)
    assert result == (N(expected) if expected is not None else None)


@pytest.mark.parametrize("counts,expected", [((30, 15, 10), "50"), ((5, 10, 20), "0"),
    ((0, 10, 10), "-100"), ((10, 0, 10), None), ((10, 10, 0), None)])
def test_acceleration(counts, expected):
    current, previous, prior = counts
    result = calculate_acceleration(calculate_growth_rate(current, previous), calculate_growth_rate(previous, prior))
    assert result == (N(expected) if expected is not None else None)


@pytest.mark.parametrize("values,expected", [((80, 60, 50, 40), "64.00"),
    ((0, 0, 0, 0), "0.00"), ((100, 100, 100, 100), "100.00"),
    ((None, 60, 50, 40), None), ((80, None, 50, 40), None),
    ((80, 60, None, 40), None), ((80, 60, 50, None), None),
    ((N("0.01"), N("0.01"), 0, 0), "0.01")])
def test_weighted_score(values, expected):
    result = calculate_trend_score(*(N(v) if v is not None else None for v in values))
    assert result == (N(expected) if expected is not None else None)


@pytest.mark.parametrize("value,expected", [("1.23445", "1.2345"), ("-1.23445", "-1.2345"),
    ("0.00005", "0.0001"), ("0", "0.0000")])
def test_raw_half_up(value, expected):
    assert rounded(N(value), RAW_QUANTUM) == N(expected)
