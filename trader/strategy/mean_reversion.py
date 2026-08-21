from __future__ import annotations
from dataclasses import dataclass,asdict
import numpy as np
import pandas as pd
from scipy.stats import beta as beta_dist

TPS=(.05,.08,.10,.12,.15,.20)

@dataclass(frozen=True)
class HistoricalEvent:
    event_i:int;date:object;symbol:str;next_day_entry:float;oscillation_score:float;price_position:float;price_percentile:float;low_score:float;atr_pct:float;rsi:float;bb_position:float;efficiency_ratio:float;regime_risk:float;market_regime:str;sector:str|None

def _bucket(row):
    get=lambda k,v:row.get(k,v) if hasattr(row,"get") else getattr(row,k,v)
    return (pd.cut([get("oscillation_score",0)],[0,65,70,80,90,np.inf],labels=False)[0],pd.cut([get("price_position",1)],[-np.inf,.05,.10,.20,.30,np.inf],labels=False)[0],pd.cut([get("regime_risk_score",0)],[-np.inf,20,40,60,np.inf],labels=False)[0],pd.cut([get("atr_pct",.04)],[-np.inf,.025,.04,.06,.08,.12,np.inf],labels=False)[0],pd.cut([get("rsi14",35)],[-np.inf,20,30,40,50,np.inf],labels=False)[0])

def _simulate_path(d,i,tp,cfg):
    s=cfg["strategy"];ex=s["execution"];future=d.iloc[i+1:i+92]
    if future.empty or pd.isna(future.iloc[0].open):return None
    entry=float(future.iloc[0].open)*(1+ex["buy_slippage"]);target=entry*(1+tp);mae=0.;mfe=0.;pending_thesis=False;pending_time=False
    for day,(_,r) in enumerate(future.iterrows(),1):
        if pd.isna(r.open):continue
        if pending_thesis:return _path_result(entry,float(r.open)*(1-ex["sell_slippage"]),day,mae,mfe,"THESIS_BREAK")
        if pending_time:return _path_result(entry,float(r.open)*(1-ex["sell_slippage"]),day,mae,mfe,"TIME_EXIT")
        mae=min(mae,float(r.low/entry-1));mfe=max(mfe,float(r.high/entry-1))
        fill=float(r.open)*(1-ex["sell_slippage"]) if r.open>=target else target*(1-ex["sell_slippage"]) if r.high>=target else None
        if fill is not None:return _path_result(entry,fill,day,mae,mfe,"TAKE_PROFIT")
        immediate=r.get("thesis_break_score",0)>=s["regime"]["thesis_break_immediate_score"]
        confirmed=day>=2 and r.get("thesis_break_score",0)>=s["regime"]["thesis_break_score"] and future.iloc[day-2].get("thesis_break_score",0)>=s["regime"]["thesis_break_score"]
        pending_thesis=bool(immediate or confirmed)
        if day==s["holding"]["max_days"]:
            extend=(r.oscillation_score>=60 and r.regime_risk_score<40 and r.structure_direction!="BEARISH" and r.rs60>-.10 and mfe>=.03)
            pending_time=not extend
        if day>=s["holding"]["absolute_max_days"]:pending_time=True
    r=future.iloc[-1];return _path_result(entry,float(r.close)*(1-ex["sell_slippage"]),len(future),mae,mfe,"END_OF_TEST")

def _path_result(entry,exit_price,days,mae,mfe,reason):
    fee=.001425*2;tax=.003;net=exit_price/entry-1-fee-tax
    return {"net_return":net,"holding_days":int(days),"mae":mae,"mfe":mfe,"exit_reason":reason,"hit":reason=="TAKE_PROFIT","day":int(days) if reason=="TAKE_PROFIT" else np.nan}

