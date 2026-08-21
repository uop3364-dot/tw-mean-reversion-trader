import copy,math
import pandas as pd
from trader.backtest.engine import BacktestEngine

GRID_TP=(.05,.08,.10,.12,.15,.20);GRID_LOW=(.10,.15,.20,.25,.30);GRID_MR=(.55,.60,.65,.70,.75)
def robust_score(m,trades,minimum=50):
    pf=m.get("Profit Factor",0);dd=m.get("Max Drawdown",0);cagr=m.get("CAGR",0);sh=m.get("Sharpe Ratio",0)
    if trades<minimum or dd<=-.50 or not math.isfinite(pf) or pf<=0:return float("-inf")
    return cagr/abs(dd) + .5*sh + .5*math.log(pf) if dd else float("-inf")
def optimize_grid(data,cfg,start,end,status=None,prepared=None,minimum=50,scenario="BASE"):
    rows=[]
    for low in GRID_LOW:
      for mr in GRID_MR:
       c=copy.deepcopy(cfg);c["strategy"]["low_zone"]["max_price_position"]=low;c["strategy"]["mean_reversion"]["minimum_probability"]=mr
       for tp in GRID_TP:
        r=BacktestEngine(data,c,prepared=prepared,status=status).run(start,end,tp,liquidate_at_end=True,execution_scenario=scenario,account_kill=False);m=r["metrics"];rows.append({"TP":tp,"LowPosition":low,"MRProbability":mr,"trades":len(r["trades"]),"RobustScore":robust_score(m,len(r["trades"]),minimum),**m})
    out=pd.DataFrame(rows);valid=out.RobustScore.replace([-math.inf],pd.NA).dropna();threshold=valid.quantile(.90) if len(valid) else math.inf;out["top_10pct"]=out.RobustScore>=threshold
    def neighbors(r):return out[(out.TP.sub(r.TP).abs()<=.03)&(out.LowPosition.sub(r.LowPosition).abs()<=.05)&(out.MRProbability.sub(r.MRProbability).abs()<=.05)]
    out["parameter_plateau_score"]=[float((neighbors(r).RobustScore>=threshold).mean()) for r in out.itertuples()];return out.sort_values("RobustScore",ascending=False)
