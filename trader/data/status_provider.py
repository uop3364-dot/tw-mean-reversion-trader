from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor,as_completed
import re
import pandas as pd
import requests
from .universe_provider import _roc_date

def _period(text):
    parts=re.findall(r"\d{2,4}[./-]\d{1,2}[./-]\d{1,2}",str(text));dates=[_roc_date(x) for x in parts]
    return (dates[0] if dates else pd.NaT,dates[1] if len(dates)>1 else (dates[0] if dates else pd.NaT))

def dispositions(start="2019-01-01",end=None,exchanges=("TWSE","TPEx")):
    end=pd.Timestamp(end or pd.Timestamp.today()).strftime("%Y%m%d");start_ts=pd.Timestamp(start);rows=[]
    if "TWSE" in exchanges:
        response=requests.get("https://wwwc.twse.com.tw/announcement/punish",params={"response":"json","startDate":start_ts.strftime('%Y%m%d'),"endDate":end,"stockNo":"","sortKind":"DATE","querytype":"","selectType":"","proceType":"","remarkType":""},timeout=60);response.raise_for_status();payload=response.json()
        if payload.get("stat")!="OK":raise RuntimeError(f"TWSE disposition endpoint failed: {payload.get('stat')}")
        for vals in payload.get("data",[]):
            symbol=str(vals[2]).strip();a,b=_period(vals[6])
            if re.fullmatch(r"\d{4}",symbol) and pd.notna(a) and pd.notna(b):rows.append({"symbol":symbol,"exchange":"TWSE","start_date":a,"end_date":b,"status":"DISPOSITION","source":"TWSE_announcement_punish"})
    for year in range(start_ts.year,pd.Timestamp(end).year+1) if "TPEx" in exchanges else []:
        a=max(start_ts,pd.Timestamp(year=year,month=1,day=1));b=min(pd.Timestamp(end),pd.Timestamp(year=year,month=12,day=31))
        response=requests.get("https://www.tpex.org.tw/www/zh-tw/bulletin/disposal",params={"startDate":a.strftime('%Y/%m/%d'),"endDate":b.strftime('%Y/%m/%d'),"type":"all","order":"date"},timeout=60);response.raise_for_status();j=response.json()
        for x in j.get("tables",[{}])[0].get("data",[]):
            symbol=re.sub(r"\D","",str(x[2]));p,q=_period(x[5])
            if re.fullmatch(r"\d{4}",symbol) and pd.notna(p) and pd.notna(q):rows.append({"symbol":symbol,"exchange":"TPEx","start_date":p,"end_date":q,"status":"DISPOSITION","source":"TPEX_bulletin_disposal"})
    return pd.DataFrame(rows,columns=["symbol","exchange","start_date","end_date","status","source"]).drop_duplicates(["symbol","start_date","end_date","status"])

def altered_daily(dates,workers=4,exchanges=("TWSE","TPEx"),return_audit=False):
    def one_twse(day):
        response=requests.get("https://wwwc.twse.com.tw/exchangeReport/TWT85U",params={"response":"json","date":day.strftime('%Y%m%d')},timeout=30);response.raise_for_status();j=response.json();out=[]
        if j.get("stat") not in ("OK",None):raise RuntimeError(str(j.get("stat")))
        for x in j.get("data",[]):
            symbol=str(x[0]).strip()
            if re.fullmatch(r"\d{4}",symbol):out.append({"date":day,"symbol":symbol,"exchange":"TWSE","status":"FULL_CASH_DELIVERY","source":"TWSE_TWT85U"})
        return "TWSE",day,out
    def one_tpex(day):
        response=requests.get("https://www.tpex.org.tw/www/zh-tw/afterTrading/chtm",params={"date":day.strftime('%Y/%m/%d')},timeout=30);response.raise_for_status();j=response.json();out=[]
        if j.get("stat") not in ("ok","OK",None):raise RuntimeError(str(j.get("stat")))
        for x in j.get("tables",[{}])[0].get("data",[]):
            symbol=str(x[0]).strip()
            if re.fullmatch(r"\d{4}",symbol) and str(x[2]).strip():out.append({"date":day,"symbol":symbol,"exchange":"TPEx","status":"FULL_CASH_DELIVERY","source":"TPEX_CHTM"})
            if re.fullmatch(r"\d{4}",symbol) and len(x)>6 and str(x[6]).strip():out.append({"date":day,"symbol":symbol,"exchange":"TPEx","status":"SUSPENDED","source":"TPEX_CHTM"})
        return "TPEx",day,out
    rows=[];audit=[]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        funcs=[]
        if "TWSE" in exchanges:funcs.append(one_twse)
        if "TPEx" in exchanges:funcs.append(one_tpex)
        fs={pool.submit(fn,pd.Timestamp(d)):("TWSE" if fn is one_twse else "TPEx",pd.Timestamp(d)) for d in dates for fn in funcs}
        for f in as_completed(fs):
            exchange,day=fs[f]
            try:
                _,_,found=f.result();rows.extend(found);audit.append({"date":day,"exchange":exchange,"success":True,"rows":len(found),"reason":""})
            except Exception as exc:audit.append({"date":day,"exchange":exchange,"success":False,"rows":0,"reason":repr(exc)})
    frame=pd.DataFrame(rows,columns=["date","symbol","exchange","status","source"]).drop_duplicates(["date","symbol","status"])
    checks=pd.DataFrame(audit,columns=["date","exchange","success","rows","reason"]).sort_values(["exchange","date"])
    return (frame,checks) if return_audit else frame
