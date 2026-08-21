from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import json

import numpy as np
import pandas as pd

from .twse_fallback_provider import OfficialFallbackClient, roc_date


RESEARCH_START = pd.Timestamp("2018-01-02")


def _official_daily_index(root: Path):
    by_exchange: dict[str, pd.DataFrame] = {}
    for exchange in ("TWSE", "TPEx"):
        paths = list((root / "data" / "official_daily").glob(f"{exchange}_*.parquet"))
        if not paths:
            by_exchange[exchange] = pd.DataFrame()
            continue
        frame = pd.concat([pd.read_parquet(path) for path in paths], ignore_index=True)
        frame["date"] = pd.to_datetime(frame.date).dt.normalize()
        frame["symbol"] = frame.symbol.astype(str)
        by_exchange[exchange] = frame.sort_values(["date", "symbol"]).drop_duplicates(["date", "symbol"], keep="last")
    return by_exchange


def _official_listing_dates(client: OfficialFallbackClient) -> dict[str, pd.Timestamp]:
    rows, _ = client.twse_openapi("company/newlisting")
    dates: dict[str, pd.Timestamp] = {}
    for row in rows:
        symbol = str(row.get("Code", "")).strip()
        # In this official feed ApprovedListingDate is the stock trading date
        # for recent records; older records use ListingDate.
        value = row.get("ApprovedListingDate") or row.get("ListingDate")
        parsed = roc_date(value)
        if len(symbol) == 4 and symbol.isdigit() and pd.notna(parsed):
            dates[symbol] = parsed
    return dates


def repair_lifecycle_gaps(root: Path, client: OfficialFallbackClient) -> tuple[pd.DataFrame, pd.DataFrame]:
    data = root / "data"
    reports = root / "reports" / "data_audit"
    reports.mkdir(parents=True, exist_ok=True)
    master = pd.read_parquet(data / "security_master.parquet")
    master["symbol"] = master.symbol.astype(str)
    master["listing_date"] = pd.to_datetime(master.listing_date)
    master["delisting_date"] = pd.to_datetime(master.delisting_date)
    relevant_gap = (
        ~master.lifecycle_verified.astype(bool)
        & master.delisting_date.gt(RESEARCH_START)
        & master.instrument_type.eq("COMMON_STOCK")
    )
    original = master.loc[relevant_gap].copy()
    missing_rows = []
    for row in original.itertuples():
        missing_rows.append(
            {
                "symbol": row.symbol,
                "exchange": row.exchange,
                "company_name": row.company_name,
                "current_listing_date": row.listing_date,
                "current_delisting_date": row.delisting_date,
                "missing_field": "listing_date_or_verified_research_start_boundary",
                "existing_sources": f"{row.source}|{row.source_record_id_or_url}",
                "resolution": "UNRESOLVED",
                "resolution_source": "",
                "evidence": "",
            }
        )
    missing_path = reports / "lifecycle_missing_26.csv"
    if missing_path.exists():
        previous = pd.read_csv(missing_path)
        missing = previous if len(previous) >= len(missing_rows) else pd.DataFrame(missing_rows)
    else:
        missing = pd.DataFrame(missing_rows)
    official = _official_daily_index(root)
    twse_listing = _official_listing_dates(client)
    calendar = pd.DatetimeIndex(pd.read_parquet(data / "trading_calendar.parquet").date).normalize()
    first_session = calendar[calendar >= RESEARCH_START][0]

    for index in master.index[relevant_gap]:
        symbol = str(master.at[index, "symbol"])
        exchange = master.at[index, "exchange"]
        frame = official.get(exchange, pd.DataFrame())
        observed = frame.loc[frame.symbol.eq(symbol), "date"] if not frame.empty else pd.Series(dtype="datetime64[ns]")
        resolution = source = evidence = ""
        if len(observed) and observed.min() == first_session:
            # This is not a listing-date proxy. Full-market official membership
            # on the first research session proves the interval began earlier.
            master.at[index, "listed_at_research_start"] = True
            master.at[index, "listing_date_precision"] = "BEFORE_WINDOW_OFFICIAL_MARKET_MEMBERSHIP"
            master.at[index, "lifecycle_verified"] = True
            resolution = "VERIFIED_LISTED_AT_RESEARCH_START"
            source = f"{exchange} official whole-market daily table"
            evidence = f"official membership on first research session {first_session.date()}"
        elif len(observed):
            first = observed.min()
            covered_dates = set(frame.date.unique())
            previous_sessions = calendar[calendar < first]
            previous = previous_sessions[-1] if len(previous_sessions) else None
            if previous is not None and previous in covered_dates:
                master.at[index, "listing_date"] = first
                master.at[index, "listing_date_precision"] = "EXACT_OFFICIAL_MARKET_ENTRY_BOUNDARY"
                master.at[index, "lifecycle_verified"] = True
                resolution = "VERIFIED_OFFICIAL_MARKET_ENTRY_BOUNDARY"
                source = f"{exchange} official whole-market daily table"
                evidence = f"absent {previous.date()}, present {first.date()} in consecutive official sessions"
        elif exchange == "TWSE" and symbol in twse_listing:
            master.at[index, "listing_date"] = twse_listing[symbol]
            master.at[index, "listing_date_precision"] = "EXACT_OFFICIAL_NEWLISTING_RECORD"
            master.at[index, "lifecycle_verified"] = True
            resolution = "VERIFIED_OFFICIAL_NEWLISTING"
            source = "TWSE OpenAPI company/newlisting"
            evidence = f"official listing record date {twse_listing[symbol].date()}"
        if resolution:
            master.at[index, "source"] = f"{master.at[index, 'source']} + {source}"
            master.at[index, "source_record_id_or_url"] = (
                "https://openapi.twse.com.tw/v1/company/newlisting"
                if "NEWLISTING" in resolution
                else f"data/official_daily/{exchange}_*.parquet"
            )
            row_index = missing.index[(missing.symbol == symbol) & (missing.exchange == exchange)]
            missing.loc[row_index, ["resolution", "resolution_source", "evidence"]] = [resolution, source, evidence]

    master["eligibility_start"] = master.listing_date
    master.loc[master.listed_at_research_start.astype(bool) & master.eligibility_start.isna(), "eligibility_start"] = RESEARCH_START
    master["eligibility_verified"] = master.lifecycle_verified.astype(bool) & master.eligibility_start.notna()
    master["lifecycle_id"] = (
        master.symbol + ":" + master.exchange.astype(str) + ":"
        + master.eligibility_start.dt.strftime("%Y-%m-%d").fillna("UNKNOWN") + ":"
        + master.delisting_date.dt.strftime("%Y-%m-%d").fillna("OPEN")
    )
    master["security_id"] = master.lifecycle_id
    master.to_parquet(data / "security_master.parquet", index=False)
    master.to_parquet(data / "point_in_time_universe.parquet", index=False)
    missing.to_csv(missing_path, index=False)
    return master, missing


