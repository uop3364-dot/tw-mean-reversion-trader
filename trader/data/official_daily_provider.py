from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
import re,time
import pandas as pd
import requests

def _num(x):
    try:return float(str(x).replace(",","").replace("--","").strip())
    except (ValueError,TypeError):return float("nan")

def _get_json(url,retries=2):
    last=None
    for n in range(retries):
        try:
            r=requests.get(url,timeout=20,headers={"User-Agent":"tw-mean-reversion-research/0.1","Accept-Encoding":"gzip"});r.raise_for_status();return r.json()
        except Exception as exc:last=exc;time.sleep(1.5*(n+1))
    raise last

def fetch_twse(day:pd.Timestamp):
    ds=day.strftime("%Y%m%d");url=f"https://wwwc.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={ds}&type=ALLBUT0999&response=json"
    j=_get_json(url)
    if j.get("date") not in (None, ds):
        raise ValueError(f"TWSE_DATE_MISMATCH:{ds}:{j.get('date')}")
    tables=j.get("tables",[]);table=max((t for t in tables if len(t.get("fields",[]))>=16),key=lambda t:len(t.get("data",[])),default={})
    rows=[]
    for x in table.get("data",[]):
        symbol=str(x[0]).strip()
        if re.fullmatch(r"\d{4}",symbol):rows.append({"date":day,"symbol":symbol,"exchange":"TWSE","open":_num(x[5]),"high":_num(x[6]),"low":_num(x[7]),"close":_num(x[8]),"volume":_num(x[2]),"turnover":_num(x[4]),"source":"TWSE_MI_INDEX"})
    return rows

def fetch_tpex(day:pd.Timestamp):
    roc=day.year-1911;ds=f"{roc}/{day:%m/%d}";url=f"https://www.tpex.org.tw/web/stock/aftertrading/otc_quotes_no1430/stk_wn1430_result.php?l=zh-tw&d={ds}&se=EW&o=json"
    j=_get_json(url)
    if j.get("date") not in (None, day.strftime("%Y%m%d")):
        raise ValueError(f"TPEX_DATE_MISMATCH:{day:%Y%m%d}:{j.get('date')}")
    tables=j.get("tables",[]);table=max((t for t in tables if len(t.get("fields",[]))>=15),key=lambda t:len(t.get("data",[])),default={})
    rows=[]
    for x in table.get("data",[]):
        symbol=str(x[0]).strip()
        if re.fullmatch(r"\d{4}",symbol):rows.append({"date":day,"symbol":symbol,"exchange":"TPEx","open":_num(x[4]),"high":_num(x[5]),"low":_num(x[6]),"close":_num(x[2]),"volume":_num(x[7]),"turnover":_num(x[8]),"source":"TPEX_STK_WN1430"})
    return rows

class OfficialDailyMarketProvider:
    def __init__(self,root):self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
    def download(self,dates,workers=4,exchanges=("TWSE","TPEx"),max_partitions=None):
        dates=pd.DatetimeIndex(dates).normalize().unique().sort_values();failures=[];created=0
        covered={ex:set() for ex in exchanges}
        for ex in exchanges:
            for saved_path in self.root.glob(f"{ex}_*.parquet"):
                try:covered[ex]|={pd.Timestamp(x) for x in pd.read_parquet(saved_path,columns=["date"]).date.unique()}
                except Exception:pass
        groups={};tasks={}
        for exchange,fn in (("TWSE",fetch_twse),("TPEx",fetch_tpex)):
            if exchange not in exchanges:continue
            needed=pd.DatetimeIndex([d for d in dates if pd.Timestamp(d) not in covered[exchange]])
            for day in needed:
                key=(exchange,day.to_period("M"));groups.setdefault(key,{"dates":set(),"rows":[],"done":0})
                groups[key]["dates"].add(pd.Timestamp(day));tasks[(exchange,pd.Timestamp(day))]=fn
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures={pool.submit(fn,day):(exchange,day) for (exchange,day),fn in tasks.items()}
            for future in as_completed(futures):
                exchange,day=futures[future];key=(exchange,day.to_period("M"));group=groups[key]
                try:
                    result=future.result()
                    if not result:failures.append({"date":day,"exchange":exchange,"reason":"EMPTY_OFFICIAL_SESSION"})
                    else:group["rows"].extend(result)
                except Exception as exc:failures.append({"date":day,"exchange":exchange,"reason":repr(exc)})
                group["done"]+=1
                if group["done"]==len(group["dates"]):
                    frame=pd.DataFrame(group["rows"],columns=["date","symbol","exchange","open","high","low","close","volume","turnover","source"]).sort_values(["date","symbol"])
                    actual=set(pd.to_datetime(frame.date).dt.normalize()) if not frame.empty else set()
                    if actual==group["dates"]:
                        path=self.root/f"{exchange}_{min(actual):%Y%m%d}_{max(actual):%Y%m%d}.parquet"
                        frame.to_parquet(path,index=False);created+=1
                        if max_partitions and created>=max_partitions:
                            for pending in futures:pending.cancel()
                            return pd.DataFrame(failures)
        return pd.DataFrame(failures)
    def consolidate(self,repository,required_dates=None,exchanges=("TWSE","TPEx")):
        """Validate and persist only the requested exchanges.

        Keeping the exchange list explicit allows a completed market (currently
        TPEx) to replace bootstrap data without weakening the completeness gate
        for another market.
        """
        parts=[p for ex in exchanges for p in self.root.glob(f"{ex}_*.parquet")]
        if not parts:raise RuntimeError(f"No official daily partitions for {exchanges}")
        frames=[pd.read_parquet(p) for p in parts];all_data=pd.concat(frames,ignore_index=True).sort_values(["symbol","date"])
        if required_dates is not None:
            expected={pd.Timestamp(x) for x in required_dates}
            coverage={ex:{pd.Timestamp(x) for x in all_data.loc[all_data.exchange==ex,"date"].unique()} for ex in exchanges}
            missing={ex:sorted(expected-days) for ex,days in coverage.items()}
            if any(missing.values()):
                detail={ex:len(days) for ex,days in missing.items()};raise RuntimeError(f"Official daily coverage incomplete; refusing to overwrite research data: {detail}")
        all_data=all_data.dropna(subset=["open","high","low","close"]);all_data=all_data[(all_data.high>=all_data.low)&(all_data.high>=all_data[["open","close"]].max(axis=1))&(all_data.low<=all_data[["open","close"]].min(axis=1))]
        for symbol,d in all_data.groupby("symbol",sort=False):repository.save(symbol,d[["date","open","high","low","close","volume"]])
        hist=all_data.groupby(["symbol","exchange"],as_index=False).agg(first_seen=("date","min"),last_seen=("date","max"),trading_days=("date","nunique"),source=("source","first"))
        return hist
