import pandas as pd
from trader.backtest.engine import BacktestEngine
def run_ablation(data,cfg,start,end,status=None,prepared=None):
    rows=[]
    for i in range(7):
        fixed=None if i==6 else cfg["strategy"]["take_profit"]["fallback"];r=BacktestEngine(data,cfg,prepared=prepared,status=status).run(start,end,fixed,True,"BASE",False,f"A{i}");m=r["metrics"];rows.append({"variant":f"A{i}","trades":len(r["trades"]),"CAGR":m.get("CAGR",0),"Total Return":m.get("Total Return",0),"MaxDD":m.get("Max Drawdown",0),"Sharpe":m.get("Sharpe Ratio",0),"ProfitFactor":m.get("Profit Factor",0),"Expectancy":m.get("Expectancy per trade",0),"TPHitRate":m.get("Take Profit Hit Rate",0),"MAE":m.get("Average MAE",0),"CapitalUtilization":m.get("Capital Utilization",0)})
    out=pd.DataFrame(rows);out["evidence"]="BASE";prev=None
    for i in out.index:
        if prev is not None and out.at[i,"trades"]<out.at[prev,"trades"] and out.at[i,"ProfitFactor"]<=out.at[prev,"ProfitFactor"] and out.at[i,"Expectancy"]<=out.at[prev,"Expectancy"]:out.at[i,"evidence"]="NO EVIDENCE OF VALUE"
        prev=i
    return out
