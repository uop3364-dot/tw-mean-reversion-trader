import numpy as np
from trader.indicators import atr,rsi,efficiency_ratio,zigzag_count,direction_changes
def test_indicator_ranges(prices):
    assert (atr(prices).dropna()>0).all();assert rsi(prices.close).between(0,100).all();assert efficiency_ratio(prices.close).between(0,1).all()
def test_oscillation_detection(prices):
    assert zigzag_count(prices.close,.05,60).iloc[-1]>=4;assert direction_changes(prices.close,60).iloc[-1]>=5