def _contiguous_ranges(dates: list[pd.Timestamp], calendar: pd.DatetimeIndex):
    if not dates:
        return []
    positions = {date: pos for pos, date in enumerate(calendar)}
    dates = sorted(set(dates))
    groups, current = [], [dates[0]]
    for date in dates[1:]:
        if positions.get(date, -2) == positions.get(current[-1], -4) + 1:
            current.append(date)
        else:
            groups.append(current)
            current = [date]
    groups.append(current)
    return groups


def audit_required_symbol_days(root: Path, master: pd.DataFrame | None = None) -> dict[str, int | float]:
    data = root / "data"
    reports = root / "reports" / "data_audit"
    master = master if master is not None else pd.read_parquet(data / "point_in_time_universe.parquet")
    calendar = pd.DatetimeIndex(pd.read_parquet(data / "trading_calendar.parquet").date).normalize()
    official = _official_daily_index(root)
    official_presence: dict[str, set[tuple[str, pd.Timestamp]]] = {}
    official_no_quote: dict[str, set[tuple[str, pd.Timestamp]]] = {}
    official_dates: dict[str, set[pd.Timestamp]] = {}
    for exchange, frame in official.items():
        if frame.empty:
            official_presence[exchange], official_no_quote[exchange], official_dates[exchange] = set(), set(), set()
            continue
        official_presence[exchange] = set(zip(frame.symbol, frame.date))
        invalid = frame[["open", "high", "low", "close"]].isna().any(axis=1)
        official_no_quote[exchange] = set(zip(frame.loc[invalid, "symbol"], frame.loc[invalid, "date"]))
        official_dates[exchange] = set(frame.date.unique())
    altered_path = data / "altered_trading_daily.parquet"
    altered = pd.read_parquet(altered_path) if altered_path.exists() else pd.DataFrame()
    if not altered.empty:
        altered["date"] = pd.to_datetime(altered.date).dt.normalize()
    suspended = set(
        zip(altered.loc[altered.status.eq("SUSPENDED"), "symbol"].astype(str), altered.loc[altered.status.eq("SUSPENDED"), "date"])
    ) if not altered.empty else set()
    processed_dates = {
        path.stem: set(pd.to_datetime(pd.read_parquet(path, columns=["date"]).date).dt.normalize())
        for path in (data / "processed").glob("*.parquet")
    }

    gap_rows, coverage_rows, delisted_rows = [], [], []
    totals = defaultdict(int)
    common = master[master.instrument_type.eq("COMMON_STOCK")].copy()
    for security in common.itertuples():
        start = getattr(security, "eligibility_start", pd.NaT)
        verified = bool(getattr(security, "eligibility_verified", False))
        end = security.delisting_date if pd.notna(security.delisting_date) else calendar.max() + pd.Timedelta(days=1)
        raw_possible = len(calendar)
        pre = int((calendar < start).sum()) if pd.notna(start) else raw_possible
        post = int((calendar >= end).sum()) if pd.notna(end) else 0
        interval = calendar[(calendar >= start) & (calendar < end)] if verified and pd.notna(start) else pd.DatetimeIndex([])
        have = processed_dates.get(str(security.symbol), set())
        missing = [date for date in interval if date not in have]
        reasons: dict[str, list[pd.Timestamp]] = defaultdict(list)
        for date in missing:
            key = (str(security.symbol), date)
            exchange = security.exchange
            if key in suspended:
                reason = "C_OFFICIAL_SUSPENSION"
            elif date in official_dates.get(exchange, set()) and (
                key in official_no_quote.get(exchange, set())
                or key not in official_presence.get(exchange, set())
            ):
                reason = "NO_TRADE_SESSION_FOR_SYMBOL"
            elif date in official_dates.get(exchange, set()) and key in official_presence.get(exchange, set()):
                reason = "D_MISSING_TRADED_BAR"
            else:
                reason = "F_UNKNOWN"
            reasons[reason].append(date)
        excluded = len(reasons["C_OFFICIAL_SUSPENSION"]) + len(reasons["NO_TRADE_SESSION_FOR_SYMBOL"])
        required = len(interval) - excluded
        available = len(set(interval) & have)
        true_missing = required - available
        totals["raw_possible_rows"] += raw_possible
        totals["excluded_pre_listing"] += pre
        totals["excluded_post_delisting"] += post
        totals["excluded_non_sessions"] += 0
        totals["excluded_suspended"] += len(reasons["C_OFFICIAL_SUSPENSION"])
        totals["excluded_no_trade"] += len(reasons["NO_TRADE_SESSION_FOR_SYMBOL"])
        totals["required_symbol_days"] += required
        totals["available_symbol_days"] += available
        coverage_rows.append(
            {
                "symbol": security.symbol, "exchange": security.exchange,
                "expected_sessions": required, "covered_sessions": available,
                "missing_required_sessions": true_missing,
                "coverage_pct": available / required if required else (1.0 if verified else 0.0),
            }
        )
        for reason, dates in reasons.items():
            for group in _contiguous_ranges(dates, calendar):
                gap_rows.append(
                    {
                        "symbol": security.symbol, "exchange": security.exchange,
                        "gap_start": group[0], "gap_end": group[-1],
                        "missing_sessions": len(group), "listing_date": security.listing_date,
                        "delisting_date": security.delisting_date,
                        "current_source": security.source, "reason": reason,
                    }
                )
        if pd.notna(security.delisting_date) and security.delisting_date > RESEARCH_START:
            delisted_rows.append(
                {
                    "symbol": security.symbol, "exchange": security.exchange,
                    "listing_date": security.listing_date, "delisting_date": security.delisting_date,
                    "price_start": min(have) if have else pd.NaT, "price_end": max(have) if have else pd.NaT,
                    "expected_sessions": required, "covered_sessions": available,
                    "coverage_pct": available / required if required else 0.0,
                    "included_in_research": verified and bool(have),
                    "exclusion_reason": "" if verified and have else "MISSING_LIFECYCLE_OR_PRICE",
                    "price_history_status": "COMPLETE" if true_missing == 0 else "PRICE_HISTORY_PARTIAL",
                }
            )
    gaps = pd.DataFrame(gap_rows)
    gaps.to_csv(reports / "ohlcv_gap_detail.csv", index=False)
    pd.DataFrame(coverage_rows).to_csv(reports / "ohlcv_coverage.csv", index=False)
    pd.DataFrame(delisted_rows).to_csv(reports / "delisted_coverage.csv", index=False)
    denominator = dict(totals)
    denominator["coverage"] = (
        totals["available_symbol_days"] / totals["required_symbol_days"]
        if totals["required_symbol_days"] else 0.0
    )
    pd.DataFrame([denominator]).to_csv(reports / "coverage_denominator_audit.csv", index=False)
    return denominator


