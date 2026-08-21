from pathlib import Path
import pandas as pd
def write_csvs(result,out_dir,sensitivity=None):
    p=Path(out_dir);p.mkdir(parents=True,exist_ok=True)
    result["trades"].to_csv(p/"trades.csv",index=False);result["equity"].to_csv(p/"equity_curve.csv",index=False);result["equity"].to_csv(p/"daily_portfolio.csv",index=False);result["signals"].to_csv(p/"signals.csv",index=False)
    pd.DataFrame([result["metrics"]]).to_csv(p/"metrics.csv",index=False)
    (sensitivity if sensitivity is not None else pd.DataFrame()).to_csv(p/"sensitivity.csv",index=False)

