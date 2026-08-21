from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import platform
import pandas as pd


class ResearchDataNotReady(RuntimeError):
    pass


GRADE_ORDER = {
    "GRADE_C_BLOCKED": 0,
    "GRADE_B_EXPLORATORY": 1,
    "GRADE_A_FORMAL": 2,
}


@dataclass(frozen=True)
class ResearchReadinessResult:
    checks: pd.DataFrame
    dataset_version: str
    dataset_hash: str
    grade: str

    @property
    def passed(self):
        return self.grade == "GRADE_A_FORMAL"

    @property
    def exploratory(self):
        return GRADE_ORDER[self.grade] >= GRADE_ORDER["GRADE_B_EXPLORATORY"]

    def require(self, minimum="GRADE_A_FORMAL"):
        if GRADE_ORDER[self.grade] < GRADE_ORDER[minimum]:
            failed = ",".join(self.checks.loc[self.checks.status.eq("FAIL"), "check"])
            raise ResearchDataNotReady(f"RESEARCH_DATA_NOT_READY:{self.grade}:{failed}")
        return self


def _hash(paths, extra=b""):
    h = hashlib.sha256(extra)
    for path in sorted(set(Path(x) for x in paths), key=lambda x: x.as_posix()):
        h.update(path.as_posix().encode())
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1048576), b""):
                h.update(block)
    return h.hexdigest()