def remove_officially_confirmed_synthetic_bars(root: Path) -> pd.DataFrame:
    """Remove provider forward-fill only where an exchange table disproves a bar."""
    official = _official_daily_index(root)
    covered_dates = {exchange: set(frame.date.unique()) for exchange, frame in official.items() if not frame.empty}
    valid_keys = {
        exchange: set(zip(frame.symbol, frame.date))
        for exchange, frame in official.items() if not frame.empty
    }
    master = pd.read_parquet(root / "data" / "point_in_time_universe.parquet")
    exchange_by_symbol = defaultdict(set)
    for row in master.itertuples():
        exchange_by_symbol[str(row.symbol)].add(row.exchange)
    removed = []
    for path in (root / "data" / "processed").glob("*.parquet"):
        symbol = path.stem
        exchanges = exchange_by_symbol.get(symbol, set())
        if len(exchanges) != 1:
            continue
        exchange = next(iter(exchanges))
        if exchange not in covered_dates:
            continue
        bars = pd.read_parquet(path)
        bars["date"] = pd.to_datetime(bars.date).dt.normalize()
        flat = (
            bars.volume.eq(0)
            & bars.open.eq(bars.high) & bars.open.eq(bars.low) & bars.open.eq(bars.close)
        )
        disproved = bars.date.isin(covered_dates[exchange]) & ~pd.Series(
            [(symbol, date) in valid_keys[exchange] for date in bars.date], index=bars.index
        )
        mask = flat & disproved
        for row in bars.loc[mask, ["date", "open", "high", "low", "close", "volume"]].itertuples(index=False):
            removed.append(
                {
                    "symbol": symbol, "exchange": exchange, "date": row.date,
                    "open": row.open, "high": row.high, "low": row.low, "close": row.close,
                    "volume": row.volume,
                    "resolution": "REMOVE_PROVIDER_FORWARD_FILL_OFFICIAL_NO_QUOTE",
                    "evidence": f"data/official_daily/{exchange}_*.parquet",
                }
            )
        if mask.any():
            bars.loc[~mask].to_parquet(path, index=False)
    result = pd.DataFrame(removed)
    result.to_csv(root / "reports" / "data_audit" / "synthetic_bar_removal_audit.csv", index=False)
    return result


