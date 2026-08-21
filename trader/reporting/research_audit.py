from __future__ import annotations
from pathlib import Path
import pandas as pd
from trader.strategy.signal_engine import build_signals

PASS_COLUMNS=["pass_history","pass_data_quality","pass_liquidity","pass_oscillation","pass_low_zone","pass_mr_sample","pass_mr_probability","pass_regime","pass_ranking"]

def build_research_audit(data,cfg,out_dir,status=None,start="2019-01-01"):
    out=Path(out_dir);cache=out.parent/"data"/"feature_cache";cache.mkdir(parents=True,exist_ok=True);status=status or {"altered":set(),"dispositions":{}}
    latest=[];events=[];funnel={"INPUT_SYMBOL_DAYS":0};reject={};calendar=data.get("TAIEX",pd.DataFrame()).get("date",None)
    for symbol,raw in sorted(data.items()):
        if symbol in ("TAIEX","0050") or len(raw)<1:continue
        f=build_signals(raw,cfg,calendar);f["symbol"]=symbol
        blocked=[]
        for dt in f.date:
            b=(symbol,pd.Timestamp(dt)) in status.get("altered",set()) or any(a<=pd.Timestamp(dt)<=z for a,z in status.get("dispositions",{}).get(symbol,[]));blocked.append(not b)
        f["pass_official_status"]=blocked
        f.loc[~f.pass_official_status,"rejection_reason"]="OFFICIAL_STATUS"
        cols=PASS_COLUMNS[:-2]+["pass_official_status"]+PASS_COLUMNS[-2:]
        f["candidate"]=f[cols].all(axis=1)
        f.to_parquet(cache/f"{symbol}.parquet",index=False)
        window=f[f.date>=pd.Timestamp(start)];funnel["INPUT_SYMBOL_DAYS"]+=len(window);mask=pd.Series(True,index=window.index)
        for col in cols:
            mask &= window[col].fillna(False);funnel[col]=funnel.get(col,0)+int(mask.sum())
        for reason,count in window.loc[~window.candidate,"rejection_reason"].value_counts().items():reject[reason]=reject.get(reason,0)+int(count)
        if not f.empty:latest.append(f.iloc[-1][["date","symbol","close","oscillation_score","low_score","historical_events","mr_probability","regime_risk_score","final_score","candidate","rejection_reason"]].to_dict())
        accepted=window[window.candidate]
        if not accepted.empty:events.append(accepted[["date","symbol","close","oscillation_score","low_score","historical_events","mr_probability","regime_risk_score","final_score","take_profit"]])
    pd.DataFrame(latest).to_csv(out/"latest_symbol_audit.csv",index=False)
    (pd.concat(events,ignore_index=True) if events else pd.DataFrame(columns=["date","symbol","close","oscillation_score","low_score","historical_events","mr_probability","regime_risk_score","final_score","take_profit"])).to_csv(out/"eligible_signal_events.csv",index=False)
    pd.DataFrame([{"stage":k,"survivors":v} for k,v in funnel.items()]).to_csv(out/"filter_funnel.csv",index=False)
    pd.DataFrame([{"reason":k,"symbol_days":v} for k,v in sorted(reject.items())]).to_csv(out/"rejection_counts.csv",index=False)
    return funnel
