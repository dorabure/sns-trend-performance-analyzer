from decimal import Decimal

import pytest

from app.services.gap_analysis_service import classify, gap_score, ratio
from app.services.my_account_service import number


@pytest.mark.parametrize('trend,own,expected', [(80,25,60),(100,0,100),(100,100,0),(0,50,0),
    (None,25,None),(80,None,None),(None,None,None),(50,'49.999999', '25.0000005')])
def test_gap_formula_without_competitor_or_renormalization(trend, own, expected):
    result = gap_score(Decimal(str(trend)) if trend is not None else None, Decimal(str(own)) if own is not None else None)
    assert result == (Decimal(str(expected)) if expected is not None else None)


@pytest.mark.parametrize('trend,own,expected', [
    ('50','49.999999','OPPORTUNITY'),('50','50','BALANCED'),('49.999999','50','HIGH_COVERAGE'),
    ('49.999999','49.999999','LOW_PRIORITY'),('100','0','OPPORTUNITY'),('0','100','HIGH_COVERAGE'),
    ('0','0','LOW_PRIORITY'),('100','100','BALANCED'),(None,'10',None),('80',None,None),(None,None,None)])
def test_classification_raw_decimal_boundaries(trend, own, expected):
    assert classify(Decimal(trend) if trend is not None else None, Decimal(own) if own is not None else None) == expected


@pytest.mark.parametrize('matched,total,expected', [(0,0,None),(0,10,0),(1,4,25),(1,3,33.3333),(10,10,100)])
def test_ratio_known_zero_missing_and_rounding(matched,total,expected):
    assert number(ratio(matched,total)) == expected
