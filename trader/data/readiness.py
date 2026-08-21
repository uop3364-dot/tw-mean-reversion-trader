from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import hashlib,json
import pandas as pd

class ResearchDataNotReady(RuntimeError): pass

@dataclass(frozen=True)
class ResearchReadinessResult:
    checks:pd.DataFrame; dataset_version:str; dataset_hash:str
    @property
    def passed(self): return bool(not self.checks.empty and self.checks.passed.all())
    def require(self):
        if not self.passed: raise ResearchDataNotReady("RESEARCH_DATA_NOT_READY:"+",".join(self.checks.loc[~self.checks.passed,"check"]))
        return self

def _hash(paths,extra=b""):
    h=hashlib.sha256(extra)
    for p in sorted(set(Path(x) for x in paths),key=lambda x:x.as_posix()):
        h.update(p.as_posix().encode())
        with p.open("rb") as f:
            for block in iter(lambda:f.read(1048576),b""):h.update(block)
    return h.hexdigest()

def research_readiness(root:Path,cfg=None):
    from trader.config import settings
    cfg=cfg or settings();data=root/"data";out=root/"reports"/"data_audit";out.mkdir(parents=True,exist_ok=True);checks=[]
    def add(name,ok,actual,required,reason):checks.append({"check":name,"passed":bool(ok),"actual":str(actual),"required":str(required),"reason":reason})
    hp=data/"historical_universe.parquet";hist=pd.read_parquet(hp) if hp.exists() else pd.DataFrame();required={"symbol","exchange","listing_date","delisting_date","instrument_type"}
    pit=required<=set(hist.columns) and hist.listing_date.notna().all();add("point_in_time_universe",pit,sorted(hist.columns),sorted(required),"authoritative listing/delisting/type for every security")
    ordinary=not hist.empty and "instrument_type" in hist and hist.instrument_type.isin(["stock","ordinary_stock","common_stock"]).all();add("ordinary_stock_identity",ordinary,"verified" if ordinary else "missing","TWSE/TPEx ordinary stock only","product identity must be point-in-time")
    dp=data/"delisted_universe.parquet";dl=pd.read_parquet(dp) if dp.exists() else pd.DataFrame();covered=not dl.empty and not hist.empty and set(dl.symbol.astype(str))<=set(hist.symbol.astype(str));add("delisted_coverage",covered,f"{len(dl)} delisted", "all delisted", "prevent survivorship bias")
    tp=data/"processed"/"TAIEX.parquet";cal=pd.read_parquet(tp).date if tp.exists() else pd.Series(dtype="datetime64[ns]");idx=pd.DatetimeIndex(cal);add("trading_calendar",len(idx)>0 and idx.is_unique and idx.is_monotonic_increasing,len(idx),"unique ordered sessions","single timing source")
    expected=set(pd.to_datetime(cal[cal>=pd.Timestamp("2019-01-01")]));missing={}
    for ex in ("TWSE","TPEx"):
        p=data/f"status_query_audit_{ex}.parquet";success=set()
        if p.exists():
            a=pd.read_parquet(p);success=set(pd.to_datetime(a.loc[a.success,"date"]))
        missing[ex]=len(expected-success)
    add("point_in_time_status",all(v==0 for v in missing.values()),missing,"zero missing sessions","tradability state per exchange session")
    pp=data/"provenance.parquet";prov=pd.read_parquet(pp) if pp.exists() else pd.DataFrame();pc={"symbol","start_date","end_date","source","price_convention","download_timestamp","repair_reason","validation_result"};ready=set(hist.loc[hist.get("data_status",pd.Series(index=hist.index)).eq("READY"),"symbol"].astype(str)) if not hist.empty else set();ps=set(prov.symbol.astype(str)) if pc<=set(prov.columns) else set();add("ohlcv_provenance",pc<=set(prov.columns) and ready<=ps,f"{len(ps)}/{len(ready)}", "every symbol/range","secondary data cannot be unmarked")
    conv=set(prov.price_convention.dropna()) if "price_convention" in prov else set();add("price_convention",conv=={"UNADJUSTED_EXCHANGE"},conv,"UNADJUSTED_EXCHANGE","no adjusted/unadjusted mix")
    ap=data/"corporate_actions.parquet";actions=pd.read_parquet(ap) if ap.exists() else pd.DataFrame();ac={"symbol","date","event_type","adjustment_factor","source","verified"};complete=ac<=set(actions.columns) and not actions.empty and actions.verified.astype(bool).all();add("corporate_actions",complete,f"rows={len(actions)}","complete verified ledger","auditable adjustment layer")
    lap=out/"corporate_action_audit.csv";large=pd.read_csv(lap) if lap.exists() else pd.DataFrame();largeok=not large.empty and "verified" in large and large.verified.astype(bool).all();add("large_return_audit",largeok,f"rows={len(large)}","all >25% moves verified","corporate action/data error audit")
    invalid=duplicates=offcal=0
    for p in (data/"processed").glob("*.parquet"):
        d=pd.read_parquet(p);d["date"]=pd.to_datetime(d.date);bad=(d[["open","high","low","close"]]<=0).any(axis=1)|(d.volume<0)|(d.high<d.low)|(d.high<d[["open","close"]].max(axis=1))|(d.low>d[["open","close"]].min(axis=1));invalid+=int(bad.sum());duplicates+=int(d.date.duplicated().sum());offcal+=int((~d.date.isin(cal)).sum()) if len(cal) else len(d)
    add("ohlcv_hard_checks",invalid==duplicates==offcal==0,{"invalid":invalid,"duplicates":duplicates,"off_calendar":offcal},"all zero","bar and calendar invariants")
    version=cfg.get("research",{}).get("dataset_version","UNVERSIONED");paths=[p for p in [hp,dp,pp,ap,tp,root/"config"/"strategy.yaml"] if p.exists()]+list((data/"processed").glob("*.parquet"))+list(data.glob("*status*.parquet"))+list(data.glob("dispositions*.parquet"));dh=_hash(paths,json.dumps(cfg,sort_keys=True,default=str).encode());frame=pd.DataFrame(checks);frame.to_csv(out/"research_readiness.csv",index=False);(out/"readiness.json").write_text(json.dumps({"dataset_version":version,"dataset_hash":dh,"passed":bool(frame.passed.all()),"checks":frame.to_dict("records")},indent=2),encoding="utf-8");return ResearchReadinessResult(frame,version,dh)
