from __future__ import annotations
from datetime import date
from pathlib import Path
import json,logging,os
import pandas as pd
import typer
from rich.console import Console
from rich.table import Table
from trader.config import ROOT,settings,live_enabled
from trader.data.repository import MarketRepository
from trader.data.parquet_provider import ParquetDataProvider
from trader.data.yahoo_provider import YahooDataProvider
from trader.data.universe_provider import OfficialUniverseProvider
from trader.data.quality import quality_manifest
from trader.data.official_daily_provider import OfficialDailyMarketProvider
from trader.data.status_provider import dispositions,altered_daily
from trader.data.readiness import research_readiness,ResearchDataNotReady
from trader.data.audit import build_data_audit
from trader.data.finmind_provider import FinMindDataProvider,write_provenance
from trader.data.historical_universe import twse_delisted,tpex_delisted
from trader.data.catalog import build_catalog
from trader.data.shioaji_research import ShioajiResearchClient,compare_bars
from trader.reporting.research_audit import build_research_audit
from trader.strategy.signal_engine import build_signals
from trader.backtest.engine import BacktestEngine
from trader.backtest.walk_forward import walk_forward
from trader.research.optimization import optimize_grid
from trader.research.ablation import run_ablation
from trader.research.manifest import write_manifest,config_hash,git_commit
from trader.research.statistics import bootstrap_trades,monte_carlo
from trader.research.verdict import evaluate
from trader.reporting.csv_report import write_csvs
from trader.reporting.html_report import write_html

app=typer.Typer(no_args_is_help=True);console=Console();LOG=ROOT/"logs"/"trader.log";LOG.parent.mkdir(exist_ok=True)
logging.basicConfig(filename=LOG,level=logging.INFO,format='%(message)s')
def event(name,**kw):logging.info(json.dumps({"timestamp":pd.Timestamp.now().isoformat(),"event":name,**kw},ensure_ascii=False,default=str))
def _data():
    repo=MarketRepository(ROOT/"data"/"processed");catalog=ROOT/"data"/"historical_universe.parquet"
    if catalog.exists():
        h=pd.read_parquet(catalog);symbols=h.loc[h.data_status=="READY","symbol"].astype(str).tolist()+["TAIEX","0050"]
        return {s:repo.load(s) for s in symbols if (repo.root/f"{s}.parquet").exists()}
    return {s:repo.load(s) for s in repo.symbols()}
def _feature_cache():
    # Pre-v2 cache has no dataset/config key and is intentionally invalid.
    return None
def _require_ready():
    result=research_readiness(ROOT)
    if not result.passed:
        failed=",".join(result.checks.loc[~result.checks.passed,"check"])
        console.print(f"[red]RESEARCH_DATA_NOT_READY[/]: {failed}")
        raise typer.Exit(2)
    return result
def _status():
    out={"altered":set(),"dispositions":{}}
    paths=[ROOT/"data"/"altered_trading_daily.parquet"] if (ROOT/"data"/"altered_trading_daily.parquet").exists() else list((ROOT/"data").glob("altered_trading_daily_T*.parquet"))
    for p in paths:
        d=pd.read_parquet(p);out["altered"]|={(str(x.symbol),pd.Timestamp(x.date)) for x in d.itertuples()}
    paths=[ROOT/"data"/"dispositions.parquet"] if (ROOT/"data"/"dispositions.parquet").exists() else list((ROOT/"data").glob("dispositions_T*.parquet"))
    for p in paths:
        for x in pd.read_parquet(p).itertuples():out["dispositions"].setdefault(str(x.symbol),[]).append((pd.Timestamp(x.start_date),pd.Timestamp(x.end_date)))
    return out

