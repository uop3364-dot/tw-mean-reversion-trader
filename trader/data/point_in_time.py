from __future__ import annotations

import pandas as pd


ALLOWED_INSTRUMENTS = {"stock", "ordinary_stock", "common_stock", "COMMON_STOCK"}


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
        if "eligibility_start" in self.securities:
            self.securities["eligibility_start"] = pd.to_datetime(self.securities.eligibility_start)
        self.altered = altered.copy() if altered is not None else pd.DataFrame(columns=["date", "symbol", "status"])
        self.dispositions = dispositions.copy() if dispositions is not None else pd.DataFrame(columns=["symbol", "start_date", "end_date"])
        if not self.altered.empty:
            self.altered["date"] = pd.to_datetime(self.altered.date)
        if not self.dispositions.empty:
            self.dispositions[["start_date", "end_date"]] = self.dispositions[["start_date", "end_date"]].apply(pd.to_datetime)

    def _rows(self, symbol):
        return self.securities[self.securities.symbol == str(symbol)]

    def listing_date(self, symbol):
        rows = self._rows(symbol)
        return None if rows.empty else rows.listing_date.min()

    def delisting_date(self, symbol):
        rows = self._rows(symbol)
        return None if rows.empty else rows.delisting_date.max()

    def is_listed(self, symbol, date) -> bool:
        rows = self._rows(symbol); d = pd.Timestamp(date)
        if rows.empty:
            return False
        starts = rows.eligibility_start if "eligibility_start" in rows else rows.listing_date
        valid = (
            rows.exchange.isin(["TWSE", "TPEx"])
            & rows.instrument_type.isin(ALLOWED_INSTRUMENTS)
            & starts.notna()
            & starts.le(d)
            & (rows.delisting_date.isna() | rows.delisting_date.gt(d))
        )
        return bool(valid.any())

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
