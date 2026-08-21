from dataclasses import dataclass,field
@dataclass
class Position:
    symbol:str; quantity:int; avg_price:float; entry_date:object; target_return:float=.10; risk_days:int=0
    @property
    def tp(self): return self.avg_price*(1+self.target_return)
@dataclass
class Account:
    cash:float; positions:dict[str,Position]=field(default_factory=dict); realized_pnl:float=0; fees:float=0; tax:float=0
    def equity(self,prices): return self.cash+sum(p.quantity*prices.get(s,p.avg_price) for s,p in self.positions.items())

