from __future__ import annotations
import pandas as pd
def quality_manifest(universe,repository,start="2018-01-01",calendar=None):
    rows=[];expected=None
    for _,u in universe.iterrows():
        try:d=repository.load(u.symbol);d=d[d.date>=pd.Timestamp(start)].sort_values("date")
        except Exception:d=pd.DataFrame()
        if not d.empty:
            dup=int(d.date.duplicated().sum());bad=int(((d[["open","high","low","close"]]<=0).any(axis=1)|(d.high<d.low)|(d.high<d[["open","close"]].max(axis=1))|(d.low>d[["open","close"]].min(axis=1))|(d.volume<0)).sum());missing=float(d[["open","high","low","close","volume"]].isna().mean().max())
            active_calendar=pd.DatetimeIndex(calendar) if calendar is not None else pd.bdate_range(d.date.min(),d.date.max())
            active_calendar=active_calendar[(active_calendar>=d.date.min())&(active_calendar<=d.date.max())];missing_days=1-d.date.nunique()/len(active_calendar) if len(active_calendar) else 1
            rows.append({"symbol":u.symbol,"exchange":u.exchange,"rows":len(d),"first_date":d.date.min(),"last_date":d.date.max(),"duplicate_dates":dup,"invalid_ohlcv_rows":bad,"max_field_missing_ratio":missing,"missing_trading_day_ratio":missing_days,"has_120_days":len(d)>=120,"downloaded":True})
        else:rows.append({"symbol":u.symbol,"exchange":u.exchange,"rows":0,"first_date":pd.NaT,"last_date":pd.NaT,"duplicate_dates":0,"invalid_ohlcv_rows":0,"max_field_missing_ratio":1.0,"missing_trading_day_ratio":1.0,"has_120_days":False,"downloaded":False})
    return pd.DataFrame(rows)
