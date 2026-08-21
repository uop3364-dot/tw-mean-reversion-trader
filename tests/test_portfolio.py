from datetime import date
from trader.portfolio.allocator import allocate
from trader.portfolio.settlement import SettlementLedger
def test_allocation_caps_weight():assert allocate(100000,90000,8,100,.15)<=150
def test_settlement_sale_not_immediately_available():
    l=SettlementLedger();d=date(2026,8,20);l.add_sell(d,10000);assert l.pending_receivable(d)==10000;assert l.net_due(d)==0