def historical_event_stats(d:pd.DataFrame,cfg:dict,symbol="UNKNOWN")->pd.DataFrame:
    s=cfg["strategy"];low=d.get("low_score",pd.Series(100.,index=d.index));risk=d.get("regime_risk_score",pd.Series(0.,index=d.index));event=(d.oscillation_score>=s["oscillation"]["minimum_score"])&(low>=s["low_zone"]["minimum_score"])&(d.price_position<=.30)&(risk<60);rows=[];last=-9999
    for i in np.flatnonzero(event.fillna(False).to_numpy()):
        if i-last<s["mean_reversion"]["event_cooldown_days"]:continue
        last=i
        if i+1>=len(d) or pd.isna(d.iloc[i+1].open):continue
        r=d.iloc[i];ev=HistoricalEvent(i,r.get("date",i),symbol,float(d.iloc[i+1].open)*(1+s["execution"]["buy_slippage"]),float(r.get("oscillation_score",0)),float(r.get("price_position",1)),float(r.get("price_percentile",1)),float(r.get("low_score",100)),float(r.get("atr_pct",.04)),float(r.get("rsi14",35)),float(r.get("bb_position",.2)),float(r.get("er60",0)),float(r.get("regime_risk_score",0)),str(r.get("market_regime","UNKNOWN")),r.get("industry",None));row=asdict(ev);row["entry"]=ev.next_day_entry;row["bucket"]=_bucket(r)
        for tp in TPS:
            p=_simulate_path(d,i,tp,cfg)
            if p:
                prefix=f"tp{int(tp*100)}";row.update({f"{prefix}_{k}":v for k,v in p.items()})
        hit=lambda p,h:bool(row.get(f"tp{p}_hit",False) and row.get(f"tp{p}_day",np.inf)<=h)
        row.update({"P_5_20":hit(5,20),"P_8_20":hit(8,20),"P_10_20":hit(10,20),"P_10_40":hit(10,40),"P_12_40":hit(12,40),"P_15_40":hit(15,40),"P_20_60":hit(20,60)})
        rows.append(row)
    return pd.DataFrame(rows)

def expanding_probability(d:pd.DataFrame,cfg:dict,symbol="UNKNOWN")->pd.DataFrame:
    m=cfg["strategy"]["mean_reversion"];events=historical_event_stats(d,cfg,symbol);out=d.copy();cols={"historical_events":0,"raw_probability":np.nan,"posterior_probability":np.nan,"probability_ci_low":np.nan,"probability_ci_high":np.nan,"probability_source":"MARKET_PRIOR"}
    for k,v in cols.items():out[k]=v
    reveal={};target=f"tp{int(m['target_return']*100)}_hit"
    for j,e in events.iterrows():reveal.setdefault(int(e.event_i)+1+m["horizon_days"],[]).append(j)
    known=[];alpha=float(m["beta_prior_alpha"]);beta=float(m["beta_prior_beta"]);minimum=int(m["minimum_historical_events"])
    for i in range(len(out)):
        known.extend(reveal.get(i,[]));row=out.iloc[i];bucket=_bucket(row);sample=events.loc[known] if known else events.iloc[0:0];exact=sample[sample.bucket.apply(lambda x:x==bucket)] if not sample.empty else sample;near=sample[sample.bucket.apply(lambda x:x[:3]==bucket[:3])] if not sample.empty else sample
        chosen=exact if len(exact)>=minimum else near if len(near)>=minimum else sample;source="EXACT_BUCKET" if len(exact)>=minimum else "NEARBY_BUCKET" if len(near)>=minimum else "SYMBOL_LEVEL" if len(sample)>=minimum else "MARKET_PRIOR"
        successes=float(chosen[target].sum()) if len(chosen) and target in chosen else 0.;n=len(chosen) if source!="MARKET_PRIOR" else 0;post=(successes+alpha)/(n+alpha+beta);out.at[out.index[i],"historical_events"]=n;out.at[out.index[i],"raw_probability"]=successes/n if n else np.nan;out.at[out.index[i],"posterior_probability"]=post;out.at[out.index[i],"probability_ci_low"]=beta_dist.ppf(.025,successes+alpha,n-successes+beta);out.at[out.index[i],"probability_ci_high"]=beta_dist.ppf(.975,successes+alpha,n-successes+beta);out.at[out.index[i],"probability_source"]=source
    out["mr_probability"]=out.posterior_probability;return out

def choose_take_profit(events:pd.DataFrame,candidates,min_trades=30,fallback=.10):
    if len(events)<min_trades:return fallback
    best=(-np.inf,fallback)
    for tp in candidates:
        p=f"tp{int(tp*100)}";needed={f"{p}_net_return",f"{p}_holding_days",f"{p}_mae"}
        if not needed<=set(events.columns):continue
        net=events[f"{p}_net_return"].astype(float);days=events[f"{p}_holding_days"].clip(lower=1);downside=np.maximum(-net,0).mean();score=net.mean()/days.mean()-.5*downside/days.mean()
        if score>best[0]:best=(score,tp)
    return float(best[1])

def expanding_take_profit(d,events,candidates,fallback=.10,min_trades=30):
    out=pd.Series(fallback,index=d.index,dtype=float);known=[];reveal={}
    for j,r in events.iterrows():reveal.setdefault(int(r.event_i)+92,[]).append(j)
    current=fallback
    for i in range(len(d)):
        known.extend(reveal.get(i,[]))
        if reveal.get(i):current=choose_take_profit(events.loc[known],candidates,min_trades,fallback)
        out.iloc[i]=current
    return out
