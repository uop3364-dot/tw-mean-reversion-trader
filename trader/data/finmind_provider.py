from __future__ import annotations

import os
import time
from pathlib import Path

import pandas as pd
import requests


class FinMindDataProvider:
    """Targeted secondary source for TWSE gaps and delisted securities.

    It is deliberately not used as an opaque bulk universe source.  Every request
    is recorded in a provenance table and every returned bar must satisfy OHLC
    invariants before it can replace bootstrap data.
    """

    url = "https://api.finmindtrade.com/api/v4/data"

    def __init__(self, token: str | None = None, delay: float = 0.25):
        self.token = token or os.getenv("FINMIND_TOKEN")
        self.delay = delay

    def history(self, symbol: str, start: str, end: str | None = None, minimum_date=None, infer_listing_boundary=False) -> pd.DataFrame:
        params = {"dataset": "TaiwanStockPrice", "data_id": str(symbol), "start_date": start}
        if end:
            params["end_date"] = end
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        response = requests.get(self.url, params=params, headers=headers, timeout=60)
        response.raise_for_status()
        payload = response.json()
        if payload.get("status") != 200:
            raise RuntimeError(f"FinMind {symbol}: {payload.get('msg', payload)}")
        raw = pd.DataFrame(payload.get("data", []))
        time.sleep(self.delay)
        if raw.empty:
            return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume", "turnover"])
        out = raw.rename(columns={"max": "high", "min": "low", "Trading_Volume": "volume", "Trading_money": "turnover"})
        out["date"] = pd.to_datetime(out["date"])
        for column in ("open", "high", "low", "close", "volume", "turnover"):
            out[column] = pd.to_numeric(out[column], errors="coerce")
        out = out[["date", "open", "high", "low", "close", "volume", "turnover"]].dropna(subset=["open", "high", "low", "close"])
        if minimum_date is not None and not pd.isna(minimum_date):
            out = out[out.date >= pd.Timestamp(minimum_date)]
        valid = (out[["open","high","low","close"]] > 0).all(axis=1) & (out.high >= out.low) & (out.high >= out[["open", "close"]].max(axis=1)) & (out.low <= out[["open", "close"]].min(axis=1)) & (out.volume >= 0)
        if infer_listing_boundary and not valid.all():
            # FinMind also carries pre-listing emerging-market rows under the
            # same code, where `open` is not an auction open.  Keeping only the
            # final all-valid suffix conservatively excludes that mixed schema.
            last_bad = out.index[~valid].max()
            out = out.loc[out.index > last_bad].copy()
            valid = (out[["open","high","low","close"]] > 0).all(axis=1) & (out.high >= out.low) & (out.high >= out[["open", "close"]].max(axis=1)) & (out.low <= out[["open", "close"]].min(axis=1)) & (out.volume >= 0)
        if not valid.all():
            raise ValueError(f"FinMind {symbol}: {(~valid).sum()} invalid OHLCV rows after listing-date boundary")
        return out.sort_values("date").drop_duplicates("date").reset_index(drop=True)


def write_provenance(path: Path, records: list[dict]) -> pd.DataFrame:
    frame = pd.DataFrame(records)
    if path.exists():
        frame = pd.concat([pd.read_parquet(path), frame], ignore_index=True)
    if not frame.empty:
        frame = frame.sort_values(["symbol", "retrieved_at"]).drop_duplicates("symbol", keep="last")
    frame.to_parquet(path, index=False)
    return frame
