from __future__ import annotations

import pandas as pd


ALLOWED_INSTRUMENTS = {"stock", "ordinary_stock", "common_stock"}


class PointInTimeUniverse:
    def __init__(self, securities: pd.DataFrame, altered=None, dispositions=None):
        required = {"symbol", "exchange", "listing_date", "delisting_date", "instrument_type"}
        missing = required - set(securities.columns)
        if missing:
            raise ValueError(f"POINT_IN_TIME_COLUMNS_MISSING:{sorted(missing)}")
        self.securities = securities.copy()
        self.securities["symbol"] = self.securities.symbol.astype(str)
        self.securities["listing_date"] = pd.to_datetime(self.securities.listing_date)
        self.securities["delisting_date"] = pd.to_datetime(self.securities.delisting_date)
        self.altered = altered.copy() if altered is not None else pd.DataFrame(columns=["date", "symbol", "status"])
        self.dispositions = dispositions.copy() if dispositions is not None else pd.DataFrame(columns=["symbol", "start_date", "end_date"])
        if not self.altered.empty:
            self.altered["date"] = pd.to_datetime(self.altered.date)
        if not self.dispositions.empty:
            self.dispositions[["start_date", "end_date"]] = self.dispositions[["start_date", "end_date"]].apply(pd.to_datetime)

    def _row(self, symbol):
        rows = self.securities[self.securities.symbol == str(symbol)]
        return None if rows.empty else rows.iloc[0]

    def listing_date(self, symbol):
        row = self._row(symbol)
        return None if row is None else row.listing_date

    def delisting_date(self, symbol):
        row = self._row(symbol)
        return None if row is None else row.delisting_date

    def is_listed(self, symbol, date) -> bool:
        row = self._row(symbol); d = pd.Timestamp(date)
        return bool(row is not None and row.exchange in ("TWSE", "TPEx") and row.instrument_type in ALLOWED_INSTRUMENTS and pd.notna(row.listing_date) and row.listing_date <= d and (pd.isna(row.delisting_date) or d <= row.delisting_date))

    def is_tradable(self, symbol, date) -> bool:
        if not self.is_listed(symbol, date):
            return False
        d = pd.Timestamp(date); sym = str(symbol)
        altered = self.altered[(self.altered.symbol.astype(str) == sym) & (self.altered.date == d)]
        if not altered.empty:
            return False
        disp = self.dispositions[(self.dispositions.symbol.astype(str) == sym) & (self.dispositions.start_date <= d) & (self.dispositions.end_date >= d)]
        return disp.empty

    def symbols_on(self, date):
        return sorted(s for s in self.securities.symbol.unique() if self.is_listed(s, date))
