from __future__ import annotations
import numpy as np
import pandas as pd

TARGETS=[(.05,20,"P_5_20"),(.08,20,"P_8_20"),(.10,20,"P_10_20"),(.10,40,"P_10_40"),(.12,40,"P_12_40"),(.15,40,"P_15_40"),(.20,60,"P_20_60")]

def historical_event_stats(d: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    m=cfg["strategy"]["mean_reversion"]; o=cfg["strategy"]["oscillation"]; l=cfg["strategy"]["low_zone"]
    buy_slippage=cfg["strategy"]["execution"]["buy_slippage"]
    event=(d.oscillation_score>=o["minimum_score"])&(d.price_position<=l["max_price_position"])
    rows=[]; last=-10_000
    idxs=np.flatnonzero(event.fillna(False).to_numpy())
    for i in idxs:
        if i-last<m["event_cooldown_days"]: continue
        last=i; future=d.iloc[i+1:i+61]
        if future.empty or pd.isna(future.iloc[0].open): continue
        # A close-of-day signal is executable no earlier than the following
        # session's open. Include the configured buy slippage in the event
        # cost so historical probabilities match the portfolio fill model.
        entry=float(future.iloc[0].open)*(1+buy_slippage)
        row={"event_i":i,"entry":entry,"mae":float(future.low.min()/entry-1),"mfe":float(future.high.max()/entry-1)}
        for target,h,name in TARGETS: row[name]=bool((future.iloc[:h].high>=entry*(1+target)).any())
        rows.append(row)
    return pd.DataFrame(rows)

def expanding_probability(d: pd.DataFrame,cfg:dict) -> pd.DataFrame:
    m=cfg["strategy"]["mean_reversion"]; events=historical_event_stats(d,cfg)
    out=d.copy(); out["historical_events"]=0; out["mr_probability"]=np.nan
    target_col=f"P_{int(round(m['target_return']*100))}_{int(m['horizon_days'])}"
    if target_col not in events.columns and not events.empty:
        raise ValueError(f"Unsupported mean-reversion target/horizon: {target_col}")
    successes=0; count=0; event_map={int(r.event_i):bool(r[target_col]) for _,r in events.iterrows()}
    # An event outcome becomes knowable only after its full horizon: strict anti-look-ahead.
    # Entry occurs at i+1; its complete h-day outcome is known only afterward.
    reveal={i+1+m["horizon_days"]: ok for i,ok in event_map.items()}
    for i in range(len(out)):
        if i in reveal: count+=1; successes+=int(reveal[i])
        out.iat[i,out.columns.get_loc("historical_events")]=count
        out.iat[i,out.columns.get_loc("mr_probability")]=successes/count if count else np.nan
    return out

def choose_take_profit(events: pd.DataFrame,candidates:list[float],fee_rate=.001425,tax=.003) -> float:
    best=(float("-inf"),.10)
    for tp in candidates:
        if events.empty: continue
        success=events.mfe>=tp
        if success.mean()<.60: continue
        days=np.where(success,20,60).mean(); net=np.where(success,tp-fee_rate*2-tax,events.mfe-fee_rate*2-tax).mean()
        if net/days>best[0]: best=(net/days,tp)
    return best[1]

def expanding_take_profit(d:pd.DataFrame,events:pd.DataFrame,candidates:list[float],fallback=.10)->pd.Series:
    """Choose TP only from event paths whose entire 60-day evaluation is known."""
    out=pd.Series(fallback,index=d.index,dtype=float);known=[];by_reveal={}
    for j,r in events.iterrows():by_reveal.setdefault(int(r.event_i)+61,[]).append(j)
    current=fallback
    for i in range(len(d)):
        newly_known=by_reveal.get(i,[]);known.extend(newly_known)
        if newly_known:current=choose_take_profit(events.loc[known],candidates)
        out.iloc[i]=current
    return out
