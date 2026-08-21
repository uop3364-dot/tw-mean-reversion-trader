from __future__ import annotations
import pandas as pd
from .engine import BacktestEngine
from trader.strategy.signal_engine import build_signals
def walk_forward(data,cfg,start="2019-01-01",end=None,status=None,prepared=None):
    begin=pd.Timestamp(start); final=pd.Timestamp(end or max(d.date.max() for d in data.values())); rows=[]; test=begin+pd.DateOffset(years=3)
    calendar=data.get("TAIEX",pd.DataFrame()).get("date",None);prepared=prepared or {k:build_signals(v,cfg,calendar).set_index("date") for k,v in data.items() if k not in ("TAIEX","0050") and len(v)>=120}
    while test<final:
        test_end=min(test+pd.DateOffset(months=6)-pd.Timedelta(days=1),final)
        # Parameter selection is confined to the trailing 3-year training window.
        train_start=test-pd.DateOffset(years=3); best=(-1,.10)
        engine=BacktestEngine(data,cfg,prepared=prepared,status=status)
        for tp in cfg["strategy"]["take_profit"]["candidates"]:
            r=engine.run(train_start,test-pd.Timedelta(days=1),tp,liquidate_at_end=True);score=r["metrics"].get("CAGR",-1)
            if score>best[0]:best=(score,tp)
        out=engine.run(test,test_end,best[1],liquidate_at_end=True);rows.append({"train_start":train_start,"test_start":test,"test_end":test_end,"selected_tp":best[1],"trades":len(out["trades"]),**out["metrics"]});test=test+pd.DateOffset(months=6)
    return pd.DataFrame(rows)
