from __future__ import annotations
import numpy as np
import pandas as pd
from trader.indicators import atr,rsi,bollinger,efficiency_ratio,direction_changes,zigzag_count

def _clip_score(x, lo, hi, inverse=False):
    z=((x-lo)/(hi-lo)*100).clip(0,100)
    return 100-z if inverse else z

def add_features(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    d=df.sort_values("date").copy(); o=cfg["strategy"]["oscillation"]; l=cfg["strategy"]["low_zone"]
    d["atr_pct"]=atr(d,o["atr_period"])/d.close
    d["swings"]=zigzag_count(d.close,o["zigzag_threshold"],o["lookback_days"])
    d["direction_changes"]=direction_changes(d.close,o["lookback_days"])
    d["er60"]=efficiency_ratio(d.close,o["efficiency_ratio_period"])
    atr_score=_clip_score(d.atr_pct,o["minimum_atr_pct"],o["ideal_atr_pct"])
    swing_score=_clip_score(d.swings,0,max(o["minimum_swings"],1))
    dir_score=_clip_score(d.direction_changes,0,max(o["minimum_direction_changes"],1))
    eff_score=_clip_score(d.er60,0,o["maximum_efficiency_ratio"],inverse=True)
    d["oscillation_score"]=.25*atr_score+.30*swing_score+.20*dir_score+.25*eff_score
    n=l["lookback_days"]; low=d.close.rolling(n).min(); high=d.close.rolling(n).max()
    d["price_position"]=(d.close-low)/(high-low).replace(0,np.nan)
    d["price_percentile"]=d.close.rolling(n).rank(pct=True)
    d["rsi14"]=rsi(d.close,l["rsi_period"]); bb=bollinger(d.close,l["bollinger_period"],l["bollinger_std"])
    d["bb_position"]=(d.close-bb.lower)/(bb.upper-bb.lower).replace(0,np.nan)
    pp=(100*(1-d.price_position/l["max_price_position"])).clip(0,100)
    pct=(100*(1-d.price_percentile/l["max_price_percentile"])).clip(0,100)
    rs=(100*(l["rsi_maximum"]-d.rsi14)/(l["rsi_maximum"]-l["rsi_minimum"])).clip(0,100)
    bs=(100*(1-d.bb_position/l["bollinger_max_position"])).clip(0,100)
    d["low_score"]=.40*pp+.25*pct+.20*rs+.15*bs
    d["ma20"]=d.close.rolling(20).mean(); d["ma60"]=d.close.rolling(60).mean()
    slope=d.ma60/d.ma60.shift(20)-1; ret60=d.close/d.close.shift(60)-1
    cond_a=(d.close<d.ma60)&(d.ma20<d.ma60)&(slope<-.03)
    newlow=d.low<=d.low.rolling(20).min(); nearlow=d.close<=d.low+.2*(d.high-d.low)
    cond_b=newlow&(d.volume>d.volume.rolling(20).mean()*2)&nearlow
    cond_c=(d.er60>.50)&(ret60<-.15)
    lower_lows=(d.low.diff()<0).rolling(20).sum()>=3; lower_highs=(d.high.diff()<0).rolling(20).sum()>=3
    cond_d=lower_lows&lower_highs
    d["regime_risk_score"]=(cond_a*30+cond_b*35+cond_c*35+cond_d*20).clip(0,100).astype(float)
    d["avg_volume_20"]=d.volume.rolling(20).mean();d["avg_value_20"]=(d.close*d.volume).rolling(20).mean()
    return d