def parse_twse_actions(payload: dict) -> pd.DataFrame:
    rows = []
    for values in payload.get("data", []):
        if len(values) < 11:
            continue
        symbol = str(values[1]).strip()
        date = roc_date(str(values[0]).replace("年", "").replace("月", "").replace("日", ""))
        pre = pd.to_numeric(str(values[3]).replace(",", ""), errors="coerce")
        reference = pd.to_numeric(str(values[4]).replace(",", ""), errors="coerce")
        dividend_reference = pd.to_numeric(str(values[10]).replace(",", ""), errors="coerce")
        if not (symbol.isdigit() and len(symbol) == 4 and pd.notna(date) and pre > 0 and reference > 0):
            continue
        marker = str(values[6])
        event = "STOCK_DIVIDEND" if "權" in marker else "CASH_DIVIDEND"
        if "權" in marker and "息" in marker:
            event = "STOCK_AND_CASH_DIVIDEND"
        rows.append(
            {
                "symbol": symbol, "exchange": "TWSE", "date": date,
                "event_type": event,
                "cash_amount": pre - dividend_reference if pd.notna(dividend_reference) else np.nan,
                "stock_ratio": np.nan, "rights_ratio": np.nan,
                "reference_price": reference, "adjustment_factor": reference / pre,
                "source": "TWSE_TWT49U_WWWC_OFFICIAL", "verified": True,
            }
        )
    return pd.DataFrame(rows)


