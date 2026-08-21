from pathlib import Path
import pandas as pd
class MarketRepository:
    def __init__(self,root): self.root=Path(root); self.root.mkdir(parents=True,exist_ok=True)
    def save(self,symbol,d): d.sort_values("date").drop_duplicates("date").to_parquet(self.root/f"{symbol}.parquet",index=False)
    def symbols(self): return sorted(p.stem for p in self.root.glob("*.parquet"))
    def load(self,symbol): return pd.read_parquet(self.root/f"{symbol}.parquet")

