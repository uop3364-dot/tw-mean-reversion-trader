from __future__ import annotations
from dataclasses import dataclass
from datetime import timedelta
import hashlib,math
import numpy as np
import pandas as pd
from trader.strategy.signal_engine import build_signals
from .fill_model import buy_fill,sell_fill
from .metrics import metrics

@dataclass
class OpenPosition:
    symbol:str; qty:int; entry_price:float; entry_date:pd.Timestamp; tp_return:float; entry_fee:float; mae:float=0; mfe:float=0; risk_days:int=0; age:int=0; extended:bool=False; last_price:float|None=None
    @property
    def tp(self):return self.entry_price*(1+self.tp_return)

class BacktestEngine:
    def __init__(self,data:dict[str,pd.DataFrame],cfg:dict,capital:float|None=None,prepared=None,status=None):
        self.cfg=cfg;self.initial=float(capital or cfg["backtest"]["initial_capital_twd"]);self.raw=data;self.prepared=prepared;self.status=status or {"altered":set(),"dispositions":{}};self._eligible_by_date=None
    def _status_blocked(self,symbol,date):
        if (symbol,pd.Timestamp(date)) in self.status.get("altered",set()):return True
        return any(a<=pd.Timestamp(date)<=b for a,b in self.status.get("dispositions",{}).get(symbol,[]))
    def run(self,start=None,end=None,fixed_tp=None,liquidate_at_end=False):
        np.random.seed(int(self.cfg["backtest"].get("seed",42))); s=self.cfg["strategy"]; b=self.cfg["broker"]; fee_cfg=b["broker_fee"]
        calendar=self.raw.get("TAIEX",pd.DataFrame()).get("date",None)
        feat=self.prepared if self.prepared is not None else {k:build_signals(v,self.cfg,calendar).set_index("date") for k,v in self.raw.items() if k not in ("TAIEX","0050") and len(v)>=120}
        eligible_by_date=self._eligible_by_date
        if eligible_by_date is None:
            eligible_by_date={};o=s["oscillation"];l=s["low_zone"];m=s["mean_reversion"];rg=s["regime"];u=s["universe"]
            for sym,d in feat.items():
                mask=(d.close.between(u["minimum_price"],u["maximum_price"]))&(d.avg_volume_20>=u["minimum_avg_daily_volume_shares_20d"])&(d.avg_value_20>=u["minimum_avg_daily_value_20d"])&(d.oscillation_score>=o["minimum_score"])&(d.low_score>=l["minimum_score"])&(d.price_position<=l["max_price_position"])&(d.price_percentile<=l["max_price_percentile"])&(d.rsi14.between(l["rsi_minimum"],l["rsi_maximum"]))&(d.bb_position<=l["bollinger_max_position"])&(d.historical_events>=m["minimum_historical_events"])&(d.mr_probability>=m["minimum_probability"])&(d.regime_risk_score<=rg["maximum_buy_risk_score"])&(d.final_score>=s["ranking"]["minimum_final_score"])
                for dt in d.index[mask.fillna(False)]:
                    if not self._status_blocked(sym,dt):eligible_by_date.setdefault(dt,[]).append((float(d.at[dt,"final_score"]),sym))
            for values in eligible_by_date.values():values.sort(reverse=True)
            self._eligible_by_date=eligible_by_date
        market=pd.DataFrame()
        if "TAIEX" in self.raw:
            market=self.raw["TAIEX"].copy().set_index("date");market["ma20"]=market.close.rolling(20).mean();market["ma60"]=market.close.rolling(60).mean();market["return20"]=market.close.pct_change(20)
        dates=sorted(set().union(*(set(x.index) for x in feat.values()))) if feat else []
        if start:dates=[d for d in dates if d>=pd.Timestamp(start)]
        if end:dates=[d for d in dates if d<=pd.Timestamp(end)]
        cash=self.initial; positions={}; trades=[]; eqrows=[]; signalrows=[]; pending=[]; highwater=self.initial; safe=False
        def fee(value,qty): return max(fee_cfg["odd_lot_minimum_fee"] if qty<1000 else fee_cfg["minimum_fee"],value*fee_cfg["rate"]*fee_cfg.get("discount",1))
        for di,date in enumerate(dates):
            due=[x for x in pending if x[0]<=date]; cash+=sum(x[1] for x in due);pending=[x for x in pending if x[0]>date]
            prices={}
            for sym in positions:
                d=feat[sym]
                if date in d.index and pd.notna(d.at[date,"close"]):prices[sym]=float(d.at[date,"close"])
            for sym,price in prices.items():
                if sym in positions:positions[sym].last_price=price
            # SELL phase first.
            for sym,p in list(positions.items()):
                d=feat[sym]
                if date not in d.index:continue
                row=d.loc[date];p.age+=1
                if row[["open","high","low","close"]].isna().any():continue
                p.mae=min(p.mae,float(row.low/p.entry_price-1));p.mfe=max(p.mfe,float(row.high/p.entry_price-1))
                p.risk_days=p.risk_days+1 if row.regime_risk_score>=s["regime"]["thesis_break_score"] else 0
                fill=sell_fill(float(row.open),float(row.high),p.tp,s["execution"]["sell_slippage"]);reason="TP" if fill else None
                if not reason and p.risk_days>=s["regime"]["thesis_break_confirmation_days"]:fill=float(row.open)*(1-s["execution"]["sell_slippage"]);reason="THESIS_BREAK"
                if not reason and p.age>=s["holding"]["max_days"] and not p.extended:
                    if row.oscillation_score>=60 and row.regime_risk_score<60:p.extended=True
                    else:fill=float(row.open)*(1-s["execution"]["sell_slippage"]);reason="TIME_EXIT"
                if not reason and p.age>=s["holding"]["absolute_max_days"]:fill=float(row.open)*(1-s["execution"]["sell_slippage"]);reason="TIME_EXIT"
                if not reason and liquidate_at_end and di==len(dates)-1:fill=float(row.close)*(1-s["execution"]["sell_slippage"]);reason="END_OF_WINDOW"
                if reason:
                    gross=p.qty*fill;sf=fee(gross,p.qty);tax=gross*b["cost"]["stock_transaction_tax"];net=gross-sf-tax
                    # Taiwan T+N is counted in exchange sessions, not generic
                    # Monday-Friday weekdays (which mishandle market holidays).
                    settle_i=di+int(b["settlement"]["business_days"]);settle_date=dates[settle_i] if settle_i<len(dates) else pd.Timestamp.max
                    pending.append((settle_date,net))
                    cost=p.qty*p.entry_price+p.entry_fee; pnl=net-cost
                    trades.append({"symbol":sym,"entry_date":p.entry_date,"exit_date":date,"quantity":p.qty,"entry_price":p.entry_price,"exit_price":fill,"target_return":p.tp_return,"holding_days":p.age,"exit_reason":reason,"fees":p.entry_fee+sf,"tax":tax,"net_pnl":pnl,"return_pct":pnl/cost,"mae":p.mae,"mfe":p.mfe})
                    del positions[sym]
            invested=sum(p.qty*(p.last_price if p.last_price is not None else p.entry_price) for p in positions.values());equity=cash+sum(v for _,v in pending)+invested;highwater=max(highwater,equity)
            if equity/highwater-1<=-s["account_risk"]["maximum_strategy_drawdown"]:safe=True
            # Signals at D close create buys at D+1 open only.
            daily_paused=bool(eqrows and equity/eqrows[-1]["equity"]-1<=-s["account_risk"]["daily_equity_drop_pause"])
            if di and not safe and not daily_paused and not (liquidate_at_end and di==len(dates)-1):
                prev=dates[di-1]; candidates=[]
                crash=False
                if not market.empty and prev in market.index:
                    mr=market.loc[prev];crash=bool(pd.notna(mr.ma60) and mr.close<mr.ma60 and mr.ma20<mr.ma60 and mr.return20<-.10)
                for score,sym in eligible_by_date.get(prev,[]):
                    # Revalidate official restrictions on execution day: a
                    # stock can enter disposition/suspension after the signal
                    # close and must not be bought the following morning.
                    if sym not in positions and date in feat[sym].index and not self._status_blocked(sym,date):candidates.append((score,sym,feat[sym].loc[prev]))
                for _,sym,sig in candidates[:s["portfolio"]["max_new_positions_per_day"]]:
                    if len(positions)>=s["portfolio"]["max_positions"]:break
                    row=feat[sym].loc[date]
                    if pd.isna(row.open):continue
                    fill=buy_fill(float(row.open),s["execution"]["buy_slippage"]);reserve=equity*s["portfolio"]["cash_reserve_ratio"];available=cash-reserve
                    slots=s["portfolio"]["max_positions"]-len(positions);target=min(equity*s["portfolio"]["max_position_weight"],available/slots if slots else 0)
                    if crash:target*=s["market_regime"]["crash_mode_position_multiplier"]
                    qty=math.floor(target/fill)
                    if qty<1:continue
                    f=fee(qty*fill,qty);total=qty*fill+f
                    if total>cash-reserve:continue
                    cash-=total;tp=float(fixed_tp if fixed_tp is not None else sig.take_profit);positions[sym]=OpenPosition(sym,qty,fill,date,tp,f,last_price=float(row.close) if pd.notna(row.close) else fill)
                    signalrows.append({"strategy_date":prev,"execution_date":date,"symbol":sym,"client_order_id":hashlib.sha256(f"{sym}|BUY|{prev.date()}".encode()).hexdigest()[:24],"oscillation_score":sig.oscillation_score,"low_score":sig.low_score,"mr_probability":sig.mr_probability,"regime_risk":sig.regime_risk_score,"final_score":sig.final_score,"take_profit":tp})
            invested=sum(p.qty*(p.last_price if p.last_price is not None else p.entry_price) for p in positions.values());equity=cash+sum(v for _,v in pending)+invested
            eqrows.append({"date":date,"cash":cash,"pending_settlement":sum(v for _,v in pending),"invested":invested,"equity":equity,"positions":len(positions),"safe_mode":safe})
        equity_df=pd.DataFrame(eqrows); trades_df=pd.DataFrame(trades); signals_df=pd.DataFrame(signalrows)
        return {"equity":equity_df,"trades":trades_df,"signals":signals_df,"metrics":metrics(equity_df,trades_df,self.initial)}
