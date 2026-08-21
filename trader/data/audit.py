from pathlib import Path
import pandas as pd
from .corporate_actions import CorporateActionAdjuster

def build_data_audit(root:Path):
    data=root/"data";out=root/"reports"/"data_audit";out.mkdir(parents=True,exist_ok=True);hist=pd.read_parquet(data/"historical_universe.parquet");dl=pd.read_parquet(data/"delisted_universe.parquet");rows=[]
    for x in dl.itertuples():
        h=hist[hist.symbol.astype(str)==str(x.symbol)];p=data/"processed"/f"{x.symbol}.parquet";included=not h.empty and p.exists();rows.append({"symbol":str(x.symbol),"exchange":x.exchange,"listing_date":h.first_seen.min() if not h.empty else pd.NaT,"delisting_date":x.delisting_date,"price_history_available":p.exists(),"included_in_research":included,"exclusion_reason":"" if included else "MISSING_CATALOG_OR_PRICE"})
    pd.DataFrame(rows).to_csv(out/"delisted_coverage.csv",index=False);ap=data/"corporate_actions.parquet";actions=pd.read_parquet(ap) if ap.exists() else pd.DataFrame(columns=["symbol","date","event_type","adjustment_factor","source","verified"]);adj=CorporateActionAdjuster(actions);audits=[]
    for p in (data/"processed").glob("*.parquet"):
        if p.stem in ("TAIEX","0050"):continue
        a=adj.audit_large_returns(p.stem,pd.read_parquet(p));audits.append(a) if not a.empty else None
    large=pd.concat(audits,ignore_index=True) if audits else pd.DataFrame(columns=["symbol","date","return","matched_action","verified"]);large.to_csv(out/"corporate_action_audit.csv",index=False);return {"symbols":len(hist),"delisted":len(dl),"large_returns":len(large),"verified":int(large.verified.sum()) if len(large) else 0,"corporate_actions":len(actions)}
