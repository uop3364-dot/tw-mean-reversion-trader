def market_crash(taiex):
    if len(taiex)<60:return False
    c=taiex.close; ma20=c.rolling(20).mean().iloc[-1]; ma60=c.rolling(60).mean().iloc[-1]
    return bool(c.iloc[-1]<ma60 and ma20<ma60 and c.iloc[-1]/c.iloc[-21]-1<-.10)