def research_readiness(root: Path, cfg=None):
    from trader.config import settings

    cfg = cfg or settings()
    data = root / "data"
    out = root / "reports" / "data_audit"
    out.mkdir(parents=True, exist_ok=True)
    checks = []

    def add(name, coverage, required, unresolved, reason, grade_a=None, grade_b=None):
        a = bool(grade_a if grade_a is not None else coverage >= required)
        b = bool(grade_b if grade_b is not None else coverage >= .98)
        checks.append(
            {
                "check": name,
                "status": "PASS" if a else ("EXPLORATORY" if b else "FAIL"),
                "coverage": float(coverage),
                "required": float(required),
                "unresolved_count": int(unresolved),
                "reason": reason,
                "grade_a_pass": a,
                "grade_b_pass": b,
            }
        )

    master_path = data / "security_master.parquet"
    master = pd.read_parquet(master_path) if master_path.exists() else pd.DataFrame()
    required_master = {
        "symbol", "company_name", "exchange", "instrument_type", "listing_date",
        "delisting_date", "source", "source_record_id_or_url", "verified",
    }
    master_schema = required_master <= set(master.columns)
    add(
        "security_master",
        1.0 if master_schema else 0.0,
        .995,
        0 if master_schema else len(required_master - set(master.columns)),
        "official security identity and lifecycle schema",
    )
    relevant = master[
        master.exchange.isin(["TWSE", "TPEx"])
        & (master.delisting_date.isna() | master.delisting_date.gt(pd.Timestamp("2018-01-02")))
    ] if not master.empty and "exchange" in master else pd.DataFrame()
    identity_coverage = relevant.verified.mean() if not relevant.empty and "verified" in relevant else 0.0
    add("ordinary_stock_identity", identity_coverage, .995, int((~relevant.verified).sum()) if not relevant.empty else 1, "verified instrument identity")

    pit_path = data / "point_in_time_universe.parquet"
    pit = pd.read_parquet(pit_path) if pit_path.exists() else pd.DataFrame()
    pit_relevant = pit[
        pit.delisting_date.isna() | pit.delisting_date.gt(pd.Timestamp("2018-01-02"))
    ] if len(pit) else pit
    pit_expected = len(pit_relevant)
    pit_covered = int(pit_relevant.get("eligibility_verified", pd.Series(False, index=pit_relevant.index)).sum()) if len(pit_relevant) else 0
    pit_coverage = pit_covered / pit_expected if pit_expected else 0.0
    add("point_in_time_universe", pit_coverage, .995, pit_expected - pit_covered, "listing interval evidence without first_seen/date proxy")

    delisted_path = out / "delisted_coverage.csv"
    delisted = pd.read_csv(delisted_path) if delisted_path.exists() else pd.DataFrame()
    if not delisted.empty:
        relevant_delisted = (
            delisted[pd.to_datetime(delisted.delisting_date).gt(pd.Timestamp("2018-01-02"))]
            if "delisting_date" in delisted else delisted
        )
        expected = relevant_delisted.expected_sessions.sum()
        covered = relevant_delisted.covered_sessions.sum()
        delisted_coverage = covered / expected if expected else 0.0
        unresolved_delisted = int((~relevant_delisted.included_in_research.astype(bool)).sum())
    else:
        delisted_coverage, unresolved_delisted = 0.0, 1
    add("delisted_coverage", delisted_coverage, .995, unresolved_delisted, "delisted ordinary stocks and price history prevent survivorship bias")

    denominator_path = out / "coverage_denominator_audit.csv"
    denominator = pd.read_csv(denominator_path) if denominator_path.exists() else pd.DataFrame()
    ohlcv_path = out / "ohlcv_coverage.csv"
    ohlcv = pd.read_csv(ohlcv_path) if ohlcv_path.exists() else pd.DataFrame()
    expected = denominator.required_symbol_days.iloc[0] if not denominator.empty else (ohlcv.expected_sessions.sum() if not ohlcv.empty else 0)
    covered = denominator.available_symbol_days.iloc[0] if not denominator.empty else (ohlcv.covered_sessions.sum() if not ohlcv.empty else 0)
    ohlcv_coverage = covered / expected if expected else 0.0
    add("ohlcv_symbol_days", ohlcv_coverage, .995, int(expected - covered), "required listed/tradable symbol-day OHLCV coverage")

    provenance_path = data / "ohlcv_provenance.parquet"
    provenance = pd.read_parquet(provenance_path) if provenance_path.exists() else pd.DataFrame()
    required_symbols = set(
        pit.loc[
            pit.instrument_type.eq("COMMON_STOCK")
            & (pit.delisting_date.isna() | pit.delisting_date.gt(pd.Timestamp("2018-01-02"))),
            "symbol",
        ].astype(str)
    ) if not pit.empty else set()
    accepted_provenance = {"PROVENANCE_DIRECT", "PROVENANCE_RECONSTRUCTED", "SECONDARY_CROSSCHECKED"}
    evidence = provenance.get("evidence", pd.Series("", index=provenance.index)).fillna("").astype(str).str.len().gt(0) if not provenance.empty else pd.Series(dtype=bool)
    classes = provenance.get("provenance_class", pd.Series("UNKNOWN", index=provenance.index)) if not provenance.empty else pd.Series(dtype=str)
    verified_symbols = set(
        provenance.loc[
            provenance.verified.astype(bool)
            & classes.isin(accepted_provenance)
            & evidence,
            "symbol",
        ].astype(str)
    ) if not provenance.empty else set()
    provenance_coverage = len(required_symbols & verified_symbols) / len(required_symbols) if required_symbols else 0.0
    add("ohlcv_provenance", provenance_coverage, .995, len(required_symbols - verified_symbols), "known source for each research symbol")
    conventions = set(
        provenance.loc[provenance.symbol.astype(str).isin(required_symbols), "price_convention"].dropna()
    ) if not provenance.empty else set()
    convention_ok = conventions == {"UNADJUSTED_EXCHANGE"}
    add("price_convention", 1.0 if convention_ok else 0.0, 1.0, 0 if convention_ok else 1, "raw exchange trade price; adjusted analysis layer is separate")

    actions_path = data / "corporate_actions.parquet"
    actions = pd.read_parquet(actions_path) if actions_path.exists() else pd.DataFrame()
    action_schema = {
        "symbol", "exchange", "date", "event_type", "cash_amount", "stock_ratio",
        "rights_ratio", "reference_price", "adjustment_factor", "source", "verified",
    }
    action_exchanges = set(actions.exchange) if not actions.empty and action_schema <= set(actions.columns) else set()
    expected_action_exchanges = {"TWSE", "TPEx"}
    row_coverage = actions.verified.mean() if not actions.empty and action_schema <= set(actions.columns) else 0.0
    exchange_coverage = len(action_exchanges & expected_action_exchanges) / len(expected_action_exchanges)
    action_fail_path = out / "corporate_action_recovery_failures.csv"
    action_failures = pd.read_csv(action_fail_path) if action_fail_path.exists() else pd.DataFrame()
    unresolved_periods = len(action_failures)
    total_months = len(pd.period_range("2018-01", pd.Timestamp.today(), freq="M"))
    completed_exchange_months = total_months * len(action_exchanges & expected_action_exchanges) - unresolved_periods
    verified_action_coverage = min(
        row_coverage,
        completed_exchange_months / (total_months * len(expected_action_exchanges)) if total_months else 0.0,
    )
    unresolved_actions = int((~actions.verified.astype(bool)).sum()) + unresolved_periods + len(expected_action_exchanges - action_exchanges) if not actions.empty and "verified" in actions else len(expected_action_exchanges)
    add(
        "corporate_actions", verified_action_coverage, .995, unresolved_actions,
        "verified actions affecting continuous analysis price; failed official periods remain explicit",
        grade_a=verified_action_coverage >= .995 and unresolved_actions == 0,
        grade_b=row_coverage == 1.0 and exchange_coverage == 1.0,
    )

    large_path = out / "large_return_audit.csv"
    large = pd.read_csv(large_path) if large_path.exists() else pd.DataFrame()
    unresolved_large = int(large.resolution.eq("UNRESOLVED").sum()) if not large.empty and "resolution" in large else 1
    large_coverage = 1 - unresolved_large / len(large) if len(large) else 0.0
    add(
        "large_return_audit", large_coverage, 1.0, unresolved_large,
        "every abs(raw return)>25% has deterministic resolution; Grade B retains explicit unresolved cases",
        grade_a=unresolved_large == 0,
        grade_b=large_coverage >= .95,
    )

    off_path = out / "off_calendar_detail.csv"
    off = pd.read_csv(off_path) if off_path.exists() else pd.DataFrame()
    unresolved_off = int(off.resolution.eq("UNRESOLVED").sum()) if not off.empty and "resolution" in off else 1
    add("off_calendar", 1.0 if unresolved_off == 0 else 0.0, 1.0, unresolved_off, "each original off-calendar bar is classified and resolved")

    cal_path = data / "trading_calendar.parquet"
    calendar = pd.read_parquet(cal_path).date if cal_path.exists() else pd.Series(dtype="datetime64[ns]")
    calendar = pd.DatetimeIndex(pd.to_datetime(calendar)).normalize()
    invalid = duplicates = remaining_off = 0
    for path in (data / "processed").glob("*.parquet"):
        bars = pd.read_parquet(path)
        bars["date"] = pd.to_datetime(bars.date).dt.normalize()
        bad = (
            (bars[["open", "high", "low", "close"]] <= 0).any(axis=1)
            | bars.volume.lt(0)
            | bars.high.lt(bars.low)
            | bars.high.lt(bars[["open", "close"]].max(axis=1))
            | bars.low.gt(bars[["open", "close"]].min(axis=1))
        )
        invalid += int(bad.sum())
        duplicates += int(bars.date.duplicated().sum())
        remaining_off += int((~bars.date.isin(calendar)).sum()) if len(calendar) else len(bars)
    hard_unresolved = invalid + duplicates + remaining_off
    add("ohlcv_hard_checks", 1.0 if hard_unresolved == 0 else 0.0, 1.0, hard_unresolved, f"invalid={invalid}; duplicates={duplicates}; off_calendar={remaining_off}")

    frame = pd.DataFrame(checks)
    grade_a = bool(frame.grade_a_pass.all())
    grade_b = bool(frame.grade_b_pass.all())
    grade = "GRADE_A_FORMAL" if grade_a else ("GRADE_B_EXPLORATORY" if grade_b else "GRADE_C_BLOCKED")
    version = cfg.get("research", {}).get("dataset_version", "UNVERSIONED")
    paths = [
        path for path in [
            master_path, pit_path, provenance_path, actions_path, cal_path,
            root / "config" / "strategy.yaml",
        ] if path.exists()
    ] + list((data / "processed").glob("*.parquet")) + list(data.glob("*status*.parquet"))
    dataset_hash = _hash(paths, json.dumps(cfg, sort_keys=True, default=str).encode())
    frame.to_csv(out / "research_readiness.csv", index=False)
    payload = {
        "dataset_grade": grade,
        "dataset_version": version,
        "dataset_hash": dataset_hash,
        "python": platform.python_version(),
        "checks": frame.to_dict("records"),
    }
    (out / "readiness.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    blockers = frame[~frame.grade_a_pass].copy()
    blocker_rows = []
    for priority, row in enumerate(blockers.itertuples(), 1):
        blocker_rows.append(
            {
                "priority": priority,
                "check": row.check,
                "affected_symbols": row.unresolved_count if "symbol" in row.check or row.check in {"point_in_time_universe", "ohlcv_provenance", "delisted_coverage"} else "",
                "affected_rows": row.unresolved_count,
                "coverage": row.coverage,
                "missing_requirement": row.required,
                "recommended_source": "TWSE/TPEx official records",
                "automatically_fixable": row.check not in {"point_in_time_universe", "delisted_coverage"},
                "manual_action_required": row.check in {"point_in_time_universe", "delisted_coverage"},
            }
        )
    pd.DataFrame(
        blocker_rows,
        columns=[
            "priority", "check", "affected_symbols", "affected_rows", "coverage",
            "missing_requirement", "recommended_source", "automatically_fixable",
            "manual_action_required",
        ],
    ).to_csv(out / "blockers.csv", index=False)
    return ResearchReadinessResult(frame, version, dataset_hash, grade)
