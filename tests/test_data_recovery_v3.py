from pathlib import Path

import pandas as pd

from trader.backtest.fill_model import buy_fill
from trader.data.audit import build_data_audit
from trader.data.corporate_actions import CorporateActionAdjuster
from trader.data.point_in_time import PointInTimeUniverse
from trader.data.readiness import research_readiness


MASTER_COLUMNS = {
    "symbol", "company_name", "exchange", "instrument_type", "listing_date",
    "delisting_date", "source", "source_record_id_or_url", "verified",
}


def security(symbol="1000", instrument="COMMON_STOCK", listed="2020-01-02", delisted=None, **extra):
    return {
        "symbol": symbol, "company_name": symbol, "exchange": "TWSE",
        "instrument_type": instrument, "listing_date": listed,
        "delisting_date": delisted, "source": "official",
        "source_record_id_or_url": "https://example.invalid/official",
        "verified": True, "eligibility_start": listed,
        "eligibility_verified": True, **extra,
    }


def make_ready_tree(root: Path):
    (root / "data" / "processed").mkdir(parents=True)
    (root / "reports" / "data_audit").mkdir(parents=True)
    master = pd.DataFrame([security()])
    master.to_parquet(root / "data" / "security_master.parquet", index=False)
    master.to_parquet(root / "data" / "point_in_time_universe.parquet", index=False)
    calendar = pd.DataFrame({"date": pd.to_datetime(["2020-01-02", "2020-01-03"])})
    calendar.to_parquet(root / "data" / "trading_calendar.parquet", index=False)
    bars = pd.DataFrame(
        {
            "date": calendar.date, "open": [100, 50], "high": [101, 51],
            "low": [99, 49], "close": [100, 50], "volume": [1000, 2000],
        }
    )
    bars.to_parquet(root / "data" / "processed" / "1000.parquet", index=False)
    provenance = pd.DataFrame(
        [{
            "symbol": "1000", "exchange": "TWSE", "start_date": calendar.date.min(),
            "end_date": calendar.date.max(), "source": "TWSE", "source_type": "OFFICIAL_EXCHANGE",
            "price_convention": "UNADJUSTED_EXCHANGE", "download_timestamp": "2020-01-04",
            "raw_file_reference": "raw", "verified": True,
            "verification_method": "official", "validation_result": "OFFICIAL_VERIFIED",
            "repair_reason": "",
        }]
    )
    provenance.to_parquet(root / "data" / "ohlcv_provenance.parquet", index=False)
    actions = pd.DataFrame(
        [{
            "symbol": "1000", "exchange": "TWSE", "date": pd.Timestamp("2020-01-03"),
            "event_type": "SPLIT", "cash_amount": 0.0, "stock_ratio": 1.0,
            "rights_ratio": 0.0, "reference_price": 50.0, "adjustment_factor": .5,
            "source": "TWSE", "verified": True,
        }]
    )
    actions.to_parquet(root / "data" / "corporate_actions.parquet", index=False)
    audit = root / "reports" / "data_audit"
    pd.DataFrame([{"symbol": "1000", "expected_sessions": 2, "covered_sessions": 2, "coverage_pct": 1.0}]).to_csv(audit / "ohlcv_coverage.csv", index=False)
    pd.DataFrame([{"symbol": "1000", "expected_sessions": 2, "covered_sessions": 2, "coverage_pct": 1.0, "included_in_research": True}]).to_csv(audit / "delisted_coverage.csv", index=False)
    pd.DataFrame([{"symbol": "1000", "resolution": "VERIFIED_CORPORATE_ACTION"}]).to_csv(audit / "large_return_audit.csv", index=False)
    pd.DataFrame([{"symbol": "1000", "resolution": "ADD_VERIFIED_OFFICIAL_SESSION"}]).to_csv(audit / "off_calendar_detail.csv", index=False)
    return master, bars, actions


def test_security_master_required_columns():
    assert MASTER_COLUMNS <= set(pd.DataFrame([security()]).columns)


def test_listing_date_not_first_seen_proxy():
    row = security(listed=None, eligibility_start=None, first_seen="2018-01-02")
    assert not PointInTimeUniverse(pd.DataFrame([row])).is_listed("1000", "2020-01-01")


def test_delisting_date_not_last_seen_proxy():
    row = security(delisted=None, last_seen="2020-01-03")
    assert PointInTimeUniverse(pd.DataFrame([row])).is_listed("1000", "2021-01-01")


def test_only_common_stocks_enter_strategy_universe():
    rows = [security("1000"), security("0050", "ETF")]
    assert PointInTimeUniverse(pd.DataFrame(rows)).symbols_on("2020-01-03") == ["1000"]


