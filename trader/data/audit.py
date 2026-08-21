from pathlib import Path
import pandas as pd


def _date_set(path):
    if not path.exists():
        return set()
    return set(pd.to_datetime(pd.read_parquet(path, columns=["date"]).date).dt.normalize())


def _large_return_audit(root, actions, provenance):
    rows = []
    action_dates = {
        (str(x.symbol), pd.Timestamp(x.date).normalize()): x
        for x in actions.itertuples()
    }
    prov = provenance.set_index(provenance.symbol.astype(str)) if not provenance.empty else pd.DataFrame()
    for path in (root / "data" / "processed").glob("*.parquet"):
        if path.stem == "TAIEX":
            continue
        bars = pd.read_parquet(path).sort_values("date")
        bars["date"] = pd.to_datetime(bars.date).dt.normalize()
        bars["raw_return"] = bars.close.pct_change()
        for row in bars[bars.raw_return.abs().gt(.25)].itertuples():
            action = action_dates.get((path.stem, row.date))
            official = (
                not prov.empty
                and path.stem in prov.index
                and bool(prov.loc[path.stem].verified)
                and prov.loc[path.stem].source_type == "OFFICIAL_EXCHANGE"
            )
            if action is not None:
                resolution = "VERIFIED_CORPORATE_ACTION"
            elif official:
                resolution = "VERIFIED_MARKET_MOVE"
            else:
                resolution = "UNRESOLVED"
            rows.append(
                {
                    "symbol": path.stem,
                    "date": row.date,
                    "raw_return": row.raw_return,
                    "source": prov.loc[path.stem].source if not prov.empty and path.stem in prov.index else "UNKNOWN",
                    "corporate_action": action.event_type if action is not None else "",
                    "official_crosscheck": official,
                    "resolution": resolution,
                    "original_value": row.close,
                    "replacement_value": row.close,
                    "verified": resolution != "UNRESOLVED",
                }
            )
    return pd.DataFrame(
        rows,
        columns=[
            "symbol", "date", "raw_return", "source", "corporate_action",
            "official_crosscheck", "resolution", "original_value",
            "replacement_value", "verified",
        ],
    )


def build_data_audit(root: Path):
    data = root / "data"
    out = root / "reports" / "data_audit"
    out.mkdir(parents=True, exist_ok=True)
    master_path = data / "security_master.parquet"
    pit_path = data / "point_in_time_universe.parquet"
    calendar_path = data / "trading_calendar.parquet"
    master = pd.read_parquet(master_path) if master_path.exists() else pd.DataFrame()
    pit = pd.read_parquet(pit_path) if pit_path.exists() else master.copy()
    calendar = (
        pd.DatetimeIndex(pd.read_parquet(calendar_path).date).normalize()
        if calendar_path.exists() else pd.DatetimeIndex([])
    )
    provenance_path = data / "ohlcv_provenance.parquet"
    provenance = pd.read_parquet(provenance_path) if provenance_path.exists() else pd.DataFrame()
    actions_path = data / "corporate_actions.parquet"
    actions = pd.read_parquet(actions_path) if actions_path.exists() else pd.DataFrame()

    if not actions.empty:
        actions.to_csv(out / "corporate_action_audit.csv", index=False)
    else:
        pd.DataFrame(
            columns=[
                "symbol", "exchange", "date", "event_type", "cash_amount",
                "stock_ratio", "rights_ratio", "reference_price",
                "adjustment_factor", "source", "verified",
            ]
        ).to_csv(out / "corporate_action_audit.csv", index=False)

    coverage_rows = []
    delisted_rows = []
    exclusions = []
    common = pit[pit.get("instrument_type", pd.Series(index=pit.index)).eq("COMMON_STOCK")] if not pit.empty else pit
    for security in common.itertuples():
        start = getattr(security, "eligibility_start", pd.NaT)
        end = security.delisting_date if pd.notna(security.delisting_date) else (calendar.max() + pd.Timedelta(days=1) if len(calendar) else pd.NaT)
        outside_window = pd.notna(security.delisting_date) and security.delisting_date <= pd.Timestamp("2018-01-02")
        expected = calendar[(calendar >= start) & (calendar < end)] if pd.notna(start) and pd.notna(end) else pd.DatetimeIndex([])
        path = data / "processed" / f"{security.symbol}.parquet"
        dates = _date_set(path)
        covered = sum(d in dates for d in expected)
        ratio = covered / len(expected) if len(expected) else 0.0
        if not bool(getattr(security, "eligibility_verified", security.verified)) and not outside_window:
            exclusions.append(
                {
                    "symbol": security.symbol,
                    "date_or_range": f"2018-01-02:{end.date() if pd.notna(end) else ''}",
                    "reason": "MISSING_AUTHORITATIVE_LISTING_EVIDENCE",
                    "source": security.source,
                    "severity": "BLOCKING",
                }
            )
        if pd.notna(security.delisting_date):
            delisted_rows.append(
                {
                    "symbol": security.symbol,
                    "exchange": security.exchange,
                    "listing_date": security.listing_date,
                    "delisting_date": security.delisting_date,
                    "price_start": min(dates) if dates else pd.NaT,
                    "price_end": max(dates) if dates else pd.NaT,
                    "expected_sessions": len(expected),
                    "covered_sessions": covered,
                    "coverage_pct": ratio,
                    "included_in_research": bool(not outside_window and getattr(security, "eligibility_verified", security.verified) and dates),
                    "exclusion_reason": "OUTSIDE_RESEARCH_WINDOW" if outside_window else ("" if bool(getattr(security, "eligibility_verified", security.verified) and dates) else "MISSING_LISTING_EVIDENCE_OR_PRICE"),
                }
            )
        coverage_rows.append(
            {
                "symbol": security.symbol,
                "expected_sessions": len(expected),
                "covered_sessions": covered,
                "coverage_pct": ratio,
            }
        )
    delisted = pd.DataFrame(delisted_rows)
    delisted.to_csv(out / "delisted_coverage.csv", index=False)
    pd.DataFrame(exclusions, columns=["symbol", "date_or_range", "reason", "source", "severity"]).to_csv(
        out / "research_exclusions.csv", index=False
    )
    symbol_coverage = pd.DataFrame(coverage_rows)
    symbol_coverage.to_csv(out / "ohlcv_coverage.csv", index=False)

    large = _large_return_audit(root, actions, provenance)
    large.to_csv(out / "large_return_audit.csv", index=False)
    return {
        "security_master": len(master),
        "common_stocks": len(common),
        "delisted": len(delisted),
        "symbol_days_expected": int(symbol_coverage.expected_sessions.sum()) if not symbol_coverage.empty else 0,
        "symbol_days_covered": int(symbol_coverage.covered_sessions.sum()) if not symbol_coverage.empty else 0,
        "large_returns": len(large),
        "large_returns_unresolved": int(large.resolution.eq("UNRESOLVED").sum()) if not large.empty else 0,
        "corporate_actions": len(actions),
    }
