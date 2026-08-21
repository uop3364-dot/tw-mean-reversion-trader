from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time

import numpy as np
import pandas as pd
import requests

from .historical_universe import tpex_delisted, twse_delisted
from .official_daily_provider import fetch_tpex, fetch_twse
from .universe_provider import OfficialUniverseProvider
from .corporate_actions import CorporateActionAdjuster


RESEARCH_START = pd.Timestamp("2018-01-02")
DELISTED_START = pd.Timestamp("2017-01-01")


def _number(value):
    return pd.to_numeric(str(value).replace(",", "").replace("--", ""), errors="coerce")


def _get(url, params=None, attempts=4):
    error = None
    for attempt in range(attempts):
        try:
            response = requests.get(
                url,
                params=params,
                timeout=60,
                headers={"User-Agent": "tw-mean-reversion-research/3.0"},
            )
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            error = exc
            time.sleep(1.5 * (attempt + 1))
    raise error


def _months(start, end):
    return pd.period_range(pd.Timestamp(start), pd.Timestamp(end), freq="M")


def collect_delisted(start="2017-01-01", end=None):
    end = pd.Timestamp(end or pd.Timestamp.today()).normalize()
    tw = twse_delisted()
    otc = tpex_delisted(pd.Timestamp(start).year, end.year)
    frame = pd.concat([tw, otc], ignore_index=True)
    frame["symbol"] = frame.symbol.astype(str)
    frame["company_name"] = frame.get("name", "")
    frame["listing_date"] = pd.NaT
    frame["delisting_date"] = pd.to_datetime(frame.delisting_date)
    frame["instrument_type"] = np.where(
        frame.symbol.str.startswith("91") | frame.company_name.str.contains(r"(?:-DR|TDR)", case=False, na=False),
        "TDR",
        "COMMON_STOCK",
    )
    frame["reason"] = frame.get("reason", "")
    frame["verified"] = True
    frame = frame[
        frame.delisting_date.between(pd.Timestamp(start), end)
        & frame.symbol.str.fullmatch(r"\d{4}")
    ]
    return frame[
        [
            "symbol", "company_name", "exchange", "listing_date",
            "delisting_date", "instrument_type", "reason", "source", "verified",
        ]
    ].sort_values(["exchange", "delisting_date", "symbol"]).drop_duplicates(["exchange", "symbol"], keep="last")


def build_security_master(root: Path):
    data = root / "data"
    current = OfficialUniverseProvider().current().rename(columns={"name": "company_name"})
    current["instrument_type"] = "COMMON_STOCK"
    current["delisting_date"] = pd.NaT
    current["source_record_id_or_url"] = np.where(
        current.exchange.eq("TWSE"),
        "https://openapi.twse.com.tw/v1/opendata/t187ap03_L",
        "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O",
    )
    current["verified"] = True
    current["listing_date_precision"] = "EXACT_OFFICIAL"
    current["listed_at_research_start"] = False

    delisted = collect_delisted(DELISTED_START)
    old_snapshot = pd.read_parquet(data / "universe.parquet") if (data / "universe.parquet").exists() else pd.DataFrame()
    known_dates = (
        old_snapshot.assign(symbol=old_snapshot.symbol.astype(str)).set_index(["symbol", "exchange"]).listing_date
        if not old_snapshot.empty and "listing_date" in old_snapshot else pd.Series(dtype="datetime64[ns]")
    )
    observations_path = data / "historical_observations.parquet"
    hist = pd.read_parquet(observations_path if observations_path.exists() else data / "historical_universe.parquet")
    observed = hist.assign(symbol=hist.symbol.astype(str)).set_index(["symbol", "exchange"]).first_seen
    keys = list(zip(delisted.symbol.astype(str), delisted.exchange))
    delisted["listing_date"] = [known_dates.get(key, pd.NaT) for key in keys]
    delisted["first_official_observation"] = [observed.get(key, pd.NaT) for key in keys]
    delisted["listed_at_research_start"] = (
        delisted.listing_date.isna()
        & (pd.to_datetime(delisted.first_official_observation, errors="coerce") <= RESEARCH_START)
    )
    delisted["listing_date_precision"] = np.select(
        [
            delisted.listing_date.notna(),
            delisted.listed_at_research_start,
        ],
        ["EXACT_OFFICIAL", "BEFORE_RESEARCH_WINDOW_OFFICIAL_SESSION_EVIDENCE"],
        default="UNKNOWN",
    )
    delisted["source_record_id_or_url"] = np.where(
        delisted.exchange.eq("TWSE"),
        "https://openapi.twse.com.tw/v1/company/suspendListingCsvAndHtml",
        "https://www.tpex.org.tw/www/zh-tw/company/deListed",
    )
    delisted["verified"] = True
    delisted["lifecycle_verified"] = delisted.listing_date.notna() | delisted.listed_at_research_start
    current["lifecycle_verified"] = True

    columns = [
        "symbol", "company_name", "exchange", "instrument_type", "listing_date",
        "delisting_date", "source", "source_record_id_or_url", "verified",
        "listing_date_precision", "listed_at_research_start", "lifecycle_verified",
    ]
    master = pd.concat([current[columns], delisted[columns]], ignore_index=True)
    master["security_id"] = (
        master.symbol.astype(str) + ":" + master.exchange.astype(str) + ":"
        + master.listing_date.dt.strftime("%Y-%m-%d").fillna("")
        + ":" + master.delisting_date.dt.strftime("%Y-%m-%d").fillna("")
    )
    master = master.sort_values(["symbol", "exchange", "delisting_date"], na_position="last").drop_duplicates("security_id", keep="first")
    master.to_parquet(data / "security_master.parquet", index=False)
    return master


