from __future__ import annotations
import copy,pandas as pd
from pathlib import Path
from .engine import BacktestEngine
from trader.strategy.signal_engine import build_signals
def sensitivity(data,cfg,start=None,end=None,status=None,baseline_prepared=None,checkpoint_path=None):
    # The matrix must use the same research interval as the formal baseline.
    # A missing CLI override means the configured baseline start, not the
    # earliest bootstrap observation (which is retained only for indicators).
    start=start or cfg["backtest"]["start_date"]
    checkpoint=Path(checkpoint_path) if checkpoint_path else None
    try:previous=pd.read_csv(checkpoint) if checkpoint and checkpoint.exists() and checkpoint.stat().st_size else pd.DataFrame()
    except pd.errors.EmptyDataError:previous=pd.DataFrame()
    rows=previous.to_dict("records") if not previous.empty else []
    done={(round(float(x["TP"]),4),round(float(x["LowPosition"]),4),round(float(x["MRProbability"]),4)) for x in rows}
    for low in [.10,.15,.20,.25,.30]:
      c=copy.deepcopy(cfg);c["strategy"]["low_zone"]["max_price_position"]=low
      calendar=data.get("TAIEX",pd.DataFrame()).get("date",None)
      if all((tp,low,prob) in done for prob in [.55,.60,.65,.70,.75] for tp in [.05,.08,.10,.12,.15,.20]):continue
      prepared=baseline_prepared if baseline_prepared is not None and low==cfg["strategy"]["low_zone"]["max_price_position"] else {k:build_signals(v,c,calendar).set_index("date") for k,v in data.items() if k not in ("TAIEX","0050") and len(v)>=120}
      for prob in [.55,.60,.65,.70,.75]:
        run_cfg=copy.deepcopy(c);run_cfg["strategy"]["mean_reversion"]["minimum_probability"]=prob
        engine=BacktestEngine(data,run_cfg,prepared=prepared,status=status)
        for tp in [.05,.08,.10,.12,.15,.20]:
          if (tp,low,prob) in done:continue
          r=engine.run(start,end,tp);m=r["metrics"]
          rows.append({"TP":tp,"LowPosition":low,"MRProbability":prob,"Return":m.get("Total Return",0),"CAGR":m.get("CAGR",0),"Max Drawdown":m.get("Max Drawdown",0),"Sharpe":m.get("Sharpe Ratio",0),"Win Rate":m.get("Win Rate",0),"Profit Factor":m.get("Profit Factor",0),"Average Holding":m.get("Average Holding Days",0),"Capital Utilization":m.get("Capital Utilization",0),"Trade Count":len(r["trades"])})
          done.add((tp,low,prob))
          if checkpoint:pd.DataFrame(rows).sort_values(["LowPosition","MRProbability","TP"]).to_csv(checkpoint,index=False)
    return pd.DataFrame(rows).sort_values(["LowPosition","MRProbability","TP"]).reset_index(drop=True)