@app.command("download-data")
def download_data(start:str|None=None,end:str|None=None,full_market:bool=typer.Option(True,"--full-market/--configured-only")):
    """Download configured TWSE equities plus benchmarks to Parquet."""
    cfg=settings();provider=YahooDataProvider();repo=MarketRepository(ROOT/"data"/"processed");start=start or cfg["data"]["start_date"]
    if full_market:
        universe=OfficialUniverseProvider().current();universe.to_parquet(ROOT/"data"/"universe.parquet",index=False);universe.to_csv(ROOT/"reports"/"universe.csv",index=False)
        histories,failures=provider.histories(dict(zip(universe.symbol,universe.exchange)),start,end)
        for symbol,d in histories.items():repo.save(symbol,d)
        failures.to_csv(ROOT/"reports"/"download_failures.csv",index=False)
        for symbol in ["0050","^TWII"]:
            d=provider.history(symbol,start,end)
            if not d.empty:repo.save("TAIEX" if symbol=="^TWII" else symbol,d)
        cal=repo.load("TAIEX").date;manifest=quality_manifest(universe,repo,start,cal);manifest.to_csv(ROOT/"reports"/"data_quality.csv",index=False)
        console.print(f"Universe {len(universe)}; downloaded {manifest.downloaded.sum()}; failures {(~manifest.downloaded).sum()}");event("full_market_download",universe=len(universe),downloaded=int(manifest.downloaded.sum()));return
    symbols=list(cfg["data"]["symbols"])+["^TWII"]
    ok=0
    for symbol in symbols:
        key="TAIEX" if symbol=="^TWII" else symbol
        try:
            d=provider.history(symbol,start,end)
            if not d.empty:repo.save(key,d);ok+=1;console.print(f"[green]saved[/] {key}: {len(d)} rows")
            else:console.print(f"[yellow]no data[/] {key}")
        except Exception as e:console.print(f"[red]failed[/] {key}: {e}")
    event("download_complete",symbols=ok);console.print(f"Downloaded {ok}/{len(symbols)} datasets")

@app.command("download-universe")
def download_universe():
    u=OfficialUniverseProvider().current();u.to_parquet(ROOT/"data"/"universe.parquet",index=False);u.to_csv(ROOT/"reports"/"universe.csv",index=False)
    console.print(f"TWSE: {(u.exchange=='TWSE').sum()}, TPEx: {(u.exchange=='TPEx').sum()}, total ordinary-stock issuers: {len(u)}")

@app.command("audit-data")
def audit_data():
    path=ROOT/"data"/"universe.parquet"
    if not path.exists():raise typer.BadParameter("Run download-universe first")
    u=pd.read_parquet(path);repo=MarketRepository(ROOT/"data"/"processed");m=quality_manifest(u,repo,settings()["data"]["start_date"],repo.load("TAIEX").date);m.to_csv(ROOT/"reports"/"data_quality.csv",index=False)
    summary={"universe":len(u),"downloaded":int(m.downloaded.sum()),"missing":int((~m.downloaded).sum()),"history_120d":int(m.has_120_days.sum()),"invalid_ohlcv_rows":int(m.invalid_ohlcv_rows.sum()),"point_in_time_complete":bool(u.point_in_time_complete.all())}
    (ROOT/"reports"/"data_audit.json").write_text(json.dumps(summary,indent=2),encoding="utf-8");console.print(summary)

@app.command("sanitize-data")
def sanitize_data():
    """Remove rows that cannot represent an executable listed-market price."""
    repo=MarketRepository(ROOT/"data"/"processed");removed=[]
    for symbol in repo.symbols():
        d=repo.load(symbol);mask=(d[["open","high","low","close"]]<=0).any(axis=1)
        if mask.any():
            for x in d.loc[mask,["date","open","high","low","close","volume"]].itertuples(index=False):removed.append({"symbol":symbol,**x._asdict(),"reason":"NONPOSITIVE_OHLC_NOT_EXECUTABLE"})
            repo.save(symbol,d.loc[~mask].copy())
    out=pd.DataFrame(removed,columns=["symbol","date","open","high","low","close","volume","reason"]);out.to_csv(ROOT/"reports"/"removed_nonprice_rows.csv",index=False)
    console.print(f"Removed {len(out)} non-price rows from {out.symbol.nunique() if not out.empty else 0} symbols; raw/official source partitions remain unchanged")

