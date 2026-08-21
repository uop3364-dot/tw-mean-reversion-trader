import pandas as pd
import pytest

from trader.data.finmind_provider import FinMindDataProvider
from trader.data.quality import quality_manifest
from trader.data.repository import MarketRepository


class Response:
    def __init__(self, rows): self.rows=rows
    def raise_for_status(self): return None
    def json(self): return {"status":200,"data":self.rows}


def row(date, open_, high, low, close):
    return {"date":date,"stock_id":"9999","Trading_Volume":1000,"Trading_money":10000,"open":open_,"max":high,"min":low,"close":close,"Trading_turnover":10}


def test_finmind_listing_boundary_removes_emerging_schema(monkeypatch):
    rows=[row("2024-01-01",105,100,90,95),row("2024-01-02",96,99,94,98)]
    monkeypatch.setattr("trader.data.finmind_provider.requests.get",lambda *a,**k:Response(rows))
    d=FinMindDataProvider(delay=0).history("9999","2020-01-01",minimum_date="2024-01-02")
    assert list(d.date)==[pd.Timestamp("2024-01-02")]


def test_finmind_rejects_invalid_ohlc_after_listing(monkeypatch):
    monkeypatch.setattr("trader.data.finmind_provider.requests.get",lambda *a,**k:Response([row("2024-01-02",105,100,90,95)]))
    with pytest.raises(ValueError,match="after listing-date boundary"):
        FinMindDataProvider(delay=0).history("9999","2020-01-01",minimum_date="2024-01-01")


def test_quality_manifest_flags_corrupt_bars(tmp_path):
    repo=MarketRepository(tmp_path)
    repo.save("9999",pd.DataFrame({"date":pd.to_datetime(["2024-01-02"]),"open":[11],"high":[10],"low":[9],"close":[10],"volume":[100]}))
    universe=pd.DataFrame({"symbol":["9999"],"exchange":["TWSE"]})
    result=quality_manifest(universe,repo,"2024-01-01",pd.to_datetime(["2024-01-02"]))
    assert result.loc[0,"invalid_ohlcv_rows"]==1


def test_quality_manifest_flags_zero_price(tmp_path):
    repo=MarketRepository(tmp_path)
    repo.save("9999",pd.DataFrame({"date":pd.to_datetime(["2024-01-02"]),"open":[0],"high":[0],"low":[0],"close":[0],"volume":[0]}))
    universe=pd.DataFrame({"symbol":["9999"],"exchange":["TWSE"]})
    result=quality_manifest(universe,repo,"2024-01-01",pd.to_datetime(["2024-01-02"]))
    assert result.loc[0,"invalid_ohlcv_rows"]==1
