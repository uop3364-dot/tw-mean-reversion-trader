def buy_fill(open_price,slippage=.001): return open_price*(1+slippage)
def sell_fill(open_price,high,tp,slippage=.001):
    if open_price>tp:return open_price*(1-slippage)
    if high>=tp:return tp*(1-slippage)
    return None