@app.command("download-historical-universe")
def download_historical_universe(start_year:int=2018):
    """Save official delisting masters used to audit survivorship coverage."""
    tw=twse_delisted();otc=tpex_delisted(start_year)
    d=pd.concat([tw,otc],ignore_index=True);d=d[d.delisting_date>=pd.Timestamp(f"{start_year}-01-01")]
    d.to_parquet(ROOT/"data"/"delisted_universe.parquet",index=False);d.to_csv(ROOT/"reports"/"delisted_universe.csv",index=False)
    console.print(f"Delisted since {start_year}: TWSE {(d.exchange=='TWSE').sum()}, TPEx {(d.exchange=='TPEx').sum()}")

@app.command("repair-twse-data")
def repair_twse_data(start:str="2018-01-01",end:str|None=None,include_delisted:bool=True,max_symbols:int|None=None):
    """Repair missing/corrupt TWSE histories and load delisted names via FinMind."""
    repo=MarketRepository(ROOT/"data"/"processed");u=pd.read_parquet(ROOT/"data"/"universe.parquet")
    calendar=repo.load("TAIEX").date;m=quality_manifest(u,repo,start,calendar)
    bad=m[(m.exchange=="TWSE")&((~m.downloaded)|(m.invalid_ohlcv_rows>0))].symbol.astype(str).tolist()
    delisted=twse_delisted();delisted=delisted[delisted.delisting_date>=pd.Timestamp(start)]
    targets=bad+([x for x in delisted.symbol.astype(str) if x not in set(u.symbol.astype(str))] if include_delisted else [])
    targets=list(dict.fromkeys(targets))
    provenance_path=ROOT/"data"/"ohlcv_provenance.parquet"
    already=set(pd.read_parquet(provenance_path).symbol.astype(str)) if provenance_path.exists() else set()
    targets=[s for s in targets if s in bad or s not in already];targets=targets[:max_symbols] if max_symbols else targets
    listing_dates=dict(zip(u.symbol.astype(str),u.listing_date));provider=FinMindDataProvider();records=[];fail=[]
    for n,symbol in enumerate(targets,1):
        try:
            d=provider.history(symbol,start,end,listing_dates.get(symbol),infer_listing_boundary=symbol not in listing_dates)
            if d.empty:raise RuntimeError("empty_history")
            repo.save(symbol,d[["date","open","high","low","close","volume"]])
            records.append({"symbol":symbol,"exchange":"TWSE","source":"FinMind TaiwanStockPrice","purpose":"repair_missing_or_invalid" if symbol in bad else "delisted_survivorship_history","rows":len(d),"first_date":d.date.min(),"last_date":d.date.max(),"retrieved_at":pd.Timestamp.now()})
        except Exception as exc:fail.append({"symbol":symbol,"reason":repr(exc)})
        if n%25==0:console.print(f"TWSE repair progress {n}/{len(targets)}; succeeded {len(records)}; failed {len(fail)}")
    prov_path=ROOT/"data"/"ohlcv_provenance.parquet";write_provenance(prov_path,records)
    pd.DataFrame(fail).to_csv(ROOT/"reports"/"twse_repair_failures.csv",index=False)
    console.print(f"TWSE targets {len(targets)}; succeeded {len(records)}; failed {len(fail)}")

@app.command("build-data-catalog")
def data_catalog():
    catalog,sources,excluded=build_catalog(ROOT)
    console.print(f"Historical symbols {len(catalog)}; research-ready {int((catalog.data_status=='READY').sum())}; explicitly excluded {len(excluded)}")
    console.print(sources.to_string(index=False))

