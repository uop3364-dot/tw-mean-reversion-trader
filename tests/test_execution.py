from trader.backtest.fill_model import sell_fill
from trader.broker.paper import PaperBroker
from trader.execution.order_manager import OrderManager
from trader.storage.db import database
def test_take_profit_gap_uses_open():assert sell_fill(115,116,110,.001)==115*.999
def test_duplicate_order_idempotency(tmp_path):
    broker=PaperBroker();sessions=database(f"sqlite:///{tmp_path/'x.db'}");m=OrderManager(broker,sessions);a=m.submit("2330","BUY",1,100,"2026-01-01");b=m.submit("2330","BUY",1,100,"2026-01-01");assert len(broker.orders)==1
def test_restart_recovery():
    from trader.execution.position_manager import PositionManager
    b=PaperBroker();assert set(PositionManager(b).recover())=={"positions","open_orders","settlements"}

