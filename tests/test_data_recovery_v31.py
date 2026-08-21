from pathlib import Path

import pandas as pd

from trader.data.audit import _large_return_audit
from trader.data.point_in_time import PointInTimeUniverse
from trader.data.recovery_v31 import (
    audit_required_symbol_days,
    parse_twse_actions,
    reconstruct_provenance,
    secondary_crosschecked_bars,
)
from trader.data.twse_fallback_provider import OfficialFallbackClient, SOURCE_TIER_1


def _tree(root: Path, *, listed="2020-01-03", delisted=None, dates=("2020-01-03", "2020-01-06")):
    (root / "data" / "processed").mkdir(parents=True)
    (root / "data" / "official_daily").mkdir()
    (root / "reports" / "data_audit").mkdir(parents=True)
    calendar = pd.DataFrame({"date": pd.to_datetime(["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07"])})
    calendar.to_parquet(root / "data" / "trading_calendar.parquet", index=False)
    master = pd.DataFrame(
        [{
            "symbol": "1000", "company_name": "fixture", "exchange": "TWSE",
            "instrument_type": "COMMON_STOCK", "listing_date": pd.Timestamp(listed),
            "delisting_date": pd.Timestamp(delisted) if delisted else pd.NaT,
            "eligibility_start": pd.Timestamp(listed), "eligibility_verified": True,
            "source": "official", "verified": True,
        }]
    )
    master.to_parquet(root / "data" / "point_in_time_universe.parquet", index=False)
    bars = pd.DataFrame(
        {"date": pd.to_datetime(dates), "open": 10.0, "high": 10.0, "low": 10.0, "close": 10.0, "volume": 1}
    )
    bars.to_parquet(root / "data" / "processed" / "1000.parquet", index=False)
    pd.DataFrame(columns=["date", "symbol", "exchange", "status", "source"]).to_parquet(
        root / "data" / "altered_trading_daily.parquet", index=False
    )
    return master, bars


def test_required_mask_excludes_pre_listing(tmp_path):
    master, _ = _tree(tmp_path)
    result = audit_required_symbol_days(tmp_path, master)
    assert result["excluded_pre_listing"] == 1
    assert result["required_symbol_days"] == 3


def test_required_mask_excludes_post_delisting(tmp_path):
    master, _ = _tree(tmp_path, delisted="2020-01-07")
    result = audit_required_symbol_days(tmp_path, master)
    assert result["excluded_post_delisting"] == 1
    assert result["required_symbol_days"] == 2


def test_required_mask_handles_suspension(tmp_path):
    master, _ = _tree(tmp_path, dates=("2020-01-03", "2020-01-07"))
    pd.DataFrame(
        [{"date": pd.Timestamp("2020-01-06"), "symbol": "1000", "exchange": "TWSE", "status": "SUSPENDED", "source": "official"}]
    ).to_parquet(tmp_path / "data" / "altered_trading_daily.parquet", index=False)
    result = audit_required_symbol_days(tmp_path, master)
    assert result["excluded_suspended"] == 1
    assert result["available_symbol_days"] == result["required_symbol_days"]


def test_lifecycle_supports_multiple_intervals():
    rows = pd.DataFrame(
        [
            {"symbol": "1000", "exchange": "TPEx", "listing_date": "2018-01-01", "delisting_date": "2020-01-01", "instrument_type": "COMMON_STOCK"},
            {"symbol": "1000", "exchange": "TWSE", "listing_date": "2020-01-02", "delisting_date": None, "instrument_type": "COMMON_STOCK"},
        ]
    )
    pit = PointInTimeUniverse(rows)
    assert pit.is_listed("1000", "2019-01-01") and pit.is_listed("1000", "2021-01-01")


def test_fallback_provider_records_source_tier(tmp_path):
    class Response:
        status_code = 200
        content = b'[{"Code":"1000"}]'
        def raise_for_status(self): pass
    class Session:
        headers = {}
        def get(self, *args, **kwargs): return Response()
    client = OfficialFallbackClient(tmp_path, throttle_seconds=0, session=Session())
    _, receipt = client.twse_openapi("fixture")
    assert receipt.source_tier == SOURCE_TIER_1 and receipt.row_count == 1 and receipt.checksum


def test_reconstructed_provenance_requires_evidence(tmp_path):
    master, _ = _tree(tmp_path)
    pd.DataFrame([{"symbol": "1000", "source": "FinMind TaiwanStockPrice"}]).to_parquet(
        tmp_path / "data" / "historical_universe.parquet", index=False
    )
    pd.DataFrame(
        [{"symbol": "1000", "verified": False, "source": "", "source_type": "UNKNOWN", "verification_method": ""}]
    ).to_parquet(tmp_path / "data" / "ohlcv_provenance.parquet", index=False)
    result = reconstruct_provenance(tmp_path)
    assert result.iloc[0].provenance_class == "PROVENANCE_RECONSTRUCTED"
    assert "sha256=" in result.iloc[0].evidence


def test_secondary_price_requires_crosscheck():
    left = pd.DataFrame({"date": ["2020-01-02"], "open": [10], "high": [11], "low": [9], "close": [10], "volume": [1]})
    right = left.copy(); right["close"] = 12
    assert secondary_crosschecked_bars(left, right).empty
    right["close"] = 10
    assert len(secondary_crosschecked_bars(left, right)) == 1


def test_twse_corporate_actions_loaded():
    payload = {"data": [["109年01月02日", "1000", "測試", "100", "90", "10", "權息", "", "", "", "95"]]}
    result = parse_twse_actions(payload)
    assert len(result) == 1 and result.iloc[0].exchange == "TWSE" and result.iloc[0].verified


def test_large_return_uses_adjusted_comparison(tmp_path):
    master, _ = _tree(tmp_path, dates=("2020-01-03", "2020-01-06"))
    bars = pd.read_parquet(tmp_path / "data" / "processed" / "1000.parquet")
    bars.loc[1, ["open", "high", "low", "close"]] = 5.0
    bars.to_parquet(tmp_path / "data" / "processed" / "1000.parquet", index=False)
    master.to_parquet(tmp_path / "data" / "point_in_time_universe.parquet", index=False)
    actions = pd.DataFrame([{"symbol": "1000", "date": pd.Timestamp("2020-01-06"), "event_type": "SPLIT", "adjustment_factor": .5}])
    result = _large_return_audit(tmp_path, actions, pd.DataFrame())
    assert result.iloc[0].corporate_action_adjusted_return == 0
    assert result.iloc[0].resolution == "CORPORATE_ACTION_MECHANICAL_GAP"


def test_no_missing_bar_forward_fill(tmp_path):
    master, _ = _tree(tmp_path, dates=("2020-01-03",))
    path = tmp_path / "data" / "processed" / "1000.parquet"
    before = path.read_bytes()
    audit_required_symbol_days(tmp_path, master)
    assert path.read_bytes() == before


def test_grade_a_denominator_is_auditable(tmp_path):
    master, _ = _tree(tmp_path)
    audit_required_symbol_days(tmp_path, master)
    result = pd.read_csv(tmp_path / "reports" / "data_audit" / "coverage_denominator_audit.csv")
    required = {"raw_possible_rows", "excluded_pre_listing", "excluded_post_delisting", "excluded_non_sessions", "excluded_suspended", "required_symbol_days", "available_symbol_days", "coverage"}
    assert required <= set(result.columns)
