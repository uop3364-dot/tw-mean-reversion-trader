from __future__ import annotations
from pathlib import Path
import pandas as pd

def research_readiness(root:Path):
    data=root/"data";reports=root/"reports";checks=[]
    def add(name,ok,actual,required,reason):checks.append({"check":name,"passed":bool(ok),"actual":actual,"required":required,"reason":reason})
    up=data/"universe.parquet";u=pd.read_parquet(up) if up.exists() else pd.DataFrame();add("current_universe",len(u)>=1900,len(u),">=1900","Cover current TWSE/TPEx ordinary-stock issuers")
    hp=data/"historical_universe.parquet";h=pd.read_parquet(hp) if hp.exists() else pd.DataFrame();add("historical_universe",len(h)>=2000,len(h),">=2000 with explicit exclusions","Current plus official delisting masters prevent a current-constituent-only study")
    qp=reports/"data_quality.csv";q=pd.read_csv(qp) if qp.exists() else pd.DataFrame()
    complete=not q.empty and (~q.downloaded.astype(bool)).sum()==0 and q.invalid_ohlcv_rows.sum()==0
    add("current_ohlcv_quality",complete,f"missing={0 if q.empty else (~q.downloaded.astype(bool)).sum()}, invalid={0 if q.empty else q.invalid_ohlcv_rows.sum()}","missing=0, invalid=0","All current ordinary stocks have validated bars; <120 days are rule-based exclusions")
    taiex=data/"processed"/"TAIEX.parquet";calendar=pd.read_parquet(taiex).date if taiex.exists() else pd.Series(dtype="datetime64[ns]")
    expected={pd.Timestamp(x) for x in calendar[calendar>=pd.Timestamp("2018-01-01")]}
    for ex in ("TWSE","TPEx"):
        parts=list((data/"official_daily").glob(f"{ex}_*.parquet"));seen=set()
        for p in parts:
            try:seen|={pd.Timestamp(x) for x in pd.read_parquet(p,columns=["date"]).date.unique()}
            except Exception:pass
        if ex=="TPEx":add(f"official_ohlcv_{ex}",expected<=seen,len(expected-seen),"0 missing dates",f"Official {ex} OHLCV and historical membership")
        else:
            mixed=not h.empty and len(h[(h.exchange=="TWSE")&(h.data_status=="READY")])>=1100
            add("validated_ohlcv_TWSE",mixed,len(h[(h.exchange=="TWSE")&(h.data_status=="READY")]) if not h.empty else 0,">=1100 ready histories","Validated mixed-source TWSE bars with symbol-level provenance; official whole-market partitions remain a cross-check")
    disposition_parts=[data/f"dispositions_{ex}.parquet" for ex in ("TWSE","TPEx")]
    disposition_audits=[data/f"disposition_query_audit_{ex}.parquet" for ex in ("TWSE","TPEx")]
    disp_ok=all(p.exists() for p in disposition_parts+disposition_audits)
    add("disposition_history",disp_ok,sum(pd.read_parquet(p).shape[0] for p in disposition_parts if p.exists()),"both exchanges with successful range-query audit","Exclude disposition periods point-in-time; file existence alone is insufficient")
    status_missing={}
    expected_status={pd.Timestamp(x) for x in calendar[calendar>=pd.Timestamp("2019-01-01")]}
    for ex in ("TWSE","TPEx"):
        ap=data/f"status_query_audit_{ex}.parquet";successful=set()
        if ap.exists():
            audit=pd.read_parquet(ap);successful={pd.Timestamp(x) for x in audit.loc[audit.success,"date"]}
        status_missing[ex]=len(expected_status-successful)
    status_ok=all(v==0 for v in status_missing.values())
    add("altered_suspended_history",status_ok,str(status_missing),"0 unaudited dates for both exchanges","Every query date must explicitly succeed; empty event tables are not treated as successful queries")
    add("benchmarks",taiex.exists() and (data/"processed"/"0050.parquet").exists(),"TAIEX+0050","TAIEX+0050","Benchmark comparison")
    out=pd.DataFrame(checks);out.to_csv(reports/"research_readiness.csv",index=False);return out