def build_point_in_time_universe(root: Path, master: pd.DataFrame, calendar):
    data = root / "data"
    frame = master.copy()
    frame["eligibility_start"] = frame.listing_date
    frame.loc[frame.listed_at_research_start & frame.eligibility_start.isna(), "eligibility_start"] = RESEARCH_START
    frame["eligibility_verified"] = frame.lifecycle_verified & frame.eligibility_start.notna()
    frame.to_parquet(data / "point_in_time_universe.parquet", index=False)
    sessions = pd.DatetimeIndex(pd.to_datetime(calendar)).normalize()
    rows = []
    for date in sessions:
        expected = (
            frame.instrument_type.eq("COMMON_STOCK")
            & (frame.listing_date.le(date) | frame.listed_at_research_start)
            & (frame.delisting_date.isna() | frame.delisting_date.gt(date))
        )
        covered = expected & frame.eligibility_verified
        expected_count = frame.loc[expected, "symbol"].nunique()
        covered_count = frame.loc[covered, "symbol"].nunique()
        rows.append(
            {
                "date": date,
                "expected_symbols": int(expected_count),
                "covered_symbols": int(covered_count),
                "coverage_pct": covered_count / expected_count if expected_count else 1.0,
            }
        )
    return frame, pd.DataFrame(rows)


