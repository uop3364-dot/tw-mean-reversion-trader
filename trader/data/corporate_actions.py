from __future__ import annotations

import pandas as pd


SUPPORTED_ACTIONS = {
    "CASH_DIVIDEND", "STOCK_DIVIDEND", "RIGHTS", "RIGHTS_ISSUE",
    "CAPITAL_REDUCTION", "SPLIT", "REVERSE_SPLIT", "OTHER",
}


class CorporateActionAdjuster:
    """Backward adjustment layer; raw exchange OHLCV remains immutable."""
    def __init__(self, actions: pd.DataFrame):
        self.actions = actions.copy()
        if not self.actions.empty:
            self.actions["date"] = pd.to_datetime(self.actions.date)
            self.actions["event_type"] = self.actions.event_type.astype(str).str.upper()
            unknown = set(self.actions.event_type) - SUPPORTED_ACTIONS
            if unknown:
                raise ValueError(f"UNKNOWN_CORPORATE_ACTION:{sorted(unknown)}")

    def adjust(self, symbol: str, bars: pd.DataFrame) -> pd.DataFrame:
        out = bars.sort_values("date").copy(); out["date"] = pd.to_datetime(out.date); out["adjustment_factor"] = 1.0
        for c in ("open", "high", "low", "close", "volume"):
            out[f"trade_{c}"] = out[c]
        acts = self.actions[self.actions.symbol.astype(str) == str(symbol)].sort_values("date", ascending=False)
        factor = pd.Series(1.0, index=out.index)
        for a in acts.itertuples():
            factor.loc[out.date < a.date] *= float(a.adjustment_factor)
        for c in ("open", "high", "low", "close"):
            out[f"adjusted_{c}"] = out[c] * factor
            out[f"analysis_{c}"] = out[f"adjusted_{c}"]
        out["adjusted_volume"] = out.volume / factor.replace(0, pd.NA)
        out["analysis_volume"] = out["adjusted_volume"]
        out["adjustment_factor"] = factor
        return out

    def audit_large_returns(self, symbol: str, bars: pd.DataFrame) -> pd.DataFrame:
        d = bars.sort_values("date").copy(); d["return"] = d.close.pct_change(); large = d[d["return"].abs() > .25].copy()
        if large.empty:
            return pd.DataFrame(columns=["symbol", "date", "return", "matched_action", "verified"])
        dates = set(self.actions.loc[self.actions.symbol.astype(str) == str(symbol), "date"])
        large["symbol"] = str(symbol); large["matched_action"] = large.date.isin(dates); large["verified"] = large.matched_action
        return large[["symbol", "date", "return", "matched_action", "verified"]]