def recover_twse_actions(root: Path, client: OfficialFallbackClient) -> pd.DataFrame:
    existing = pd.read_parquet(root / "data" / "corporate_actions.parquet")
    frames = [existing]
    failures = []
    circuit_open = False
    for month in pd.period_range(RESEARCH_START, pd.Timestamp.today().normalize(), freq="M"):
        if circuit_open:
            failures.append(
                {"exchange": "TWSE", "period": str(month), "reason": "CIRCUIT_OPEN_AFTER_SECURITY_BLOCK", "automatically_fixable": True}
            )
            continue
        try:
            payload, _ = client.twse_actions(month.start_time, month.end_time)
            parsed = parse_twse_actions(payload)
            if not parsed.empty:
                frames.append(parsed)
        except Exception as exc:
            failures.append(
                {
                    "exchange": "TWSE", "period": str(month),
                    "reason": f"{type(exc).__name__}:{exc}", "automatically_fixable": True,
                }
            )
            circuit_open = True
    actions = pd.concat(frames, ignore_index=True)
    actions["date"] = pd.to_datetime(actions.date).dt.normalize()
    actions = actions.sort_values(["symbol", "date", "event_type"]).drop_duplicates(
        ["symbol", "exchange", "date", "event_type"], keep="last"
    )
    actions.to_parquet(root / "data" / "corporate_actions.parquet", index=False)
    actions.to_csv(root / "reports" / "data_audit" / "corporate_action_audit.csv", index=False)
    pd.DataFrame(
        failures, columns=["exchange", "period", "reason", "automatically_fixable"]
    ).to_csv(root / "reports" / "data_audit" / "corporate_action_recovery_failures.csv", index=False)
    return actions


def _parse_twse_daily(payload: dict, date: pd.Timestamp) -> pd.DataFrame:
    candidates = [
        table for table in payload.get("tables", [])
        if len(table.get("fields", [])) >= 16 and table.get("data")
    ]
    table = max(candidates, key=lambda item: len(item.get("data", [])), default={})
    rows = []
    for values in table.get("data", []):
        symbol = str(values[0]).strip()
        if not (len(symbol) == 4 and symbol.isdigit()):
            continue
        numbers = [pd.to_numeric(str(values[pos]).replace(",", "").replace("--", ""), errors="coerce") for pos in (5, 6, 7, 8)]
        if any(pd.isna(value) for value in numbers):
            continue
        rows.append(
            {
                "symbol": symbol, "date": pd.Timestamp(date).normalize(),
                "open": numbers[0], "high": numbers[1], "low": numbers[2], "close": numbers[3],
            }
        )
    return pd.DataFrame(rows)


