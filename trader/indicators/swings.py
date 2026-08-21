from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import pandas as pd

def causal_confirmed_swings(close:pd.Series,threshold:float=.05)->pd.DataFrame:
    """Emit a pivot only on its confirmation bar; never back-paint."""
    a=close.to_numpy(float);rows=[];direction=0;extreme=np.nan;extreme_i=-1
    for i,x in enumerate(a):
        if not np.isfinite(x):continue
        if not np.isfinite(extreme):extreme=x;extreme_i=i;continue
        if direction==0:
            if x>=extreme*(1+threshold):direction=1;extreme=x;extreme_i=i
            elif x<=extreme*(1-threshold):direction=-1;extreme=x;extreme_i=i
            elif x>extreme:extreme=x;extreme_i=i
            elif x<extreme:extreme=x;extreme_i=i
        elif direction>0:
            if x>extreme:extreme=x;extreme_i=i
            elif x<=extreme*(1-threshold):rows.append({"confirm_i":i,"pivot_i":extreme_i,"kind":"HIGH","price":extreme});direction=-1;extreme=x;extreme_i=i
        else:
            if x<extreme:extreme=x;extreme_i=i
            elif x>=extreme*(1+threshold):rows.append({"confirm_i":i,"pivot_i":extreme_i,"kind":"LOW","price":extreme});direction=1;extreme=x;extreme_i=i
    return pd.DataFrame(rows,columns=["confirm_i","pivot_i","kind","price"])

@dataclass(frozen=True)
class SwingStructure:
    higher_high_count:int=0;higher_low_count:int=0;lower_high_count:int=0;lower_low_count:int=0;structure_direction:str="NEUTRAL"

def swing_structure(points:pd.DataFrame,asof_i:int,lookback:int=20)->SwingStructure:
    p=points[(points.confirm_i<=asof_i)&(points.confirm_i>asof_i-lookback)]
    highs=p[p.kind=="HIGH"].price.to_numpy();lows=p[p.kind=="LOW"].price.to_numpy()
    hh=int((np.diff(highs)>0).sum());lh=int((np.diff(highs)<0).sum());hl=int((np.diff(lows)>0).sum());ll=int((np.diff(lows)<0).sum())
    direction="BEARISH" if lh>=2 and ll>=2 else "BULLISH" if hh>=2 and hl>=2 else "RANGE"
    return SwingStructure(hh,hl,lh,ll,direction)

def rolling_swing_features(close:pd.Series,threshold=.05,lookback=60)->pd.DataFrame:
    pts=causal_confirmed_swings(close,threshold);out=[]
    for i in range(len(close)):
        s=swing_structure(pts,i,lookback);recent=pts[(pts.confirm_i<=i)&(pts.confirm_i>i-lookback)];amps=recent.price.pct_change().abs().dropna()
        out.append({"effective_swing_count":len(recent),"median_swing_amplitude":amps.median() if len(amps) else 0.,"swing_amplitude_consistency":max(0.,1-(amps.std()/amps.mean())) if len(amps)>1 and amps.mean() else 0.,"higher_high_count":s.higher_high_count,"higher_low_count":s.higher_low_count,"lower_high_count":s.lower_high_count,"lower_low_count":s.lower_low_count,"structure_direction":s.structure_direction})
    return pd.DataFrame(out,index=close.index)
