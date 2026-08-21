class PositionManager:
    def __init__(self,broker):self.broker=broker
    def recover(self):
        return {"positions":self.broker.get_positions(),"open_orders":self.broker.get_open_orders(),"settlements":self.broker.get_settlements()}
    def monitor_tp(self,prices,targets):
        def val(obj,key,default=None): return obj.get(key,default) if isinstance(obj,dict) else getattr(obj,key,default)
        active={val(o,"symbol") for o in self.broker.get_open_orders() if val(o,"side")=="SELL"}
        out=[]
        for symbol,pos in self.broker.get_positions().items():
            qty=val(pos,"quantity",0);tp=targets.get(symbol)
            if qty>0 and tp and prices.get(symbol,0)>=tp and symbol not in active:out.append((symbol,qty,tp))
        return out
