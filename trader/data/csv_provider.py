from pathlib import Path
import pandas as pd
from .provider import DataProvider
class CSVDataProvider(DataProvider):
    def __init__(self,root): self.root=Path(root)
    def history(self,symbol,start,end=None):
        p=self.root/f"{symbol}.csv"; d=pd.read_csv(p); d.columns=[x.lower() for x in d.columns]; d["date"]=pd.to_datetime(d.date)
        return d[(d.date>=start)&((d.date<=end) if end else True)].sort_values("date").reset_index(drop=True)

