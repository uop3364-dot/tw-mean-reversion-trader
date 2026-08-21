from __future__ import annotations
import numpy as np
import pandas as pd

def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    prev = df.close.shift(1)
    tr = pd.concat([(df.high-df.low).abs(), (df.high-prev).abs(), (df.low-prev).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/period, adjust=False, min_periods=period).mean()

def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    d = close.diff(); up = d.clip(lower=0); down = -d.clip(upper=0)
    au = up.ewm(alpha=1/period, adjust=False, min_periods=period).mean()
    ad = down.ewm(alpha=1/period, adjust=False, min_periods=period).mean()
    out = 100 - 100/(1 + au/ad.replace(0, np.nan))
    return out.where(ad.ne(0), 100).fillna(50)

def bollinger(close: pd.Series, period: int = 20, std: float = 2) -> pd.DataFrame:
    mid=close.rolling(period).mean(); s=close.rolling(period).std(ddof=0)
    return pd.DataFrame({"lower":mid-std*s,"middle":mid,"upper":mid+std*s})

def efficiency_ratio(close: pd.Series, period: int = 60) -> pd.Series:
    movement=close.diff(period).abs(); path=close.diff().abs().rolling(period).sum()
    return (movement/path.replace(0,np.nan)).fillna(0)

def direction_changes(close: pd.Series, lookback: int = 60) -> pd.Series:
    slope=close.ewm(span=3,adjust=False).mean().diff(); sign=np.sign(slope).replace(0,np.nan).ffill()
    return sign.ne(sign.shift()).rolling(lookback).sum().fillna(0)

def zigzag_count(close: pd.Series, threshold: float = .05, lookback: int = 60) -> pd.Series:
    # Causal one-pass ZigZag: a reversal is recorded only on the day price has
    # actually moved `threshold` away from the running extreme. No future pivot
    # is back-painted onto an earlier high/low.
    a=close.to_numpy(float);turn=np.zeros(len(a));direction=0
    if not len(a):return pd.Series(turn,index=close.index)
    pivot=extreme=a[0]
    for i,x in enumerate(a[1:],1):
        if not np.isfinite(x):continue
        if direction==0:
            if x>=pivot*(1+threshold):direction=1;extreme=x
            elif x<=pivot*(1-threshold):direction=-1;extreme=x
        elif direction>0:
            extreme=max(extreme,x)
            if x<=extreme*(1-threshold):turn[i]=1;direction=-1;extreme=x
        else:
            extreme=min(extreme,x)
            if x>=extreme*(1+threshold):turn[i]=1;direction=1;extreme=x
    return pd.Series(turn,index=close.index).rolling(lookback,min_periods=lookback).sum()
