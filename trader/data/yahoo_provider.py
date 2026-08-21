from __future__ import annotations
import pandas as pd
from .provider import DataProvider
class YahooDataProvider(DataProvider):
    def history(self,symbol,start,end=None):
        import yfinance as yf
        ticker=symbol if symbol.startswith("^") else (symbol if "." in symbol else symbol+".TW")
        d=yf.download(ticker,start=start,end=end,auto_adjust=False,progress=False,threads=False)
        if d.empty and ticker.endswith(".TW"):
            d=yf.download(symbol+".TWO",start=start,end=end,auto_adjust=False,progress=False,threads=False)
        if d.empty:return pd.DataFrame()
        if isinstance(d.columns,pd.MultiIndex): d.columns=d.columns.get_level_values(0)
        d=d.reset_index().rename(columns=str.lower).rename(columns={"adj close":"adj_close"})
        d["date"]=pd.to_datetime(d.date).dt.tz_localize(None)
        return d[["date","open","high","low","close","volume"]].dropna().reset_index(drop=True)

    def histories(self,symbol_exchange:dict[str,str],start,end=None,batch_size=80):
        """Bulk download while preserving exchange suffix and per-symbol failures."""
        import yfinance as yf
        items=list(symbol_exchange.items());result={};failures=[]
        for begin in range(0,len(items),batch_size):
            batch=items[begin:begin+batch_size];tickers=[s+(".TW" if ex=="TWSE" else ".TWO") for s,ex in batch]
            try:d=yf.download(tickers,start=start,end=end,auto_adjust=False,progress=False,threads=True,group_by="ticker")
            except Exception as exc:
                failures.extend({"symbol":s,"reason":str(exc)} for s,_ in batch);continue
            for (symbol,_),ticker in zip(batch,tickers):
                try:
                    x=d[ticker].reset_index() if len(tickers)>1 else d.reset_index()
                    x=x.rename(columns=str.lower).rename(columns={"adj close":"adj_close"});x["date"]=pd.to_datetime(x.date).dt.tz_localize(None)
                    x=x[["date","open","high","low","close","volume"]].dropna(subset=["open","high","low","close"])
                    if x.empty:failures.append({"symbol":symbol,"reason":"empty_history"})
                    else:result[symbol]=x.reset_index(drop=True)
                except Exception as exc:failures.append({"symbol":symbol,"reason":str(exc)})
        return result,pd.DataFrame(failures)
