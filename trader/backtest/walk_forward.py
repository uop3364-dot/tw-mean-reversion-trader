import copy
import pandas as pd
from .engine import BacktestEngine
from trader.research.optimization import optimize_grid

def walk_forward(data,cfg,start="2019-01-01",end=None,status=None,prepared=None):
    begin=pd.Timestamp(start);final=pd.Timestamp(end or max(d.date.max() for d in data.values()));test=begin+pd.DateOffset(years=3);rows=[];minimum=cfg["research"]["minimum_training_trades"]
    while test<final:
        test_end=min(test+pd.DateOffset(months=6)-pd.Timedelta(days=1),final);train_start=test-pd.DateOffset(years=3);grid=optimize_grid(data,cfg,train_start,test-pd.Timedelta(days=1),status,prepared,minimum)
        valid=grid[grid.RobustScore.replace([float("inf"),float("-inf")],pd.NA).notna()]
        if valid.empty:rows.append({"train_start":train_start,"test_start":test,"test_end":test_end,"status":"INSUFFICIENT_SAMPLE","trades":0});test+=pd.DateOffset(months=6);continue
        best=valid.iloc[0];c=copy.deepcopy(cfg);c["strategy"]["low_zone"]["max_price_position"]=best.LowPosition;c["strategy"]["mean_reversion"]["minimum_probability"]=best.MRProbability;r=BacktestEngine(data,c,prepared=prepared,status=status).run(test,test_end,best.TP,True,"BASE",False);m=r["metrics"];fold_status="PASS" if len(r["trades"])>=cfg["research"]["minimum_test_fold_trades"] else "INSUFFICIENT_SAMPLE";rows.append({"train_start":train_start,"test_start":test,"test_end":test_end,"selected_tp":best.TP,"selected_low":best.LowPosition,"selected_mr":best.MRProbability,"parameter_plateau_score":best.parameter_plateau_score,"status":fold_status,"trades":len(r["trades"]),**m});test+=pd.DateOffset(months=6)
    return pd.DataFrame(rows)
