from __future__ import annotations

import pandas as pd


class TradingCalendar:
    def __init__(self, sessions):
        idx = pd.DatetimeIndex(pd.to_datetime(sessions)).normalize().sort_values().unique()
        if idx.has_duplicates or not idx.is_monotonic_increasing:
            raise ValueError("INVALID_TRADING_CALENDAR")
        self.sessions = idx
        self._positions = {d: i for i, d in enumerate(idx)}

    def contains(self, date) -> bool:
        return pd.Timestamp(date).normalize() in self._positions

    def next_session(self, date, n: int = 1) -> pd.Timestamp:
        d = pd.Timestamp(date).normalize()
        if d not in self._positions:
            raise KeyError(f"NOT_A_TRADING_SESSION:{d.date()}")
        j = self._positions[d] + n
        if j >= len(self.sessions):
            raise IndexError("TRADING_SESSION_OUT_OF_RANGE")
        return self.sessions[j]

    def sessions_between(self, start, end) -> pd.DatetimeIndex:
        return self.sessions[(self.sessions >= pd.Timestamp(start)) & (self.sessions <= pd.Timestamp(end))]

    def distance(self, start, end) -> int:
        return self._positions[pd.Timestamp(end).normalize()] - self._positions[pd.Timestamp(start).normalize()]