def test_delisted_stocks_exist_in_historical_universe():
    pit = PointInTimeUniverse(pd.DataFrame([security(delisted="2020-01-04")]))
    assert pit.is_listed("1000", "2020-01-03")


def test_point_in_time_before_listing_false():
    assert not PointInTimeUniverse(pd.DataFrame([security()])).is_listed("1000", "2020-01-01")


def test_point_in_time_after_delisting_false():
    assert not PointInTimeUniverse(pd.DataFrame([security(delisted="2020-01-03")])).is_listed("1000", "2020-01-03")


def test_provenance_required_for_formal_data(tmp_path):
    make_ready_tree(tmp_path)
    (tmp_path / "data" / "ohlcv_provenance.parquet").unlink()
    result = research_readiness(tmp_path, {"research": {"dataset_version": "test"}})
    assert result.grade != "GRADE_A_FORMAL"


def test_unknown_price_convention_blocks_grade_a(tmp_path):
    make_ready_tree(tmp_path)
    path = tmp_path / "data" / "ohlcv_provenance.parquet"
    provenance = pd.read_parquet(path)
    provenance["price_convention"] = "UNKNOWN"
    provenance.to_parquet(path, index=False)
    assert research_readiness(tmp_path, {"research": {"dataset_version": "test"}}).grade != "GRADE_A_FORMAL"


def test_off_calendar_requires_resolution(tmp_path):
    make_ready_tree(tmp_path)
    pd.DataFrame([{"symbol": "1000", "resolution": "UNRESOLVED"}]).to_csv(tmp_path / "reports" / "data_audit" / "off_calendar_detail.csv", index=False)
    assert research_readiness(tmp_path, {"research": {"dataset_version": "test"}}).grade != "GRADE_A_FORMAL"


def test_large_return_requires_resolution(tmp_path):
    make_ready_tree(tmp_path)
    pd.DataFrame([{"symbol": "1000", "resolution": "UNRESOLVED"}]).to_csv(tmp_path / "reports" / "data_audit" / "large_return_audit.csv", index=False)
    assert research_readiness(tmp_path, {"research": {"dataset_version": "test"}}).grade != "GRADE_A_FORMAL"


def test_corporate_action_does_not_create_false_crash(tmp_path):
    _, bars, actions = make_ready_tree(tmp_path)
    adjusted = CorporateActionAdjuster(actions).adjust("1000", bars)
    assert adjusted.analysis_close.pct_change().iloc[-1] == 0


def test_raw_trade_price_preserved(tmp_path):
    _, bars, actions = make_ready_tree(tmp_path)
    adjusted = CorporateActionAdjuster(actions).adjust("1000", bars)
    assert adjusted.trade_close.tolist() == [100, 50]


def test_adjusted_analysis_series_continuous(tmp_path):
    _, bars, actions = make_ready_tree(tmp_path)
    adjusted = CorporateActionAdjuster(actions).adjust("1000", bars)
    assert adjusted.analysis_close.tolist() == [50.0, 50.0]


def test_execution_never_uses_adjusted_price(tmp_path):
    _, bars, actions = make_ready_tree(tmp_path)
    row = CorporateActionAdjuster(actions).adjust("1000", bars).iloc[0]
    fill = buy_fill(float(row.trade_open), 0.0)
    assert fill == 100


def test_trade_price_is_raw(tmp_path):
    _, bars, actions = make_ready_tree(tmp_path)
    row = CorporateActionAdjuster(actions).adjust("1000", bars).iloc[0]
    assert row.trade_open == row.open and row.analysis_open != row.trade_open


def test_analysis_price_handles_corporate_action(tmp_path):
    _, bars, actions = make_ready_tree(tmp_path)
    adjusted = CorporateActionAdjuster(actions).adjust("1000", bars)
    assert adjusted.analysis_close.nunique() == 1


def test_no_silent_data_exclusion(tmp_path):
    master, _, _ = make_ready_tree(tmp_path)
    master["verified"] = False
    master["eligibility_verified"] = False
    master.to_parquet(tmp_path / "data" / "security_master.parquet", index=False)
    master.to_parquet(tmp_path / "data" / "point_in_time_universe.parquet", index=False)
    build_data_audit(tmp_path)
    exclusions = pd.read_csv(tmp_path / "reports" / "data_audit" / "research_exclusions.csv")
    assert len(exclusions) == 1 and exclusions.iloc[0].reason == "MISSING_AUTHORITATIVE_LISTING_EVIDENCE"
