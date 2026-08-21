import pytest
from trader.broker.shioaji import ShioajiBroker
def test_live_disabled_by_default(monkeypatch):
    monkeypatch.setenv("LIVE_TRADING_ENABLED","false")
    obj=object.__new__(ShioajiBroker)
    with pytest.raises(RuntimeError):obj.place_buy("2330",1,100,"x")

