from __future__ import annotations

import os
from pathlib import Path
import pandas as pd


class ShioajiResearchClient:
    """Authenticated market-data client with no order-placement surface."""

    def __init__(self):
        import shioaji as sj
        self.sj=sj;self.api=sj.Shioaji();self.logged_in=False

    def login(self):
        key=os.getenv("SHIOAJI_API_KEY","").strip();secret=os.getenv("SHIOAJI_SECRET_KEY","").strip()
        if not key or not secret:raise RuntimeError("SHIOAJI_API_KEY and SHIOAJI_SECRET_KEY are required")
        self.api.login(api_key=key,secret_key=secret);self.logged_in=True;return self

    def close(self):
        if self.logged_in:
            try:self.api.logout()
            finally:self.logged_in=False

    def stock_snapshot(self,symbols):
        rows=[]
        for symbol in symbols:
            contract=self.api.contracts.get(str(symbol))
            if contract is None:continue
            info=self.api.contracts.info(contract)
            rows.append({
                "symbol":str(symbol),"security_type":str(getattr(info,"security_type","")),
                "exchange":str(getattr(info,"exchange","")),"name":getattr(info,"name",None),
                "category":getattr(info,"category",None),"unit":getattr(info,"unit",None),
                "trading_suspended":bool(getattr(info,"trading_suspended",False)),
                "disposition_level":getattr(info,"disposition_level",None),
                "attention_flag":bool(getattr(info,"attention_flag",False)),
                "settlement_type":getattr(info,"settlement_type",None),
                "reference":getattr(info,"reference",None),"update_date":getattr(info,"update_date",None),
                "source":"Shioaji authenticated contract info","retrieved_at":pd.Timestamp.now(),
            })
        return pd.DataFrame(rows)

    def kbars(self,symbol,start,end=None):
        contract=self.api.contracts.get(str(symbol))
        if contract is None:return pd.DataFrame()
        result=self.api.kbars(contract,start=start,end=end or pd.Timestamp.today().strftime("%Y-%m-%d"))
        if hasattr(result,"model_dump"):payload=result.model_dump()
        elif hasattr(result,"dict"):payload=result.dict()
        elif hasattr(result,"to_dict"):payload=result.to_dict()
        else:payload=result
        raw=pd.DataFrame(payload)
        if raw.empty:return raw
        raw=raw.rename(columns=str.lower).rename(columns={"ts":"date","amount":"turnover"})
        raw["date"]=pd.to_datetime(raw.date)
        if getattr(raw.date.dt,"tz",None) is not None:raw["date"]=raw.date.dt.tz_localize(None)
        raw["date"]=raw.date.dt.normalize()
        aggregations={"open":"first","high":"max","low":"min","close":"last","volume":"sum"}
        if "turnover" in raw.columns:aggregations["turnover"]="sum"
        return raw.groupby("date",as_index=False).agg(aggregations)


def compare_bars(reference,broker):
    if reference.empty or broker.empty:return pd.DataFrame()
    a=reference.copy();b=broker.copy();a["date"]=pd.to_datetime(a.date).dt.normalize();b["date"]=pd.to_datetime(b.date).dt.normalize()
    d=a.merge(b,on="date",suffixes=("_research","_shioaji"))
    for col in ("open","high","low","close","volume"):
        d[f"{col}_relative_diff"]=(d[f"{col}_research"]-d[f"{col}_shioaji"]).abs()/d[f"{col}_shioaji"].replace(0,float("nan"))
    return d
