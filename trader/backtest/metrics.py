from __future__ import annotations
import numpy as np
import pandas as pd
def metrics(equity:pd.DataFrame,trades:pd.DataFrame,initial:float)->dict:
    if equity.empty:return {"Starting Capital":initial,"Ending Capital":initial}
    eq=equity.equity.astype(float); ret=eq.pct_change().fillna(0); years=max((equity.date.iloc[-1]-equity.date.iloc[0]).days/365.25,1/365.25)
    dd=eq/eq.cummax()-1; downside=ret[ret<0].std()
    out={"Starting Capital":initial,"Ending Capital":eq.iloc[-1],"Total Return":eq.iloc[-1]/initial-1,"CAGR":(eq.iloc[-1]/initial)**(1/years)-1,"Max Drawdown":dd.min(),"Average Drawdown":dd[dd<0].mean() if (dd<0).any() else 0,"Sharpe Ratio":np.sqrt(252)*ret.mean()/ret.std() if ret.std() else 0,"Sortino Ratio":np.sqrt(252)*ret.mean()/downside if downside else 0,"Capital Utilization":equity.invested.sum()/equity.equity.sum() if equity.equity.sum() else 0,"Maximum Concurrent Positions":int(equity.positions.max())}
    if trades.empty:
        out.update({k:0 for k in ["Win Rate","Profit Factor","Average Trade Return","Median Trade Return","Average Holding Days","Median Holding Days","Trades Per Year","Best Trade","Worst Trade","Average MAE","Median MAE","90th percentile MAE","Average MFE","Median MFE","Take Profit Hit Rate","Thesis Break Exit Rate","Time Exit Rate","Median Days to TP","Percentage Never Reaching TP"]});return out
    wins=trades.net_pnl[trades.net_pnl>0].sum(); losses=-trades.net_pnl[trades.net_pnl<0].sum(); tp=trades.exit_reason.eq("TP")
    out.update({"Win Rate":(trades.net_pnl>0).mean(),"Profit Factor":wins/losses if losses else float("inf"),"Average Trade Return":trades.return_pct.mean(),"Median Trade Return":trades.return_pct.median(),"Average Holding Days":trades.holding_days.mean(),"Median Holding Days":trades.holding_days.median(),"Trades Per Year":len(trades)/years,"Best Trade":trades.return_pct.max(),"Worst Trade":trades.return_pct.min(),"Average MAE":trades.mae.mean(),"Median MAE":trades.mae.median(),"90th percentile MAE":trades.mae.quantile(.10),"90th Percentile MAE Before TP":trades.loc[tp,"mae"].quantile(.10) if tp.any() else 0,"Average MFE":trades.mfe.mean(),"Median MFE":trades.mfe.median(),"Take Profit Hit Rate":tp.mean(),"Thesis Break Exit Rate":trades.exit_reason.eq("THESIS_BREAK").mean(),"Time Exit Rate":trades.exit_reason.eq("TIME_EXIT").mean(),"Median Days to TP":trades.loc[tp,"holding_days"].median() if tp.any() else 0,"Percentage Never Reaching TP":1-tp.mean()})
    return out
