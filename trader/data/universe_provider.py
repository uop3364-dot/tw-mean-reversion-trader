from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
import json,re
import pandas as pd
import requests

TWSE_BASE="https://openapi.twse.com.tw/v1"
TPEX_BASE="https://www.tpex.org.tw/openapi/v1"

def _json(url):
    r=requests.get(url,timeout=60);r.raise_for_status()
    return json.loads(r.content.decode("utf-8"))

def _roc_date(value):
    text=re.sub(r"\D","",str(value or ""))
    if len(text)<7:return pd.NaT
    year=int(text[:-4])+1911
    try:return pd.Timestamp(year=year,month=int(text[-4:-2]),day=int(text[-2:]))
    except ValueError:return pd.NaT

class OfficialUniverseProvider:
    """Current issuer master and current/historical safety flags from TWSE/TPEx.

    Current company lists are not a historical constituent database. The explicit
    `point_in_time_complete` field prevents accidental survivorship-free claims.
    """
    def current(self)->pd.DataFrame:
        tw=_json(f"{TWSE_BASE}/opendata/t187ap03_L")
        otc=_json(f"{TPEX_BASE}/mopsfin_t187ap03_O")
        rows=[]
        for r in tw:
            vals=list(r.values()); symbol=str(vals[1]).strip()
            rows.append({"symbol":symbol,"name":str(vals[3]).strip(),"exchange":"TWSE","listing_date":pd.to_datetime(str(vals[15]).strip(),format="%Y%m%d",errors="coerce"),"registration":str(vals[4]).strip(),"industry_code":str(vals[5]).strip(),"preferred_shares":pd.to_numeric(vals[18],errors="coerce"),"source":"TWSE t187ap03_L"})
        for r in otc:
            rows.append({"symbol":str(r.get("SecuritiesCompanyCode","")).strip(),"name":str(r.get("CompanyAbbreviation","")).strip(),"exchange":"TPEx","listing_date":pd.to_datetime(r.get("DateOfListing"),format="%Y%m%d",errors="coerce"),"registration":str(r.get("Registration","")).strip(),"industry_code":str(r.get("SecuritiesIndustryCode","")).strip(),"preferred_shares":pd.to_numeric(r.get("PreferredStock.shares"),errors="coerce"),"source":"TPEx mopsfin_t187ap03_O"})
        d=pd.DataFrame(rows);d=d[d.symbol.str.fullmatch(r"\d{4}")].drop_duplicates("symbol")
        d["instrument_type"]="stock";d["is_ky"]=d.name.str.contains("KY",case=False,na=False);d["point_in_time_complete"]=False
        return self._current_flags(d)
    def _current_flags(self,d):
        d=d.copy();d["is_suspended"]=False;d["is_disposition"]=False;d["is_full_cash_delivery"]=False
        tw_halt=_json(f"{TWSE_BASE}/exchangeReport/TWTAWU");tw_alt=_json(f"{TWSE_BASE}/exchangeReport/TWT85U");tw_disp=_json(f"{TWSE_BASE}/announcement/punish")
        otc_halt=_json(f"{TPEX_BASE}/tpex_spendi_history");otc_mode=_json(f"{TPEX_BASE}/tpex_cmode");otc_disp=_json(f"{TPEX_BASE}/tpex_disposal_information")
        suspended={str(x.get("Code","")).strip() for x in tw_halt if not x.get("TradingResumptionDate")}
        suspended|={str(x.get("SecuritiesCompanyCode","")).strip() for x in otc_halt if not x.get("DateOfResumedTrading")}
        altered={str(x.get("Code","")).strip() for x in tw_alt}
        altered|={str(x.get("SecuritiesCompanyCode","")).strip() for x in otc_mode if str(x.get("AlteredTrading","")).strip()}
        disposition={str(x.get("Code","")).strip() for x in tw_disp}|{str(x.get("SecuritiesCompanyCode","")).strip() for x in otc_disp}
        d.loc[d.symbol.isin(suspended),"is_suspended"]=True;d.loc[d.symbol.isin(altered),"is_full_cash_delivery"]=True;d.loc[d.symbol.isin(disposition),"is_disposition"]=True
        d["snapshot_date"]=pd.Timestamp.today().normalize();return d.sort_values(["exchange","symbol"]).reset_index(drop=True)
