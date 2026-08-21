from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


def _table(frame: pd.DataFrame, empty: str = "No observations") -> str:
    return f"<p>{empty}</p>" if frame.empty else frame.to_html(index=False, border=0)


def write_html(result, path, sensitivity=None, benchmarks=None, walk_forward=None):
    eq = result["equity"].copy()
    tr = result["trades"].copy()
    fig = make_subplots(rows=4, cols=2, subplot_titles=(
        "Equity Curve", "Drawdown Curve", "Monthly Returns", "Annual Returns",
        "Trade Return Distribution", "Holding Day Distribution", "MAE Distribution", "MFE Distribution",
    ))
    if not eq.empty:
        eq["date"] = pd.to_datetime(eq["date"])
        fig.add_trace(go.Scatter(x=eq.date, y=eq.equity, name="Equity"), row=1, col=1)
        fig.add_trace(go.Scatter(x=eq.date, y=eq.equity / eq.equity.cummax() - 1, name="Drawdown"), row=1, col=2)
        daily = eq.set_index("date").equity.pct_change().fillna(0)
        monthly = (1 + daily).resample("ME").prod() - 1
        annual = (1 + daily).resample("YE").prod() - 1
        fig.add_trace(go.Bar(x=monthly.index, y=monthly, name="Monthly"), row=2, col=1)
        fig.add_trace(go.Bar(x=annual.index.year, y=annual, name="Annual"), row=2, col=2)
    if not tr.empty:
        fig.add_trace(go.Histogram(x=tr.return_pct, name="Returns"), row=3, col=1)
        fig.add_trace(go.Histogram(x=tr.holding_days, name="Holding"), row=3, col=2)
        fig.add_trace(go.Histogram(x=tr.mae, name="MAE"), row=4, col=1)
        fig.add_trace(go.Histogram(x=tr.mfe, name="MFE"), row=4, col=2)
    fig.update_layout(height=1250, title="Portfolio and trade diagnostics")
    important = ["Take Profit Hit Rate", "Median Days to TP", "90th Percentile MAE Before TP", "Percentage Never Reaching TP"]
    metrics = "".join(f"<tr><th>{k}</th><td>{v:.6g}</td></tr>" for k, v in result["metrics"].items())
    top = "".join(f"<li>{k}: {result['metrics'].get(k, 0):.6g}</li>" for k in important)
    sensitivity = sensitivity if sensitivity is not None else pd.DataFrame()
    benchmarks = benchmarks if benchmarks is not None else pd.DataFrame()
    walk_forward = walk_forward if walk_forward is not None else pd.DataFrame()
    exits = tr.groupby("exit_reason").size().rename("trades").reset_index() if not tr.empty else pd.DataFrame()
    top_trades = tr.nlargest(20, "return_pct") if not tr.empty else pd.DataFrame()
    worst_trades = tr.nsmallest(20, "return_pct") if not tr.empty else pd.DataFrame()
    html = f"""<html><head><meta charset='utf-8'><title>Backtest Report</title>
    <style>body{{font-family:Arial,sans-serif;margin:2rem}}table{{border-collapse:collapse}}th,td{{padding:.35rem .6rem;border:1px solid #ddd;text-align:right}}th{{background:#f3f3f3}}</style></head><body>
    <h1>Core no-fixed-stop evidence</h1><ol>{top}</ol><h2>Metrics</h2><table>{metrics}</table>
    <h2>Benchmark comparison</h2>{_table(benchmarks)}{fig.to_html(full_html=False, include_plotlyjs='cdn')}
    <h2>TP hit and exit reason distribution</h2>{_table(exits)}<h2>Top 20 trades</h2>{_table(top_trades)}
    <h2>Worst 20 trades</h2>{_table(worst_trades)}<h2>Walk-forward unseen-test windows</h2>{_table(walk_forward)}
    <h2>Parameter sensitivity</h2>{_table(sensitivity)}</body></html>"""
    Path(path).write_text(html, encoding="utf-8")
