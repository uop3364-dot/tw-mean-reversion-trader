from __future__ import annotations
from dataclasses import dataclass,field
from datetime import date,timedelta

@dataclass
class Settlement:
    settlement_date: date; receivable: float=0; payable: float=0
@dataclass
class SettlementLedger:
    entries:list[Settlement]=field(default_factory=list)
    def add_buy(self,trade_date:date,amount:float): self.entries.append(Settlement(_business_add(trade_date,2),payable=amount))
    def add_sell(self,trade_date:date,amount:float): self.entries.append(Settlement(_business_add(trade_date,2),receivable=amount))
    def net_due(self,on:date): return sum(x.receivable-x.payable for x in self.entries if x.settlement_date<=on)
    def pending_receivable(self,on:date): return sum(x.receivable for x in self.entries if x.settlement_date>on)
    def pending_payable(self,on:date): return sum(x.payable for x in self.entries if x.settlement_date>on)
    def available_cash(self,cash:float,on:date,outstanding_buys:float,reserve:float):
        return cash-self.pending_payable(on)-outstanding_buys-reserve
def _business_add(d:date,n:int)->date:
    while n:
        d+=timedelta(days=1)
        if d.weekday()<5:n-=1
    return d

