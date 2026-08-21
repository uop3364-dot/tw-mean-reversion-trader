from trader.backtest.engine import BacktestEngine
def test_backtest_deterministic(prices,cfg):
    cfg["strategy"]["mean_reversion"]["minimum_historical_events"]=1;cfg["strategy"]["mean_reversion"]["minimum_probability"]=0;cfg["strategy"]["ranking"]["minimum_final_score"]=0;cfg["strategy"]["low_zone"]["minimum_score"]=0
    a=BacktestEngine({"TEST":prices},cfg).run();b=BacktestEngine({"TEST":prices},cfg).run();assert a["equity"].equals(b["equity"]);assert a["trades"].equals(b["trades"])

