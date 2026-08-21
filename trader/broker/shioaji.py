from __future__ import annotations
import os
from trader.config import live_enabled,kill_switch
from .base import Broker
class ShioajiBroker(Broker):
    def __init__(self):
        try: import shioaji as sj
        except ImportError as e: raise RuntimeError("Install live extras: pip install -e .[live]") from e
        self.api=sj.Shioaji(); self.account=None
    def login(self):
        if not live_enabled(): raise RuntimeError("LIVE_TRADING_ENABLED is not true; live login blocked")
        self.api.login(api_key=os.environ["SHIOAJI_API_KEY"],secret_key=os.environ["SHIOAJI_SECRET_KEY"]); self.account=self.api.stock_account; return self
    def get_cash(self): return self.api.account_balance().acc_balance
    def get_settlements(self): return self.api.settlements(self.account)
    def get_positions(self): return self.api.list_positions(self.account)
    def get_open_orders(self): self.api.update_status(self.account); return [t for t in self.api.list_trades() if str(t.status.status) not in ("Filled","Cancelled")]
    def _order(self,side,symbol,quantity,price,cid):
        if not live_enabled(): raise RuntimeError("Live order blocked: LIVE_TRADING_ENABLED=false")
        if side=="Buy" and kill_switch(): raise RuntimeError("Buy blocked by TRADING_KILL_SWITCH")
        sj=__import__("shioaji"); contract=self.api.Contracts.Stocks[symbol]
        order=self.api.Order(price=price,quantity=quantity,action=getattr(sj.constant.Action,side),price_type=sj.constant.StockPriceType.LMT,order_type=sj.constant.OrderType.ROD,order_lot=sj.constant.StockOrderLot.Odd,account=self.account,custom_field=cid[:6])
        return self.api.place_order(contract,order)
    def place_buy(self,symbol,quantity,price,client_order_id):return self._order("Buy",symbol,quantity,price,client_order_id)
    def place_sell(self,symbol,quantity,price,client_order_id):return self._order("Sell",symbol,quantity,price,client_order_id)
    def cancel_order(self,order_id):return self.api.cancel_order(order_id)
    def get_order_status(self,order_id):self.api.update_status(self.account);return order_id.status.status