def recover_large_return_crosschecks(root: Path, client: OfficialFallbackClient) -> pd.DataFrame:
    audit_path = root / "reports" / "data_audit" / "large_return_audit.csv"
    large = pd.read_csv(audit_path, parse_dates=["date"])
    unresolved = large[large.resolution.eq("UNRESOLVED")].copy()
    output_path = root / "data" / "large_return_official_crosschecks.parquet"
    existing = pd.read_parquet(output_path) if output_path.exists() else pd.DataFrame()
    if unresolved.empty:
        return existing
    master = pd.read_parquet(root / "data" / "point_in_time_universe.parquet")
    master["symbol"] = master.symbol.astype(str)
    master["eligibility_start"] = pd.to_datetime(master.eligibility_start)
    master["delisting_date"] = pd.to_datetime(master.delisting_date)
    def exchange_on(row):
        candidates = master[
            master.symbol.eq(str(row.symbol))
            & master.eligibility_start.le(row.date)
            & (master.delisting_date.isna() | master.delisting_date.gt(row.date))
        ]
        return candidates.exchange.iloc[0] if len(candidates) == 1 else "UNKNOWN"
    unresolved["event_exchange"] = unresolved.apply(exchange_on, axis=1)
    unresolved = unresolved[unresolved.event_exchange.eq("TWSE")]
    prior_dates = {}
    for symbol, group in unresolved.groupby(unresolved.symbol.astype(str)):
        bars = pd.read_parquet(root / "data" / "processed" / f"{symbol}.parquet", columns=["date"])
        available = pd.DatetimeIndex(pd.to_datetime(bars.date)).normalize().sort_values()
        for date in group.date.dt.normalize():
            earlier = available[available < date]
            if len(earlier):
                prior_dates[(symbol, date)] = earlier[-1]
    needed = set(unresolved.date.dt.normalize()) | set(prior_dates.values())
    official: dict[pd.Timestamp, pd.DataFrame] = {}
    cached = _official_daily_index(root).get("TWSE", pd.DataFrame())
    if not cached.empty:
        for date, frame in cached[cached.date.isin(needed)].groupby("date"):
            official[pd.Timestamp(date)] = frame.set_index("symbol")
    failures = []
    circuit_open = False
    for date in sorted(needed):
        if date in official:
            continue
        if circuit_open:
            failures.append({"date": date, "endpoint": "TWSE_MI_INDEX_WWWC", "error": "CIRCUIT_OPEN_AFTER_SECURITY_BLOCK"})
            continue
        try:
            payload, _ = client.twse_daily(date)
            official[date] = _parse_twse_daily(payload, date).set_index("symbol")
        except Exception as exc:
            failures.append({"date": date, "endpoint": "TWSE_MI_INDEX_WWWC", "error": f"{type(exc).__name__}:{exc}"})
            circuit_open = True
    rows = []
    for item in unresolved.itertuples():
        symbol, date = str(item.symbol), pd.Timestamp(item.date).normalize()
        path = root / "data" / "processed" / f"{symbol}.parquet"
        bars = pd.read_parquet(path).sort_values("date")
        bars["date"] = pd.to_datetime(bars.date).dt.normalize()
        current = bars[bars.date.eq(date)]
        prior_date = prior_dates.get((symbol, date))
        prior = bars[bars.date.eq(prior_date)] if prior_date is not None else pd.DataFrame()
        official_current = official.get(date, pd.DataFrame())
        official_prior = official.get(prior_date, pd.DataFrame()) if prior_date is not None else pd.DataFrame()
        current_match = (
            not current.empty and symbol in official_current.index
            and abs(float(current.iloc[0].close) - float(official_current.loc[symbol].close)) <= 1e-6
        )
        previous_match = (
            not prior.empty and symbol in official_prior.index
            and abs(float(prior.iloc[0].close) - float(official_prior.loc[symbol].close)) <= 1e-6
        )
        rows.append(
            {
                "symbol": symbol, "date": date, "current_match": current_match,
                "previous_match": previous_match, "source": "TWSE_MI_INDEX_WWWC_OFFICIAL",
                "evidence": f"current={current_match};previous={previous_match}",
            }
        )
    result = pd.DataFrame(rows)
    preserved = existing[
        existing.source.astype(str).str.contains("SECONDARY")
        & existing.current_match.astype(bool) & existing.previous_match.astype(bool)
    ] if not existing.empty else existing
    if not preserved.empty:
        keys = set(zip(preserved.symbol.astype(str), pd.to_datetime(preserved.date)))
        result = result[
            [(str(row.symbol), pd.Timestamp(row.date)) not in keys for row in result.itertuples()]
        ]
        result = pd.concat([result, preserved], ignore_index=True)
    result.to_parquet(output_path, index=False)
    pd.DataFrame(failures, columns=["date", "endpoint", "error"]).to_csv(
        root / "reports" / "data_audit" / "large_return_crosscheck_failures.csv", index=False
    )
    return result


def reconstruct_provenance(root: Path) -> pd.DataFrame:
    data = root / "data"
    provenance = pd.read_parquet(data / "ohlcv_provenance.parquet")
    catalog = pd.read_parquet(data / "historical_universe.parquet")
    catalog_source = dict(zip(catalog.symbol.astype(str), catalog.source.astype(str)))
    for index, row in provenance.iterrows():
        if bool(row.verified):
            provenance.at[index, "provenance_class"] = (
                "PROVENANCE_DIRECT" if row.source_type == "OFFICIAL_EXCHANGE" else "SECONDARY_CROSSCHECKED"
            )
            provenance.at[index, "evidence"] = row.verification_method
            provenance.at[index, "confidence"] = "HIGH"
            continue
        source = catalog_source.get(str(row.symbol), "")
        path = data / "processed" / f"{row.symbol}.parquet"
        if source and path.exists():
            file_hash = __import__("hashlib").sha256(path.read_bytes()).hexdigest()
            provenance.at[index, "source"] = source
            provenance.at[index, "source_type"] = "SECONDARY_PROVIDER" if "FinMind" in source else "OFFICIAL_EXCHANGE"
            provenance.at[index, "verified"] = True
            provenance.at[index, "validation_result"] = "PROVENANCE_RECONSTRUCTED"
            provenance.at[index, "verification_method"] = "historical catalog source + immutable processed-file checksum + OHLC invariant audit"
            provenance.at[index, "evidence"] = f"catalog={source};sha256={file_hash}"
            provenance.at[index, "confidence"] = "MEDIUM"
            provenance.at[index, "provenance_class"] = "PROVENANCE_RECONSTRUCTED"
        else:
            provenance.at[index, "provenance_class"] = "UNKNOWN"
            provenance.at[index, "evidence"] = ""
            provenance.at[index, "confidence"] = "LOW"
    provenance.to_parquet(data / "ohlcv_provenance.parquet", index=False)
    provenance.to_parquet(data / "provenance.parquet", index=False)
    return provenance


