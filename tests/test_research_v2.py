from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from trader.data.calendar import TradingCalendar
from trader.data.point_in_time import PointInTimeUniverse
from trader.data.corporate_actions import CorporateActionAdjuster
from trader.indicators.swings import causal_confirmed_swings,swing_structure
from trader.strategy.features import add_features
from trader.strategy.mean_reversion import historical_event_stats,expanding_probability
from trader.strategy.mean_reversion import _simulate_path
from trader.execution.taiwan_rules import TaiwanTickRule
from trader.backtest.fill_model import buy_fill,sell_fill

FIX=Path(__file__).parent/"fixtures"/"synthetic_market"

def _universe():
    u=pd.read_csv(FIX/"universe.csv");u[["listing_date","delisting_date"]]=u[["listing_date","delisting_date"]].apply(pd.to_datetime);return PointInTimeUniverse(u)

def test_no_future_universe():
    assert "HEALTHY" not in _universe().symbols_on("2019-12-31")
def test_delisted_stock_inclusion():
    assert "DELIST" in _universe().symbols_on("2024-01-03")
def test_listing_date_respected():
    assert not _universe().is_listed("HEALTHY","2019-12-31")
def test_delisting_date_respected():
    assert not _universe().is_listed("DELIST","2024-01-04")
def test_status_point_in_time():
    u=pd.read_csv(FIX/"universe.csv");u[["listing_date","delisting_date"]]=u[["listing_date","delisting_date"]].apply(pd.to_datetime);a=pd.DataFrame([{"date":"2024-01-02","symbol":"HEALTHY","status":"SUSPENDED"}]);pit=PointInTimeUniverse(u,a);assert not pit.is_tradable("HEALTHY","2024-01-02") and pit.is_tradable("HEALTHY","2024-01-03")
def test_corporate_action_consistency():
    actions=pd.read_csv(FIX/"corporate_actions.csv");bars=pd.DataFrame({"date":pd.to_datetime(["2024-01-02","2024-01-03"]),"open":[100,50],"high":[102,51],"low":[98,49],"close":[100,50],"volume":[1000,2000]});x=CorporateActionAdjuster(actions).adjust("HEALTHY",bars);assert x.adjusted_close.tolist()==[50.,50.] and x.close.tolist()==[100,50]
def test_no_adjusted_unadjusted_mix():
    assert set(pd.read_csv(FIX/"corporate_actions.csv").event_type)=={"split"}
def test_calendar_integrity():
    c=TradingCalendar(pd.to_datetime(["2024-01-02","2024-01-04","2024-01-05"]));assert c.next_session("2024-01-02",2)==pd.Timestamp("2024-01-05")
def test_zigzag_has_no_future_dependency():
    x=pd.Series([100,106,99,107,100,108,101.]);a=causal_confirmed_swings(x,.05);y=x.copy();y.iloc[-1]=500;b=causal_confirmed_swings(y,.05);pd.testing.assert_frame_equal(a[a.confirm_i<6].reset_index(drop=True),b[b.confirm_i<6].reset_index(drop=True))
def test_causal_swing_detection():
    p=causal_confirmed_swings(pd.Series([100,110,104]),.05);assert p.iloc[0].confirm_i==2 and p.iloc[0].pivot_i==1
def test_lower_low_from_swings():
    p=pd.DataFrame({"confirm_i":[1,2,3,4,5,6],"kind":["HIGH","LOW"]*3,"price":[120,100,114,94,108,88]});assert swing_structure(p,6,20).lower_low_count==2
def test_lower_high_from_swings():
    p=pd.DataFrame({"confirm_i":[1,2,3,4,5,6],"kind":["HIGH","LOW"]*3,"price":[120,100,114,94,108,88]});assert swing_structure(p,6,20).lower_high_count==2
def test_atr_score_penalizes_extreme_volatility(prices,cfg):
    base=add_features(prices,cfg);wild=prices.copy();wild.loc[250:,"high"]=wild.loc[250:].close*1.2;wild.loc[250:,"low"]=wild.loc[250:].close*.8;x=add_features(wild,cfg);assert x.iloc[-1].oscillation_score<base.iloc[-1].oscillation_score
