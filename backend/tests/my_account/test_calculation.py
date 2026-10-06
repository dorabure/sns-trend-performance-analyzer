from decimal import Decimal

import pytest

from app.services.my_account_service import average, engagement_rate, known_sum, number


@pytest.mark.parametrize("engagement,reach,impressions,views,expected,kind,value", [
    (13, 100, 200, 300, Decimal(13), "reach", 100),
    (13, None, 200, 300, Decimal("6.5"), "impressions", 200),
    (13, None, None, 200, Decimal("6.5"), "views", 200),
    (13, 0, 100, 100, None, "reach", 0),
    (13, None, 0, 100, None, "impressions", 0),
    (13, None, None, 0, None, "views", 0),
    (13, None, None, None, None, None, None),
    (None, 100, 200, 300, None, "reach", 100),
    (0, 100, 200, 300, Decimal(0), "reach", 100),
])
def test_rate_denominator(engagement, reach, impressions, views, expected, kind, value):
    assert engagement_rate(engagement, reach, impressions, views) == (expected, kind, value)


@pytest.mark.parametrize("values,total,avg", [([], None, None), ([None, None], None, None), ([0], 0, Decimal(0)), ([0, None, 10], 10, Decimal(5)), ([1, 2], 3, Decimal("1.5"))])
def test_known_aggregates(values, total, avg):
    assert known_sum(values) == total and average(values) == avg


@pytest.mark.parametrize("value,expected", [(None, None), (Decimal("1.23445"), 1.2345), (Decimal("1.23444"), 1.2344), (Decimal(0), 0.0)])
def test_rounding(value, expected):
    assert number(value) == expected
