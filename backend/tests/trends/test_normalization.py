from decimal import Decimal as N

import pytest

from app.services.trend_calculation import normalize_scores


@pytest.mark.parametrize("values,expected", [([10, 20, 30], [0, 50, 100]),
    ([20, 20, 20], [50, 50, 50]), ([42], [50]), ([None], [None]),
    ([None, 10, 30], [None, 0, 100]), ([], []),
    ([-100, -50, 0], [0, 50, 100]), ([0, 1, 3], [0, N("33.33"), 100]),
    ([None, None], [None, None]), ([0, 0], [50, 50]),
    ([N("0.00001"), N("0.00002")], [0, 100])])
def test_min_max(values, expected):
    result = normalize_scores([N(v) if v is not None else None for v in values])
    assert result == [N(v) if v is not None else None for v in expected]
    assert all(value is None or value.as_tuple().exponent == -2 for value in result)
