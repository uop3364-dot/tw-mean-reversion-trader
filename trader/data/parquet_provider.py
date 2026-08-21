from pathlib import Path
import pandas as pd
from .provider import DataProvider
class ParquetDataProvider(DataProvider):
    def __init__(self,root): self.root=Path(root)
    def history(self,symbol,start,end=None):
        p=self.root/f"{symbol}.parquet"
        if not p.exists(): return pd.DataFrame()
        d=pd.read_parquet(p); d["date"]=pd.to_datetime(d.date); mask=d.date>=pd.Timestamp(start)
        if end: mask &= d.date<=pd.Timestamp(end)
        return d.loc[mask].sort_values("date").reset_index(drop=True)

