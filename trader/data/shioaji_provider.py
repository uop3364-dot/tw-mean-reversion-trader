from .provider import DataProvider
class ShioajiDataProvider(DataProvider):
    def __init__(self,api): self.api=api
    def history(self,symbol,start,end=None):
        import pandas as pd
        contract=self.api.Contracts.Stocks[symbol]
        return pd.DataFrame(self.api.kbars(contract,start=start,end=end)).rename(columns=str.lower)

