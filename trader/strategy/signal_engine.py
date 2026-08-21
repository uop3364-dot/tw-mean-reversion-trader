from __future__ import annotations
import pandas as pd
from .features import add_features
from .mean_reversion import expanding_probability, historical_event_stats, expanding_take_profit

def build_signals(df:pd.DataFrame,cfg:dict,calendar=None,market=None,symbol="UNKNOWN") -> pd.DataFrame:
    clean=df.copy();clean["date"]=pd.to_datetime(clean.date)
    if calendar is not None and not clean.empty:
        days=pd.DatetimeIndex(calendar);days=days[(days>=clean.date.min())&(days<=clean.date.max())]
        clean=clean.set_index("date").reindex(days).rename_axis("date").reset_index()
    clean.loc[(clean[["open","high","low","close"]]<=0).any(axis=1),["open","high","low","close"]]=float("nan")
    d=expanding_probability(add_features(clean,cfg,market),cfg,symbol); s=cfg["strategy"]; u=s["universe"]; o=s["oscillation"]; l=s["low_zone"]; m=s["mean_reversion"]; r=s["regime"]
    d["mean_reversion_score"]=(d.posterior_probability*100).fillna(0)
    d["final_score"]=.30*d.oscillation_score+.25*d.low_score+.30*d.mean_reversion_score+.15*(100-d.regime_risk_score)
    liquid=(d.close.between(u["minimum_price"],u["maximum_price"]))&(d.volume.rolling(20).mean()>=u["minimum_avg_daily_volume_shares_20d"])&((d.close*d.volume).rolling(20).mean()>=u["minimum_avg_daily_value_20d"])
    d["pass_history"]=d.close.notna().cumsum()>=u["minimum_history_days"]
    missing=d[["open","high","low","close","volume"]].isna().any(axis=1);invalid=(d[["open","high","low","close"]]<=0).any(axis=1)|(d.high<d.low)|(d.high<d[["open","close"]].max(axis=1))|(d.low>d[["open","close"]].min(axis=1))|(d.volume<0)
    d["pass_data_quality"]=(missing|invalid).rolling(u["minimum_history_days"],min_periods=1).mean()<=u["max_missing_data_ratio"]
    d["pass_liquidity"]=liquid;d["pass_oscillation"]=(d.oscillation_score>=o["minimum_score"]);d["pass_low_zone"]=(d.low_score>=l["minimum_score"])&(d.price_position<=l["max_price_position"])&(d.price_percentile<=l["max_price_percentile"])
    d["pass_mr_sample"]=d.historical_events>=m["minimum_historical_events"];d["pass_mr_probability"]=d.mr_probability>=m["minimum_probability"];d["pass_regime"]=d.regime_risk_score<=r["maximum_buy_risk_score"];d["pass_ranking"]=d.final_score>=s["ranking"]["minimum_final_score"]
    passes=["pass_history","pass_data_quality","pass_liquidity","pass_oscillation","pass_low_zone","pass_mr_sample","pass_mr_probability","pass_regime","pass_ranking"]
    d["candidate"]=d[passes].all(axis=1)
    labels={"pass_history":"INSUFFICIENT_HISTORY","pass_data_quality":"DATA_QUALITY","pass_liquidity":"LIQUIDITY","pass_oscillation":"OSCILLATION","pass_low_zone":"LOW_ZONE","pass_mr_sample":"MR_SAMPLE","pass_mr_probability":"MR_PROBABILITY","pass_regime":"REGIME","pass_ranking":"RANKING"}
    d["rejection_reason"]="ACCEPT"
    for col in reversed(passes):d.loc[~d[col],"rejection_reason"]=labels[col]
    ev=historical_event_stats(d,cfg,symbol); d["take_profit"]=expanding_take_profit(d,ev,s["take_profit"]["candidates"],s["take_profit"]["fallback"],m["dynamic_tp_minimum_trades"])
    return d