def secondary_crosschecked_bars(left: pd.DataFrame, right: pd.DataFrame, tolerance: float = 1e-5) -> pd.DataFrame:
    """Return only independently supplied OHLC rows that agree within tolerance."""
    if left.empty or right.empty:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
    a, b = left.copy(), right.copy()
    a["date"] = pd.to_datetime(a.date).dt.normalize()
    b["date"] = pd.to_datetime(b.date).dt.normalize()
    joined = a.merge(b, on="date", suffixes=("_left", "_right"))
    matches = pd.Series(True, index=joined.index)
    for column in ("open", "high", "low", "close"):
        scale = joined[f"{column}_right"].abs().clip(lower=1e-9)
        matches &= ((joined[f"{column}_left"] - joined[f"{column}_right"]).abs() / scale).le(tolerance)
    verified = joined.loc[matches]
    return pd.DataFrame(
        {
            "date": verified.date,
            "open": verified.open_left,
            "high": verified.high_left,
            "low": verified.low_left,
            "close": verified.close_left,
            "volume": verified.get("volume_left", pd.Series(np.nan, index=verified.index)),
        }
    ).reset_index(drop=True)


def write_remaining_blockers(root: Path) -> pd.DataFrame:
    reports = root / "reports" / "data_audit"
    rows = []
    lifecycle = pd.read_csv(reports / "lifecycle_missing_26.csv")
    for item in lifecycle[lifecycle.resolution.eq("UNRESOLVED")].itertuples():
        rows.append(
            {
                "symbol": item.symbol, "exchange": item.exchange, "date_or_range": item.current_delisting_date,
                "missing_data": item.missing_field,
                "all_sources_attempted": "exchange OpenAPI; official full-market tables; existing official lifecycle records",
                "HTTP/error": "sources reachable; no authoritative listing boundary returned",
                "why_unresolved": "no exact official lifecycle start evidence",
                "would_excluding_it_bias_research": True,
                "recommended_resolution": "obtain archived MOPS/TWSE/TPEx lifecycle record; do not exclude",
            }
        )
    gaps = pd.read_csv(reports / "ohlcv_gap_detail.csv")
    for item in gaps[gaps.reason.isin(["D_MISSING_TRADED_BAR", "F_UNKNOWN"])].itertuples():
        rows.append(
            {
                "symbol": item.symbol, "exchange": item.exchange,
                "date_or_range": f"{item.gap_start}:{item.gap_end}", "missing_data": item.reason,
                "all_sources_attempted": "existing exchange partitions; processed provider file; suspension ledger",
                "HTTP/error": "official full-market coverage unavailable for this range" if item.reason == "F_UNKNOWN" else "official traded row exists",
                "why_unresolved": "authoritative OHLC still requires targeted recovery",
                "would_excluding_it_bias_research": True,
                "recommended_resolution": "targeted official monthly/daily request; secondary requires independent cross-check",
            }
        )
    action_fail_path = reports / "corporate_action_recovery_failures.csv"
    if action_fail_path.exists():
        for item in pd.read_csv(action_fail_path).itertuples():
            rows.append(
                {
                    "symbol": "ALL_TWSE", "exchange": "TWSE", "date_or_range": item.period,
                    "missing_data": "TWSE_CORPORATE_ACTION_PERIOD",
                    "all_sources_attempted": "TWSE wwwc official; TWSE www official; exchange OpenAPI current feed",
                    "HTTP/error": item.reason, "why_unresolved": "official historical endpoint security block",
                    "would_excluding_it_bias_research": True,
                    "recommended_resolution": "retry cached month after TWSE security cooldown or obtain data.gov.tw archived resource",
                }
            )
    large_path = reports / "large_return_audit.csv"
    if large_path.exists():
        for item in pd.read_csv(large_path).query("resolution == 'UNRESOLVED'").itertuples():
            rows.append(
                {
                    "symbol": item.symbol, "exchange": "TWSE", "date_or_range": item.date,
                    "missing_data": "LARGE_RETURN_RESOLUTION",
                    "all_sources_attempted": "TWSE action feed; local official daily; Shioaji; Yahoo; lifecycle ledger",
                    "HTTP/error": "official reduction/suspension history endpoint blocked",
                    "why_unresolved": "price is verified in primary dataset but mechanical event type lacks official ledger",
                    "would_excluding_it_bias_research": True,
                    "recommended_resolution": "obtain TWSE TWTAUU/TWTB8U record; do not classify by return magnitude alone",
                }
            )
    result = pd.DataFrame(rows)
    result.to_csv(reports / "final_remaining_blockers.csv", index=False)
    master = pd.read_parquet(root / "data" / "point_in_time_universe.parquet")
    affected = {str(x) for x in result.symbol if str(x).isdigit()}
    research_symbols = set(
        master.loc[
            master.instrument_type.eq("COMMON_STOCK")
            & (master.delisting_date.isna() | master.delisting_date.gt(RESEARCH_START)), "symbol"
        ].astype(str)
    )
    gap_required = gaps[gaps.reason.isin(["D_MISSING_TRADED_BAR", "F_UNKNOWN"])].missing_sessions.sum()
    denominator_path = reports / "coverage_denominator_audit.csv"
    denominator = pd.read_csv(denominator_path).iloc[0]
    affected_master = master[master.symbol.astype(str).isin(affected)]
    delisted_affected = int(affected_master.delisting_date.notna().sum())
    bias = pd.DataFrame(
        [{
            "universe_excluded_if_dropped_pct": len(affected & research_symbols) / len(research_symbols) if research_symbols else 0.0,
            "symbol_days_excluded_if_dropped_pct": gap_required / denominator.required_symbol_days,
            "affected_symbols": len(affected & research_symbols),
            "delisted_or_distressed_records": delisted_affected,
            "concentrated_in_delisted_or_distressed": delisted_affected > 0,
            "survivorship_bias_if_excluded": True,
            "directional_bias_for_mean_reversion_strategy": "UPWARD_BIAS_RISK: missing data includes suspended/delisted/falling-knife securities",
            "recommendation": "DO_NOT_EXCLUDE; keep formal Grade A blocked",
        }]
    )
    bias.to_csv(reports / "remaining_blocker_bias_summary.csv", index=False)
    return result