def audit_and_repair_off_calendar(root: Path):
    data = root / "data"
    reports = root / "reports" / "data_audit"
    reports.mkdir(parents=True, exist_ok=True)
    detail_path = reports / "off_calendar_detail.csv"
    calendar_path = data / "trading_calendar.parquet"
    if detail_path.exists() and calendar_path.exists():
        cached = pd.read_csv(detail_path, parse_dates=["date"])
        if not cached.empty and not cached.resolution.eq("UNRESOLVED").any():
            return cached, pd.read_parquet(calendar_path)
    hist = pd.read_parquet(data / "historical_universe.parquet")
    exchange = dict(zip(hist.symbol.astype(str), hist.exchange))
    taiex = pd.read_parquet(data / "processed" / "TAIEX.parquet")
    base_calendar = set(pd.to_datetime(taiex.date).dt.normalize())
    candidates = []
    for path in (data / "processed").glob("*.parquet"):
        bars = pd.read_parquet(path)
        bars["date"] = pd.to_datetime(bars.date).dt.normalize()
        extra = bars[~bars.date.isin(base_calendar)]
        for row in extra.itertuples():
            candidates.append(
                {
                    "symbol": path.stem,
                    "exchange": exchange.get(path.stem, "BENCHMARK"),
                    "date": row.date,
                    "source": "PROCESSED_PRE_V3_UNKNOWN",
                    "open": row.open,
                    "high": row.high,
                    "low": row.low,
                    "close": row.close,
                    "volume": row.volume,
                }
            )
    detail = pd.DataFrame(candidates)
    official_by_date = {}
    for date in sorted(detail.date.unique()):
        tw = fetch_twse(pd.Timestamp(date))
        otc = fetch_tpex(pd.Timestamp(date))
        official_by_date[pd.Timestamp(date)] = {"TWSE": tw, "TPEx": otc}
    resolutions = []
    legal_sessions = set(base_calendar)
    erroneous = {}
    for row in detail.itertuples():
        official = official_by_date[row.date].get(row.exchange, [])
        official_row = next((x for x in official if x["symbol"] == row.symbol), None)
        if official_row is not None:
            reason = "A_TRADING_CALENDAR_MISSING_LEGAL_SESSION"
            resolution = "ADD_VERIFIED_OFFICIAL_SESSION"
            legal_sessions.add(row.date)
        elif row.exchange == "BENCHMARK" and any(official_by_date[row.date].values()):
            reason = "A_TRADING_CALENDAR_MISSING_LEGAL_SESSION"
            resolution = "ADD_VERIFIED_OFFICIAL_SESSION"
            legal_sessions.add(row.date)
        elif row.volume == 0 and row.open == row.high == row.low == row.close:
            reason = "C_PROVIDER_SYNTHETIC_NONTRADING_BAR"
            resolution = "REMOVE_CONFIRMED_ERROR"
            erroneous.setdefault(row.symbol, set()).add(row.date)
        else:
            reason = "F_UNRESOLVED"
            resolution = "UNRESOLVED"
        resolutions.append((reason, resolution))
    if len(detail):
        detail[["reason", "resolution"]] = pd.DataFrame(resolutions, index=detail.index)
    for symbol, dates in erroneous.items():
        path = data / "processed" / f"{symbol}.parquet"
        bars = pd.read_parquet(path)
        cleaned = bars[~pd.to_datetime(bars.date).dt.normalize().isin(dates)]
        cleaned.to_parquet(path, index=False)
    calendar = pd.DataFrame({"date": sorted(legal_sessions), "source": "TAIEX_OR_OFFICIAL_DAILY_VERIFIED"})
    calendar.to_parquet(data / "trading_calendar.parquet", index=False)
    detail.to_csv(detail_path, index=False)
    summary = (
        detail.groupby(["date", "exchange", "source"], dropna=False)
        .agg(affected_symbols=("symbol", "nunique"), row_count=("symbol", "size"))
        .reset_index()
    )
    summary.to_csv(reports / "off_calendar_summary.csv", index=False)
    return detail, calendar


