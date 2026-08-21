from trader.strategy.features import add_features
from trader.strategy.signal_engine import build_signals
def test_scores_are_bounded(prices,cfg):
    d=add_features(prices,cfg);assert d.oscillation_score.dropna().between(0,100).all();assert d.low_score.dropna().between(0,100).all();assert d.regime_risk_score.between(0,100).all()
def test_signal_schema(prices,cfg):
    d=build_signals(prices,cfg);assert {"candidate","final_score","mr_probability","take_profit"}<=set(d.columns)

