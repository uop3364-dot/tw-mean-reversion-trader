from trader.strategy.features import add_features
from trader.strategy.mean_reversion import expanding_probability,historical_event_stats
def test_features_do_not_change_when_future_changes(prices,cfg):
    a=add_features(prices,cfg);changed=prices.copy();changed.loc[200:,"close"]*=5;b=add_features(changed,cfg)
    assert a.loc[:199,"oscillation_score"].equals(b.loc[:199,"oscillation_score"])
def test_event_result_not_revealed_early(prices,cfg):
    cfg["strategy"]["oscillation"]["minimum_score"]=0;cfg["strategy"]["low_zone"]["max_price_position"]=1
    d=expanding_probability(add_features(prices,cfg),cfg);first=d.index[d.historical_events>0]
    assert len(first)==0 or first[0]>=cfg["strategy"]["mean_reversion"]["horizon_days"]
def test_historical_event_uses_next_open_and_slippage(cfg):
    import pandas as pd
    d=pd.DataFrame({"open":[100.,200.,200.],"high":[101.,209.,209.],"low":[99.,190.,190.],"close":[100.,200.,200.],"oscillation_score":[100.,0.,0.],"price_position":[0.,1.,1.]})
    events=historical_event_stats(d,cfg)
    assert len(events)==1
    assert events.iloc[0].entry==200*(1+cfg["strategy"]["execution"]["buy_slippage"])
    assert not bool(events.iloc[0].P_5_20)
