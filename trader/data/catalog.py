from __future__ import annotations

from pathlib import Path
import pandas as pd


def build_catalog(root: Path):
    """Build a symbol-level research inventory with explicit source and purpose."""
    data=root/"data";reports=root/"reports";processed=data/"processed"
    current=pd.read_parquet(data/"universe.parquet")
    delisted=pd.read_parquet(data/"delisted_universe.parquet")
    tpex_hist=pd.read_parquet(data/"historical_universe_TPEx.parquet")
    provenance=pd.read_parquet(data/"ohlcv_provenance.parquet") if (data/"ohlcv_provenance.parquet").exists() else pd.DataFrame()
    finmind=set(provenance.symbol.astype(str)) if not provenance.empty else set()
    rows=[]
    # Official TPEx daily tables are the membership evidence and price source.
    for x in tpex_hist.itertuples():
        status="EXCLUDE_NON_COMMON_STOCK_TDR" if str(x.symbol).startswith("91") else ("READY" if x.trading_days>=120 else "EXCLUDE_INSUFFICIENT_HISTORY")
        rows.append({"symbol":str(x.symbol),"exchange":"TPEx","first_seen":x.first_seen,"last_seen":x.last_seen,"trading_days":x.trading_days,"source":"TPEx STK_WN1430","universe_reason":"observed in official daily market table","data_status":status})
    # TWSE membership is current master plus official delisting master. Price
    # history itself supplies first/last observed dates and prevents dates after
    # delisting from entering a signal.
    tw=pd.concat([current[current.exchange=="TWSE"][["symbol","exchange"]],delisted[delisted.exchange=="TWSE"][["symbol","exchange"]]],ignore_index=True).drop_duplicates("symbol")
    for x in tw.itertuples():
        path=processed/f"{x.symbol}.parquet"
        if not path.exists():
            status="EXCLUDE_NO_OVERLAPPING_PRICE_HISTORY";first=last=pd.NaT;days=0
        else:
            bars=pd.read_parquet(path,columns=["date"]);first=bars.date.min();last=bars.date.max();days=bars.date.nunique();status="READY" if days>=120 else "EXCLUDE_INSUFFICIENT_HISTORY"
        source="FinMind TaiwanStockPrice" if str(x.symbol) in finmind else "Yahoo bootstrap, OHLC/calendar validated"
        rows.append({"symbol":str(x.symbol),"exchange":"TWSE","first_seen":first,"last_seen":last,"trading_days":days,"source":source,"universe_reason":"current TWSE issuer or official TWSE delisting record","data_status":status})
    catalog=pd.DataFrame(rows).sort_values(["exchange","symbol"]).drop_duplicates("symbol",keep="last")
    catalog.to_parquet(data/"historical_universe.parquet",index=False);catalog.to_csv(reports/"historical_universe.csv",index=False)
    source=catalog.groupby(["exchange","source","data_status"],dropna=False).size().rename("symbols").reset_index()
    source.to_csv(reports/"data_source_summary.csv",index=False)
    exclusions=catalog[catalog.data_status!="READY"]
    exclusions.to_csv(reports/"data_exclusions.csv",index=False)
    return catalog,source,exclusions
