from __future__ import annotations
from abc import ABC,abstractmethod
import pandas as pd
class DataProvider(ABC):
    @abstractmethod
    def history(self,symbol:str,start:str,end:str|None=None)->pd.DataFrame: ...

