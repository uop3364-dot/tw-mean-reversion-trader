from trader.execution.taiwan_rules import TaiwanTickRule

def locked_limit(row,side,previous_close):
    if previous_close is None:return False
    limit=TaiwanTickRule.limit_up(previous_close) if side=="BUY" else TaiwanTickRule.limit_down(previous_close)
    return bool(row.open==row.high==row.low==limit)

def buy_fill(open_price,slippage=.001,row=None,previous_close=None,max_volume=None,quantity=1):
    if row is not None and (locked_limit(row,"BUY",previous_close) or (max_volume is not None and quantity>max_volume)):return None
    price=float(open_price)*(1+slippage);return price if row is None else TaiwanTickRule.round_up(price)

def sell_fill(open_price,high,tp,slippage=.001,row=None,previous_close=None,touch_adverse=0.,max_volume=None,quantity=1):
    if row is not None and (locked_limit(row,"SELL",previous_close) or (max_volume is not None and quantity>max_volume)):return None
    target=TaiwanTickRule.round_up(tp)
    if row is None:
        if open_price>=tp:return float(open_price)*(1-slippage)
        if high>=tp:return float(tp)*(1-slippage-touch_adverse)
        return None
    if open_price>=target:return TaiwanTickRule.round_down(float(open_price)*(1-slippage))
    if high>=target:return TaiwanTickRule.round_down(target*(1-slippage-touch_adverse))
    return None