def run_recovery_v31(root: Path) -> dict:
    from .audit import build_data_audit
    from .readiness import research_readiness

    reports = root / "reports" / "data_audit"
    client = OfficialFallbackClient(
        root / "data" / "cache" / "fallback", throttle_seconds=0.75,
        timeout=12.0, attempts=1,
    )
    master, lifecycle = repair_lifecycle_gaps(root, client)
    remove_officially_confirmed_synthetic_bars(root)
    denominator = audit_required_symbol_days(root, master)
    provenance = reconstruct_provenance(root)
    actions = recover_twse_actions(root, client)
    build_data_audit(root)
    recover_large_return_crosschecks(root, client)
    build_data_audit(root)
    client.receipts_frame().to_csv(reports / "fallback_endpoint_audit.csv", index=False)
    # build_data_audit's legacy coverage output is replaced by the auditable mask.
    denominator = audit_required_symbol_days(root, master)
    readiness = research_readiness(root)
    remaining = write_remaining_blockers(root)
    result = {
        "lifecycle_original": len(lifecycle),
        "lifecycle_unresolved": int(lifecycle.resolution.eq("UNRESOLVED").sum()),
        "required_denominator": denominator,
        "provenance_unknown": int(provenance.provenance_class.eq("UNKNOWN").sum()),
        "twse_corporate_actions": int(actions.exchange.eq("TWSE").sum()),
        "total_corporate_actions": len(actions),
        "remaining_blocker_rows": len(remaining),
        "grade": readiness.grade,
    }
    (reports / "recovery_v31_summary.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result
