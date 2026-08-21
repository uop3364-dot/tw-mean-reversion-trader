import numpy as np,pandas as pd,pytest
from trader.config import settings
@pytest.fixture
def cfg():
    c=settings();c["strategy"]["universe"]["minimum_avg_daily_value_20d"]=0;c["strategy"]["universe"]["minimum_avg_daily_volume_shares_20d"]=0;return c
@pytest.fixture
def prices():
    np.random.seed(42);n=300;t=np.arange(n);close=100+10*np.sin(t/4)+np.random.normal(0,.5,n)
    return pd.DataFrame({"date":pd.bdate_range("2020-01-01",periods=n),"open":close,"high":close*1.03,"low":close*.97,"close":close,"volume":1_000_000})
