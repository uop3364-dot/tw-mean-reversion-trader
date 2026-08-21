from __future__ import annotations

import numpy as np
import pandas as pd


def benchmark_comparison(data: dict[str, pd.DataFrame], start, end=None) -> pd.DataFrame:
    """Comparable buy-and-hold price-index results over the portfolio interval."""
    rows = []
    start = pd.Timestamp(start)
    end = pd.Timestamp(end) if end else None
    for symbol, label in (("TAIEX", "TAIEX Price Index"), ("0050", "0050 Adjusted Close")):
        frame = data.get(symbol, pd.DataFrame()).copy()
        if frame.empty:
            continue
        frame["date"] = pd.to_datetime(frame["date"])
        price_col = "adjusted_close" if symbol == "0050" and "adjusted_close" in frame else "close"
        cut = frame.loc[(frame.date >= start) & ((frame.date <= end) if end is not None else True), ["date", price_col]].dropna()
        if len(cut) < 2:
            continue
        prices = cut[price_col].astype(float)
        total = prices.iloc[-1] / prices.iloc[0] - 1
        years = max((cut.date.iloc[-1] - cut.date.iloc[0]).days / 365.25, 1 / 365.25)
        dd = prices / prices.cummax() - 1
        rows.append({
            "Benchmark": label,
            "Start": cut.date.iloc[0].date(),
            "End": cut.date.iloc[-1].date(),
            "Total Return": total,
            "CAGR": (1 + total) ** (1 / years) - 1,
            "Max Drawdown": dd.min(),
            "Observations": len(cut),
            "Price Field": price_col,
        })
    return pd.DataFrame(rows)