@app.command("collect-shioaji")
def collect_shioaji(crosscheck_symbols:int=100,crosscheck_days:int=90):
    """Authenticated read-only contract snapshot and OHLCV cross-check."""
    from dotenv import load_dotenv
    load_dotenv(ROOT/".env");u=pd.read_parquet(ROOT/"data"/"universe.parquet");repo=MarketRepository(ROOT/"data"/"processed")
    client=ShioajiResearchClient().login()
    try:
        snapshot=client.stock_snapshot(u.symbol.astype(str));snapshot.to_parquet(ROOT/"data"/"shioaji_contract_snapshot.parquet",index=False);snapshot.to_csv(ROOT/"reports"/"shioaji_contract_snapshot.csv",index=False)
        # Deterministic stratified sample across both exchanges and symbol order.
        sample=pd.concat([g.iloc[::max(1,len(g)//max(1,crosscheck_symbols//2))] for _,g in u.sort_values("symbol").groupby("exchange")]).head(crosscheck_symbols)
        comparisons=[];end=pd.Timestamp.today().normalize();start=end-pd.Timedelta(days=crosscheck_days)
        for symbol in sample.symbol.astype(str):
            broker=client.kbars(symbol,start.strftime("%Y-%m-%d"),end.strftime("%Y-%m-%d"));ref=repo.load(symbol);cmp=compare_bars(ref[ref.date>=start],broker)
            if not cmp.empty:cmp.insert(0,"symbol",symbol);comparisons.append(cmp)
        cross=pd.concat(comparisons,ignore_index=True) if comparisons else pd.DataFrame();cross.to_parquet(ROOT/"data"/"shioaji_ohlcv_crosscheck.parquet",index=False);cross.to_csv(ROOT/"reports"/"shioaji_ohlcv_crosscheck.csv",index=False)
        console.print(f"Shioaji read-only collection: contracts {len(snapshot)}, cross-check rows {len(cross)}; no account/order method invoked")
    finally:client.close()

@app.command("research-readiness")
def readiness():
    r=research_readiness(ROOT);console.print(r.checks.to_string(index=False));console.print(f"dataset_version={r.dataset_version} dataset_hash={r.dataset_hash}");raise typer.Exit(0 if r.passed else 2)

@app.command("data-audit")
def data_audit_command():
    result=build_data_audit(ROOT);r=research_readiness(ROOT);console.print(result);console.print(r.checks.to_string(index=False));raise typer.Exit(0 if r.passed else 2)

@app.command("build-research-audit")
def research_audit(start:str="2019-01-01",allow_incomplete:bool=False):
    ready=research_readiness(ROOT)
    if not ready.passed and not allow_incomplete:raise typer.BadParameter("RESEARCH_DATA_NOT_READY: audit build refused")
    funnel=build_research_audit(_data(),settings(),ROOT/"reports",_status(),start);console.print(funnel)

@app.command("download-official-daily")
def download_official_daily(start:str="2018-01-01",end:str|None=None,workers:int=4,exchange:str="ALL",max_partitions:int|None=None,consolidate:bool=typer.Option(True,"--consolidate/--no-consolidate")):
    """Build survivorship-aware OHLCV from official daily whole-market tables."""
    taiex=MarketRepository(ROOT/"data"/"processed").load("TAIEX");end_ts=pd.Timestamp(end) if end else taiex.date.max();dates=taiex.loc[(taiex.date>=pd.Timestamp(start))&(taiex.date<=end_ts),"date"]
    exchanges=("TWSE","TPEx") if exchange.upper()=="ALL" else (exchange,)
    provider=OfficialDailyMarketProvider(ROOT/"data"/"official_daily");fail=provider.download(dates,workers,exchanges,max_partitions);fail.to_csv(ROOT/"reports"/f"official_download_failures_{exchange}.csv",index=False)
    if not consolidate:console.print(f"Checkpoint download complete; failures: {len(fail)}");return
    hist=provider.consolidate(MarketRepository(ROOT/"data"/"processed"),dates,exchanges)
    suffix="" if exchange.upper()=="ALL" else f"_{exchange}"
    hist.to_parquet(ROOT/"data"/f"historical_universe{suffix}.parquet",index=False);hist.to_csv(ROOT/"reports"/f"historical_universe{suffix}.csv",index=False)
    console.print(f"Official dates: {len(dates)}, historical symbols: {len(hist)}, failed day/exchange requests: {len(fail)}")

@app.command("download-status-history")
def download_status_history(start:str="2019-01-01",end:str|None=None,workers:int=4,exchange:str="ALL",max_dates:int|None=None):
    repo=MarketRepository(ROOT/"data"/"processed");dates=repo.load("TAIEX").date;dates=dates[(dates>=pd.Timestamp(start))&((dates<=pd.Timestamp(end)) if end else True)]
    exchanges=("TWSE","TPEx") if exchange.upper()=="ALL" else (exchange,)
    audit_path=ROOT/"data"/f"status_query_audit_{exchange}.parquet";old_audit=pd.read_parquet(audit_path) if audit_path.exists() else pd.DataFrame()
    if not old_audit.empty:
        completed={pd.Timestamp(x) for x in old_audit.loc[old_audit.success,"date"]};dates=dates[~dates.isin(completed)]
    if max_dates:dates=dates.iloc[:max_dates]
    disp=dispositions(start,end) if exchange.upper()=="ALL" else pd.DataFrame();altered,audit=altered_daily(dates,workers,exchanges,return_audit=True)
    altered_path=ROOT/"data"/f"altered_trading_daily_{exchange}.parquet";old_altered=pd.read_parquet(altered_path) if altered_path.exists() else pd.DataFrame()
    altered=pd.concat([old_altered,altered],ignore_index=True).drop_duplicates(["date","symbol","status"])
    audit=pd.concat([old_audit,audit],ignore_index=True).sort_values(["exchange","date"]).drop_duplicates(["exchange","date"],keep="last")
    if not disp.empty:disp.to_parquet(ROOT/"data"/"dispositions.parquet",index=False)
    altered.to_parquet(altered_path,index=False)
    audit.to_parquet(audit_path,index=False)
    if not disp.empty:disp.to_csv(ROOT/"reports"/"dispositions.csv",index=False)
    altered.to_csv(ROOT/"reports"/f"altered_trading_daily_{exchange}.csv",index=False);audit.to_csv(ROOT/"reports"/f"status_query_audit_{exchange}.csv",index=False);console.print(f"Disposition periods: {len(disp)}; altered/suspended symbol-days: {len(altered)}; successful date/exchange queries: {int(audit.success.sum())}/{len(audit)}")

@app.command("download-dispositions")
def download_dispositions(start:str="2019-01-01",end:str|None=None,exchange:str="ALL"):
    exchanges=("TWSE","TPEx") if exchange.upper()=="ALL" else (exchange,);d=dispositions(start,end,exchanges);d.to_parquet(ROOT/"data"/f"dispositions_{exchange}.parquet",index=False);d.to_csv(ROOT/"reports"/f"dispositions_{exchange}.csv",index=False)
    audit=pd.DataFrame([{"exchange":exchange,"start_date":pd.Timestamp(start),"end_date":pd.Timestamp(end or date.today()),"success":True,"rows":len(d),"retrieved_at":pd.Timestamp.now()}]);audit.to_parquet(ROOT/"data"/f"disposition_query_audit_{exchange}.parquet",index=False)
    console.print(f"Disposition periods: {len(d)}")

@app.command("combine-status-data")
def combine_status_data():
    """Combine only when both exchanges exist; never silently treat absence as clean."""
    for stem in ("dispositions","altered_trading_daily"):
        paths=[ROOT/"data"/f"{stem}_{ex}.parquet" for ex in ("TWSE","TPEx")]
        missing=[str(p.name) for p in paths if not p.exists()]
        if missing:raise typer.BadParameter(f"Cannot combine {stem}; missing {missing}")
        d=pd.concat([pd.read_parquet(p) for p in paths],ignore_index=True).drop_duplicates()
        d.to_parquet(ROOT/"data"/f"{stem}.parquet",index=False);d.to_csv(ROOT/"reports"/f"{stem}.csv",index=False)
        console.print(f"{stem}: {len(d)} rows")

@app.command()
def scan(date_:str|None=typer.Option(None,"--date")):
    cfg=settings();data=_data();rows=[]
    for sym,d in data.items():
        if sym in ("TAIEX","0050") or len(d)<120:continue
        f=build_signals(d,cfg,data.get("TAIEX",pd.DataFrame()).get("date",None));cut=f[f.date<=pd.Timestamp(date_)] if date_ else f
        if cut.empty:continue
        r=cut.iloc[-1]
        if bool(r.candidate):rows.append({"Symbol":sym,"Price":r.close,"Osc":r.oscillation_score,"Low":r.low_score,"MR Prob":r.mr_probability,"Regime":r.regime_risk_score,"Final":r.final_score,"TP":r.take_profit})
    rows=sorted(rows,key=lambda x:x["Final"],reverse=True);table=Table("Rank","Symbol","Price","Osc","Low","MR Prob","Regime","Final","TP")
    for i,r in enumerate(rows,1):table.add_row(str(i),r["Symbol"],f'{r["Price"]:.2f}',f'{r["Osc"]:.1f}',f'{r["Low"]:.1f}',f'{r["MR Prob"]:.0%}',f'{r["Regime"]:.0f}',f'{r["Final"]:.1f}',f'{r["TP"]:.0%}')
    console.print(table);pd.DataFrame(rows).to_csv(ROOT/"reports"/"candidates.csv",index=False);event("scan",date=date_,candidates=len(rows))

@app.command()
def backtest(capital:float|None=None):
    cfg=settings();ready=_require_ready();data=_data();status=_status()
    for name in ("development","validation"):
        start,end=cfg["research"][name];out=ROOT/"reports"/name
        for scenario in ("OPTIMISTIC","BASE","CONSERVATIVE"):
            result=BacktestEngine(data,cfg,capital,status=status).run(start,end,None,True,scenario,False);target=out/scenario.lower();write_csvs(result,target);pd.DataFrame([result["metrics"]]).to_csv(target/"metrics.csv",index=False)
            if scenario=="BASE":write_html(result,out/"backtest.html")
        write_manifest(out/"run_manifest.json",ready,cfg,[start,end],"NEXT_DAY_OPEN",name)
    console.print("Development and validation completed; final OOS was not touched")

@app.command()
def optimize(start:str|None=None,end:str|None=None):
    cfg=settings();_require_ready();period=cfg["research"]["development"];out=optimize_grid(_data(),cfg,start or period[0],end or period[1],_status(),None,cfg["research"]["minimum_training_trades"]);path=ROOT/"reports"/"development"/"optimization.csv";out.to_csv(path,index=False);console.print(f"Wrote {len(out)} development-only combinations")

@app.command("ablation")
def ablation_command():
    cfg=settings();_require_ready();start,end=cfg["research"]["development"];out=run_ablation(_data(),cfg,start,end,_status());out.to_csv(ROOT/"reports"/"research"/"ablation.csv",index=False);console.print(out.to_string(index=False))

@app.command("walk-forward")
def walk_forward_command(start:str="2019-01-01",end:str|None=None):
    cfg=settings();_require_ready();out=walk_forward(_data(),cfg,start,end or cfg["research"]["validation"][1],_status());out.to_csv(ROOT/"reports"/"walk_forward"/"folds.csv",index=False);console.print(f"Wrote {len(out)} walk-forward windows")

@app.command("final-oos")
def final_oos():
    cfg=settings();ready=_require_ready();lock=ROOT/"config"/"final_oos_lock.json"
    if lock.exists() and json.loads(lock.read_text(encoding="utf-8")).get("executed"):raise typer.BadParameter("FINAL_OOS_LOCKED_ALREADY_EXECUTED")
    opt=ROOT/"reports"/"development"/"optimization.csv"
    if not opt.exists():raise typer.BadParameter("RUN_DEVELOPMENT_OPTIMIZATION_FIRST")
    best=pd.read_csv(opt).replace([float("inf"),float("-inf")],pd.NA).dropna(subset=["RobustScore"]).iloc[0];selected={"TP":best.TP,"LowPosition":best.LowPosition,"MRProbability":best.MRProbability};payload={"selected_parameters":selected,"data_version":ready.dataset_version,"dataset_hash":ready.dataset_hash,"config_hash":config_hash(cfg),"git_commit":git_commit(ROOT),"lock_timestamp":pd.Timestamp.now(tz="Asia/Taipei").isoformat(),"executed":False};lock.write_text(json.dumps(payload,indent=2),encoding="utf-8")
    import copy;c=copy.deepcopy(cfg);c["strategy"]["low_zone"]["max_price_position"]=best.LowPosition;c["strategy"]["mean_reversion"]["minimum_probability"]=best.MRProbability;start,end=c["research"]["final_oos"];data=_data();status=_status();results={}
    for scenario in ("OPTIMISTIC","BASE","CONSERVATIVE"):
        r=BacktestEngine(data,c,status=status).run(start,end,best.TP,True,scenario,False);results[scenario]=r;write_csvs(r,ROOT/"reports"/"final_oos"/scenario.lower())
    base=results["BASE"];boot=bootstrap_trades(base["trades"]);mc=monte_carlo(base["trades"]);boot.to_csv(ROOT/"reports"/"final_oos"/"bootstrap.csv",index=False);mc.to_csv(ROOT/"reports"/"final_oos"/"monte_carlo.csv",index=False);write_html(base,ROOT/"reports"/"final_oos"/"backtest.html");write_manifest(ROOT/"reports"/"final_oos"/"run_manifest.json",ready,c,[start,end],"NEXT_DAY_OPEN", "final_oos");payload["executed"]=True;lock.write_text(json.dumps(payload,indent=2),encoding="utf-8");console.print("Final OOS executed once and locked")

@app.command()
def report():
    p=ROOT/"reports"/"final_oos"/"base"
    if not p.exists():raise typer.BadParameter("NO_FINAL_OOS_RESULT")
    from trader.backtest.metrics import metrics
    from trader.backtest.benchmarks import benchmark_comparison
    eq=pd.read_csv(p/"equity_curve.csv",parse_dates=["date"]);tr=pd.read_csv(p/"trades.csv");m=metrics(eq,tr,float(settings()["backtest"]["initial_capital_twd"]));sig=pd.read_csv(p/"signals.csv");bench=benchmark_comparison(_data(),eq.date.min(),eq.date.max());bench.to_csv(ROOT/"reports"/"final_oos"/"benchmarks.csv",index=False);write_html({"equity":eq,"trades":tr,"signals":sig,"metrics":m},ROOT/"reports"/"final_oos"/"backtest.html",benchmarks=bench);console.print(ROOT/"reports"/"final_oos"/"backtest.html")

@app.command()
def paper():
    from trader.broker.paper import PaperBroker
    from trader.execution.position_manager import PositionManager
    state=PositionManager(PaperBroker(settings()["backtest"]["initial_capital_twd"])).recover();event("paper_start",**state);console.print("Paper broker initialized and account state synchronized; no real orders can be sent.")

@app.command()
def live():
    if not live_enabled():console.print("[red]BLOCKED: LIVE_TRADING_ENABLED=false (default). No login or order was sent.[/]");raise typer.Exit(2)
    from trader.broker.shioaji import ShioajiBroker
    broker=ShioajiBroker().login();state={"positions":broker.get_positions(),"open_orders":broker.get_open_orders(),"settlements":broker.get_settlements()};event("live_sync",state=str(state));console.print("Live account synchronized. Scheduler/order submission requires an explicit operator action.")

safety=typer.Typer();app.add_typer(safety,name="safety")
@safety.command("unlock")
def safety_unlock():
    marker=ROOT/"data"/"safe_mode.lock"
    if marker.exists():marker.unlink();console.print("SAFE_MODE manually unlocked")
    else:console.print("SAFE_MODE was not locked")

if __name__=="__main__":app()