def test_low_score_not_reward_extreme_crash(prices,cfg):
    mild=prices.copy();crash=prices.copy();mild.loc[299,["open","high","low","close"]]=mild.loc[299,"close"]*.9;crash.loc[299,["open","high","low","close"]]=crash.loc[299,"close"]*.5;assert add_features(crash,cfg).iloc[-1].low_score<=add_features(mild,cfg).iloc[-1].low_score
def test_historical_event_next_open_entry(cfg):
    d=pd.DataFrame({"open":[100,110,110],"high":[101,112,112],"low":[99,108,108],"close":[100,110,110],"oscillation_score":[90,0,0],"low_score":[90,0,0],"price_position":[.1,1,1]});e=historical_event_stats(d,cfg);assert e.iloc[0].entry==pytest.approx(110*1.001)
def test_tp_days_are_actual(cfg):
    n=10;d=pd.DataFrame({"open":[100]*n,"high":[100,100,100,100,106,106,106,106,106,106],"low":[99]*n,"close":[100]*n,"oscillation_score":[90]+[0]*(n-1),"low_score":[90]+[0]*(n-1),"price_position":[.1]+[1]*(n-1)});e=historical_event_stats(d,cfg);assert e.iloc[0].tp5_day==4
def test_failed_event_uses_real_exit_not_mfe(cfg):
    d=pd.DataFrame({"open":[100]*5,"high":[100,104,104,104,104],"low":[99]*5,"close":[100,90,90,90,90],"oscillation_score":[90,0,0,0,0],"low_score":[90,0,0,0,0],"price_position":[.1,1,1,1,1]});e=historical_event_stats(d,cfg);assert e.iloc[0].tp5_net_return<0 and e.iloc[0].tp5_mfe>0
def test_mr_probability_reveal_timing(prices,cfg):
    f=add_features(prices,cfg);x=expanding_probability(f,cfg);assert (x.iloc[:41].historical_events==0).all()
def test_tick_rounding():
    assert TaiwanTickRule.round_up(73.02)==73.1 and TaiwanTickRule.round_down(73.08)==73.0
def test_limit_price_handling():
    row=pd.Series({"open":110.,"high":110.,"low":110.,"volume":1000});assert buy_fill(110,.001,row,100,100,1) is None
def test_tp_intraday_same_day_allowed():
    assert sell_fill(100,111,110,.001) is not None
def test_thesis_break_executes_next_session(cfg):
    d=pd.DataFrame({"open":[100,100,90,80],"high":[100,101,91,81],"low":[99,89,79,79],"close":[100,90,80,80],"thesis_break_score":[0,95,95,95],"oscillation_score":[90]*4,"regime_risk_score":[0,90,90,90],"structure_direction":["RANGE"]*4,"rs60":[0]*4});r=_simulate_path(d,0,.20,cfg);assert r["exit_reason"]=="THESIS_BREAK" and r["holding_days"]==2
def test_time_exit_no_same_day_open_lookahead(cfg):
    cfg["strategy"]["holding"]["max_days"]=2;cfg["strategy"]["holding"]["absolute_max_days"]=3;d=pd.DataFrame({"open":[100]*5,"high":[101]*5,"low":[99]*5,"close":[100]*5,"thesis_break_score":[0]*5,"oscillation_score":[0]*5,"regime_risk_score":[0]*5,"structure_direction":["RANGE"]*5,"rs60":[0]*5});r=_simulate_path(d,0,.20,cfg);assert r["exit_reason"]=="TIME_EXIT" and r["holding_days"]==3
def test_no_signal_day_execution(cfg):
    d=pd.DataFrame({"open":[100,123],"high":[101,124],"low":[99,122],"close":[100,123],"oscillation_score":[90,0],"low_score":[90,0],"price_position":[.1,1]});assert historical_event_stats(d,cfg).iloc[0].entry==pytest.approx(123*1.001)
