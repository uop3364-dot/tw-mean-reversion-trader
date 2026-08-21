from __future__ import annotations

import re
import pandas as pd
import requests


def _roc(value):
    match = re.fullmatch(r"(\d{3})[-/](\d{2})[-/](\d{2})", str(value).strip())
    return pd.Timestamp(int(match[1]) + 1911, int(match[2]), int(match[3])) if match else pd.NaT


def twse_delisted() -> pd.DataFrame:
    url = "https://openapi.twse.com.tw/v1/company/suspendListingCsvAndHtml"
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    rows = response.json()
    out = pd.DataFrame({"symbol": [str(x.get("Code", "")).strip() for x in rows], "name": [x.get("Company", "") for x in rows], "delisting_date": [_roc(x.get("DelistingDate")) for x in rows]})
    out = out[out.symbol.str.fullmatch(r"\d{4}")].assign(exchange="TWSE", source="TWSE suspendListingCsvAndHtml")
    return out.sort_values("delisting_date").reset_index(drop=True)


def tpex_delisted(start_year=2018, end_year=None) -> pd.DataFrame:
    end_year = end_year or pd.Timestamp.today().year
    rows = []
    for year in range(start_year, end_year + 1):
        url = "https://www.tpex.org.tw/www/zh-tw/company/deListed"
        response = requests.get(url, params={"code": "", "date": year, "reason": -1, "response": "json"}, timeout=60)
        response.raise_for_status()
        tables = response.json().get("tables", [])
        for x in (tables[0].get("data", []) if tables else []):
            rows.append({"symbol": str(x[0]).strip(), "name": x[1], "delisting_date": _roc(x[2]), "reason": x[3], "exchange": "TPEx", "source": "TPEx company/deListed"})
    return pd.DataFrame(rows).sort_values("delisting_date").reset_index(drop=True)