def download_corporate_actions(start="2018-01-01", end=None, exchanges=("TWSE", "TPEx")):
    end = pd.Timestamp(end or pd.Timestamp.today()).normalize()
    records = []
    for month in _months(start, end):
        first = month.start_time
        last = min(month.end_time.normalize(), end)
        tw = _get(
            "https://www.twse.com.tw/rwd/en/exRight/TWT49U",
            {"startDate": first.strftime("%Y%m%d"), "endDate": last.strftime("%Y%m%d"), "response": "json"},
        ) if "TWSE" in exchanges else {"data": []}
        for row in tw.get("data", []):
            symbol = str(row[1]).strip()
            if not symbol.isdigit() or len(symbol) != 4:
                continue
            pre, ref, ex_div_ref = _number(row[2]), _number(row[3]), _number(row[7])
            cash = pre - ex_div_ref if pd.notna(pre) and pd.notna(ex_div_ref) else np.nan
            event = "CASH_DIVIDEND" if pd.notna(ref) and pd.notna(ex_div_ref) and abs(ref - ex_div_ref) < 1e-8 else "STOCK_DIVIDEND"
            records.append(
                {
                    "symbol": symbol, "exchange": "TWSE", "date": pd.to_datetime(row[0]),
                    "event_type": event, "cash_amount": cash, "stock_ratio": np.nan,
                    "rights_ratio": np.nan, "reference_price": ref,
                    "adjustment_factor": ref / pre if pre else np.nan,
                    "source": "TWSE TWT49U", "verified": True,
                }
            )
        otc = _get(
            "https://www.tpex.org.tw/www/en-us/bulletin/exDailyQ",
            {"startDate": first.strftime("%Y/%m/%d"), "endDate": last.strftime("%Y/%m/%d"), "response": "json"},
        ) if "TPEx" in exchanges else {"tables": []}
        rows = otc.get("tables", [{}])[0].get("data", []) if otc.get("tables") else []
        for row in rows:
            symbol = str(row[1]).strip()
            if not symbol.isdigit() or len(symbol) != 4:
                continue
            pre, ref = _number(row[2]), _number(row[3])
            stock, cash = _number(row[4]), _number(row[5])
            event = "STOCK_DIVIDEND" if pd.notna(stock) and stock != 0 else "CASH_DIVIDEND"
            records.append(
                {
                    "symbol": symbol, "exchange": "TPEx", "date": pd.to_datetime(row[0]),
                    "event_type": event, "cash_amount": cash, "stock_ratio": np.nan,
                    "rights_ratio": np.nan, "reference_price": ref,
                    "adjustment_factor": ref / pre if pre else np.nan,
                    "source": "TPEx bulletin/exDailyQ", "verified": True,
                }
            )
    tw_reduction = _get(
        "https://www.twse.com.tw/exchangeReport/TWTAUU",
        {"startDate": pd.Timestamp(start).strftime("%Y%m%d"), "endDate": end.strftime("%Y%m%d"), "response": "json"},
    ) if "TWSE" in exchanges else {"data": []}
    for row in tw_reduction.get("data", []):
        symbol = str(row[1]).strip()
        if symbol.isdigit() and len(symbol) == 4:
            pre, ref = _number(row[3]), _number(row[4])
            records.append(
                {
                    "symbol": symbol, "exchange": "TWSE", "date": pd.to_datetime(row[0]),
                    "event_type": "CAPITAL_REDUCTION", "cash_amount": np.nan,
                    "stock_ratio": np.nan, "rights_ratio": np.nan,
                    "reference_price": ref, "adjustment_factor": ref / pre if pre else np.nan,
                    "source": "TWSE TWTAUU", "verified": True,
                }
            )
    otc_reduction = _get(
        "https://www.tpex.org.tw/www/en-us/bulletin/revivt",
        {"startDate": pd.Timestamp(start).strftime("%Y/%m/%d"), "endDate": end.strftime("%Y/%m/%d"), "response": "json"},
    ) if "TPEx" in exchanges else {"tables": []}
    rows = otc_reduction.get("tables", [{}])[0].get("data", []) if otc_reduction.get("tables") else []
    for row in rows:
        symbol = str(row[1]).strip()
        if symbol.isdigit() and len(symbol) == 4:
            pre, ref = _number(row[2]), _number(row[3])
            records.append(
                {
                    "symbol": symbol, "exchange": "TPEx", "date": pd.to_datetime(row[0]),
                    "event_type": "CAPITAL_REDUCTION", "cash_amount": np.nan,
                    "stock_ratio": np.nan, "rights_ratio": np.nan,
                    "reference_price": ref, "adjustment_factor": ref / pre if pre else np.nan,
                    "source": "TPEx bulletin/revivt", "verified": True,
                }
            )
    result = pd.DataFrame(records)
    result = result.dropna(subset=["date", "adjustment_factor"])
    result = result[result.adjustment_factor.gt(0)]
    return result.sort_values(["symbol", "date", "event_type"]).drop_duplicates(["symbol", "date", "event_type"])


