from .base import Broker
class PaperBroker(Broker):
    def __init__(self,cash=100000): self.cash=cash; self.positions={}; self.orders={}; self.settlements=[]
    def get_cash(self):return self.cash
    def get_settlements(self):return self.settlements
    def get_positions(self):return self.positions
    def get_open_orders(self):return [x for x in self.orders.values() if x["status"]=="OPEN"]
    def _place(self,side,symbol,quantity,price,cid):
        if cid in self.orders:return self.orders[cid]
        self.orders[cid]={"id":cid,"client_order_id":cid,"side":side,"symbol":symbol,"quantity":quantity,"price":price,"status":"OPEN"};return self.orders[cid]
    def place_buy(self,symbol,quantity,price,client_order_id):return self._place("BUY",symbol,quantity,price,client_order_id)
    def place_sell(self,symbol,quantity,price,client_order_id):return self._place("SELL",symbol,quantity,price,client_order_id)
    def cancel_order(self,order_id):self.orders[order_id]["status"]="CANCELLED"
    def get_order_status(self,order_id):return self.orders[order_id]["status"]

