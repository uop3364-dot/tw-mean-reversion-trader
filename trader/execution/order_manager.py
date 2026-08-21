from __future__ import annotations
import hashlib
from sqlalchemy import select
from trader.storage.models import Order
class OrderManager:
    def __init__(self,broker,session_factory):self.broker=broker;self.sessions=session_factory
    @staticmethod
    def client_id(symbol,side,strategy_date):return hashlib.sha256(f"{symbol}|{side}|{strategy_date}".encode()).hexdigest()[:24]
    def submit(self,symbol,side,qty,price,strategy_date):
        cid=self.client_id(symbol,side,strategy_date)
        with self.sessions() as db:
            found=db.scalar(select(Order).where(Order.client_order_id==cid))
            if found:return found
            obj=Order(client_order_id=cid,symbol=symbol,side=side,status="SUBMITTING");db.add(obj);db.commit()
            try: result=(self.broker.place_buy if side=="BUY" else self.broker.place_sell)(symbol,qty,price,cid);obj.status="OPEN";db.commit();return result
            except Exception:obj.status="ERROR";db.commit();raise

