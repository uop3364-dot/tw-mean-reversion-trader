import pandas as pd
from trader.data.status_provider import _period

def test_roc_disposition_period_parsing():
    start,end=_period("109/06/18至109/07/03")
    assert start==pd.Timestamp("2020-06-18")
    assert end==pd.Timestamp("2020-07-03")