def build_provenance(root: Path):
    data = root / "data"
    master = pd.read_parquet(data / "security_master.parquet")
    exchange = master.groupby(master.symbol.astype(str)).exchange.agg(lambda x: "/".join(sorted(set(x)))).to_dict()
    legacy_path = data / "ohlcv_provenance.parquet"
    legacy = pd.read_parquet(legacy_path) if legacy_path.exists() else pd.DataFrame()
    finmind = set(legacy.symbol.astype(str)) if not legacy.empty and "source" in legacy and legacy.source.astype(str).str.contains("FinMind").any() else set()
    catalog = pd.read_parquet(data / "historical_universe.parquet")
    catalog_source = dict(zip(catalog.symbol.astype(str), catalog.source.astype(str))) if "source" in catalog else {}
    verified_overlap = set()
    official_parts = list((data / "official_daily").glob("TWSE_*.parquet"))
    if official_parts:
        official = pd.concat([pd.read_parquet(p) for p in official_parts], ignore_index=True)
        official["date"] = pd.to_datetime(official.date)
        for symbol, sample in official.groupby(official.symbol.astype(str)):
            path = data / "processed" / f"{symbol}.parquet"
            if not path.exists():
                continue
            processed = pd.read_parquet(path)
            joined = sample.merge(processed, on="date", suffixes=("_official", "_processed"))
            if len(joined) >= 20:
                errors = [
                    ((joined[f"{column}_official"] - joined[f"{column}_processed"]).abs() / joined[f"{column}_official"].abs().clip(lower=1e-9)).max()
                    for column in ("open", "high", "low", "close")
                ]
                if max(errors) <= 1e-5:
                    verified_overlap.add(symbol)
    shioaji_path = data / "shioaji_ohlcv_crosscheck.parquet"
    if shioaji_path.exists():
        cross = pd.read_parquet(shioaji_path)
        for symbol, sample in cross.groupby(cross.symbol.astype(str)):
            if len(sample) >= 20 and sample[["open_relative_diff", "high_relative_diff", "low_relative_diff", "close_relative_diff"]].abs().max().max() <= 1e-5:
                verified_overlap.add(symbol)
    rows = []
    for path in (data / "processed").glob("*.parquet"):
        bars = pd.read_parquet(path, columns=["date"])
        symbol = path.stem
        ex = exchange.get(symbol, "BENCHMARK")
        official = ex == "TPEx" and "TPEx" in catalog_source.get(symbol, "")
        source = (
            f"{ex} official whole-market daily tables" if official
            else ("FinMind TaiwanStockPrice" if symbol in finmind else catalog_source.get(symbol, "Yahoo bootstrap"))
        )
        verified = official or symbol in verified_overlap
        rows.append(
            {
                "symbol": symbol, "exchange": ex, "start_date": bars.date.min(),
                "end_date": bars.date.max(),
                "source": source,
                "source_type": "OFFICIAL_EXCHANGE" if official else "SECONDARY_PROVIDER",
                "price_convention": "UNADJUSTED_EXCHANGE" if ex != "BENCHMARK" else "UNKNOWN",
                "download_timestamp": pd.Timestamp.now(tz="Asia/Taipei"),
                "raw_file_reference": f"data/official_daily/{ex}_*.parquet" if official else str(path),
                "verified": verified,
                "verification_method": "official full history" if official else ("symbol-level official/Shioaji overlap + OHLC invariants" if verified else "source known; symbol-level cross-check unavailable"),
                "validation_result": "OFFICIAL_VERIFIED" if official else ("SECONDARY_VERIFIED" if verified else "UNVERIFIED"),
                "repair_reason": "",
            }
        )
    frame = pd.DataFrame(rows)
    frame.to_parquet(data / "ohlcv_provenance.parquet", index=False)
    frame.to_parquet(data / "provenance.parquet", index=False)
    return frame


def build_analysis_prices(root: Path, master: pd.DataFrame, actions: pd.DataFrame):
    source = root / "data" / "processed"
    target = root / "data" / "analysis"
    target.mkdir(parents=True, exist_ok=True)
    adjuster = CorporateActionAdjuster(actions)
    symbols = set(master.loc[master.instrument_type.eq("COMMON_STOCK"), "symbol"].astype(str))
    written = 0
    for symbol in sorted(symbols):
        path = source / f"{symbol}.parquet"
        if not path.exists():
            continue
        layered = adjuster.adjust(symbol, pd.read_parquet(path))
        layered.to_parquet(target / f"{symbol}.parquet", index=False)
        written += 1
    return written


