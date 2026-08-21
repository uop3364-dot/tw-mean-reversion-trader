import numpy as np
import pandas as pd
def bootstrap_trades(trades,n=10000,seed=42):
    r=trades.return_pct.to_numpy(float);rng=np.random.default_rng(seed);rows=[]
    if not len(r):return pd.DataFrame()
    for i in range(n):
        x=rng.choice(r,len(r),replace=True);wins=x[x>0].sum();loss=-x[x<0].sum();curve=np.cumprod(1+x);dd=(curve/np.maximum.accumulate(curve)-1).min();rows.append({"sample":i,"expectancy":x.mean(),"mean_return":x.mean(),"profit_factor":wins/loss if loss else np.inf,"max_drawdown":dd})
    return pd.DataFrame(rows)
def monte_carlo(trades,n=5000,seed=42):
    r=trades.return_pct.to_numpy(float);rng=np.random.default_rng(seed);rows=[]
    for i in range(n):
        x=rng.permutation(r);curve=np.cumprod(1+x);rows.append({"sample":i,"max_drawdown":(curve/np.maximum.accumulate(curve)-1).min(),"ending_growth":curve[-1]-1})
    return pd.DataFrame(rows)
