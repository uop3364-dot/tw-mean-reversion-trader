from __future__ import annotations
import numpy as np
import pandas as pd
from trader.indicators import atr,rsi,bollinger,efficiency_ratio,direction_changes
from trader.indicators.swings import rolling_swing_features

def triangular_score(x,left,ideal_low,ideal_high,right):
    x=pd.Series(x);up=((x-left)/(ideal_low-left)*100).clip(0,100);down=((right-x)/(right-ideal_high)*100).clip(0,100)
    return pd.Series(np.where(x<ideal_low,up,np.where(x<=ideal_high,100,down)),index=x.index).where((x>left)&(x<right),0.)

def add_features(df:pd.DataFrame,cfg:dict,market:pd.DataFrame|None=None)->pd.DataFrame:
    d=df.sort_values("date").copy();o=cfg["strategy"]["oscillation"];l=cfg["strategy"]["low_zone"]
    d["atr_pct"]=atr(d,o["atr_period"])/d.close;sw=rolling_swing_features(d.close,o["zigzag_threshold"],o["lookback_days"]);d=d.join(sw)
    d["swings"]=d.effective_swing_count;d["direction_changes"]=direction_changes(d.close,o["lookback_days"])
    for n in (20,40,60):d[f"er{n}"]=efficiency_ratio(d.close,n)
    atr_score=triangular_score(d.atr_pct,o["minimum_atr_pct"],o["ideal_atr_low_pct"],o["ideal_atr_high_pct"],o["maximum_atr_pct"])
    swing_score=(d.effective_swing_count/o["minimum_swings"]*100).clip(0,100);dir_score=(d.direction_changes/o["minimum_direction_changes"]*100).clip(0,100);eff_score=(100*(1-(.2*d.er20+.3*d.er40+.5*d.er60)/o["maximum_efficiency_ratio"])).clip(0,100)
    ma20=d.close.rolling(20).mean();cross=np.sign(d.close-ma20).replace(0,np.nan).ffill().ne(np.sign(d.close-ma20).replace(0,np.nan).ffill().shift()).rolling(60).sum();cross_score=(cross/8*100).clip(0,100)
    roll_low=d.close.rolling(60).min();roll_high=d.close.rolling(60).max();width=(roll_high-roll_low)/d.close;drift=(d.close-d.close.shift(60)).abs()/(roll_high-roll_low).replace(0,np.nan);range_persistence=(100*(1-drift)).clip(0,100).where(width>.08,0)
    d["ma20_crossing_count"]=cross;d["range_persistence_score"]=range_persistence.fillna(0)
    consistency=(d.swing_amplitude_consistency*100).clip(0,100)
    d["oscillation_score"]=(.18*atr_score+.22*swing_score+.15*dir_score+.18*eff_score+.12*d.range_persistence_score+.08*cross_score+.07*consistency)
    n=l["lookback_days"];lo=d.close.rolling(n).min();hi=d.close.rolling(n).max();d["price_position"]=(d.close-lo)/(hi-lo).replace(0,np.nan);d["price_percentile"]=d.close.rolling(n).rank(pct=True);d["rsi14"]=rsi(d.close,l["rsi_period"]);bb=bollinger(d.close,l["bollinger_period"],l["bollinger_std"]);d["bb_position"]=(d.close-bb.lower)/(bb.upper-bb.lower).replace(0,np.nan)
    pp=triangular_score(d.price_position,0,.05,.20,.35);pct=triangular_score(d.price_percentile,0,.05,.25,.40);rs=triangular_score(d.rsi14,15,25,40,50);bs=triangular_score(d.bb_position,-.6,-.2,.25,.45)
    d["extreme_crash_penalty"]=(100-triangular_score(d.price_position,-.01,.04,1,2)).clip(0,100)*.35+(100-triangular_score(d.rsi14,10,22,100,200)).clip(0,100)*.25
    d["low_score"]=(.40*pp+.25*pct+.20*rs+.15*bs-d.extreme_crash_penalty).clip(0,100)
    d["ma20"]=ma20;d["ma60"]=d.close.rolling(60).mean();d["ma120"]=d.close.rolling(120).mean()
    for n in (20,60):d[f"return{n}"]=d.close.pct_change(n);d[f"ma{n}_slope20"]=d[f"ma{n}"]/d[f"ma{n}"].shift(20)-1
    volavg=d.volume.rolling(20).mean();daily_range=(d.high-d.low)/d.close;gap=(d.open/d.close.shift()-1);new20=d.low<=d.low.rolling(20).min();new60=d.low<=d.low.rolling(60).min();near_low=(d.close-d.low)/(d.high-d.low).replace(0,np.nan)<.2;range_expand=daily_range>daily_range.rolling(60).median()*2
    d["abnormal_breakdown_score"]=(new20*15+new60*20+(d.volume>2*volavg)*20+near_low*15+(gap<-.04)*15+range_expand*15).astype(float)
    d["atr_regime_shift"]=d.atr_pct/d.atr_pct.rolling(60).median();d["rolling_drawdown60"]=d.close/d.close.rolling(60).max()-1
    if market is not None and not market.empty:
        m=market.copy();m["date"]=pd.to_datetime(m.date);mc=m.set_index("date").close.reindex(pd.to_datetime(d.date)).reset_index(drop=True)
        d["rs20"]=d.return20-mc.pct_change(20);d["rs60"]=d.return60-mc.pct_change(60)
    else:d["rs20"]=0.;d["rs60"]=0.
    bearish=(d.structure_direction=="BEARISH").astype(float);ma_risk=((d.close<d.ma60)&(d.ma20<d.ma60)).astype(float);trend_er=((d.er60-.35)/.35*100).clip(0,100);weak=(-d.rs60/.25*100).clip(0,100);atrshift=((d.atr_regime_shift-1)/1.5*100).clip(0,100);dd=(-d.rolling_drawdown60/.35*100).clip(0,100)
    d["regime_risk_score"]=(.20*d.abnormal_breakdown_score+.18*bearish*100+.15*ma_risk*100+.12*trend_er+.12*weak+.10*atrshift+.13*dd).clip(0,100).fillna(0)
    d["thesis_break_score"]=(.30*d.regime_risk_score+.20*bearish*100+.20*weak+.15*d.abnormal_breakdown_score+.15*atrshift).clip(0,100).fillna(0)
    d["avg_volume_20"]=volavg;d["avg_value_20"]=(d.close*d.volume).rolling(20).mean();return d