def run_data_recovery(root: Path, workers=6, official_daily=True):
    from .audit import build_data_audit
    from .official_daily_provider import OfficialDailyMarketProvider
    from .repository import MarketRepository
    from .readiness import research_readiness

    data = root / "data"
    reports = root / "reports" / "data_audit"
    reports.mkdir(parents=True, exist_ok=True)
    off_detail, calendar_frame = audit_and_repair_off_calendar(root)
    calendar = pd.DatetimeIndex(calendar_frame.date)
    if official_daily:
        provider = OfficialDailyMarketProvider(data / "official_daily")
        failures = provider.download(calendar, workers=workers, exchanges=("TWSE", "TPEx"))
        failures.to_csv(reports / "official_recovery_failures.csv", index=False)
        if not failures.empty:
            raise RuntimeError(f"OFFICIAL_DAILY_RECOVERY_FAILED:{len(failures)}")
        observations = provider.consolidate(
            MarketRepository(data / "processed"), calendar, exchanges=("TWSE", "TPEx")
        )
    else:
        previous = pd.read_parquet(data / "historical_universe.parquet")
        observations = previous[
            ["symbol", "exchange", "first_seen", "last_seen", "trading_days", "source"]
        ].copy()
        pd.DataFrame(
            [{"date": pd.Timestamp.now(), "exchange": "TWSE", "reason": "OFFICIAL_ENDPOINT_SECURITY_BLOCK; existing data retained and graded by provenance"}]
        ).to_csv(reports / "official_recovery_failures.csv", index=False)
    observations.to_parquet(data / "historical_observations.parquet", index=False)
    master = build_security_master(root)
    delisted = collect_delisted(DELISTED_START)
    delisted.to_parquet(data / "delisted_universe.parquet", index=False)
    point, point_coverage = build_point_in_time_universe(root, master, calendar)
    point_coverage.to_csv(reports / "point_in_time_coverage.csv", index=False)
    historical = observations.merge(
        master[
            [
                "symbol", "company_name", "listing_date", "delisting_date",
                "instrument_type", "verified", "listing_date_precision",
            ]
        ],
        on=["symbol", "exchange"],
        how="inner",
    )
    historical = historical[historical.instrument_type.eq("COMMON_STOCK")].copy()
    eligibility = point.set_index(point.symbol.astype(str)).eligibility_verified
    historical["data_status"] = np.where(
        historical.symbol.astype(str).map(eligibility).fillna(False)
        & historical.trading_days.ge(120),
        "READY",
        "EXCLUDE_MISSING_LIFECYCLE_OR_HISTORY",
    )
    historical["universe_reason"] = "official company master/delisting record + official daily observation"
    historical.to_parquet(data / "historical_universe.parquet", index=False)
    try:
        actions = download_corporate_actions(RESEARCH_START, calendar.max())
    except Exception as exc:
        actions = download_corporate_actions(RESEARCH_START, calendar.max(), exchanges=("TPEx",))
        pd.DataFrame(
            [{"exchange": "TWSE", "reason": f"OFFICIAL_ENDPOINT_BLOCKED:{type(exc).__name__}", "automatically_fixable": True}]
        ).to_csv(reports / "corporate_action_recovery_failures.csv", index=False)
    actions.to_parquet(data / "corporate_actions.parquet", index=False)
    provenance = build_provenance(root)
    analysis_files = build_analysis_prices(root, master, actions)
    audit = build_data_audit(root)
    readiness = research_readiness(root)
    return {
        "off_calendar_original": len(off_detail),
        "off_calendar_unresolved": int(off_detail.resolution.eq("UNRESOLVED").sum()),
        "official_observations": len(observations),
        "security_master": len(master),
        "corporate_actions": len(actions),
        "provenance": len(provenance),
        "analysis_files": analysis_files,
        "audit": audit,
        "grade": readiness.grade,
    }
