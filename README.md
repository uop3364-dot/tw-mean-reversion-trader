# TW Mean Reversion Auto Trader v0.1

可重現、規則式的台股震盪低位均值回歸研究與交易框架。回測不使用 LLM；訊號日收盤後產生候選，最早隔日開盤成交；沒有固定百分比停損，僅有 thesis-break 與時間退出。

## 安裝與執行

```powershell
cd tw-mean-reversion-trader
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[test]"
python -m trader download-data
python -m trader scan
python -m trader backtest --no-analysis
python -m trader optimize
python -m trader report
python -m trader paper
```

完整 `backtest` 預設會執行基準、walk-forward 與 150 組敏感度分析。快速驗證可用 `--no-analysis`（仍執行 walk-forward）。Yahoo provider 僅作 bootstrap/交叉檢查，不得作為正式研究的唯一行情來源。正式研究使用 TWSE/TPEx 官方每日全市場行情，並須通過 `python -m trader research-readiness`；任一市場缺交易日、缺歷史 universe 或缺處置/變更交易狀態時，`backtest` 預設拒絕執行。

## 實盤安全

`.env.example` 預設 `LIVE_TRADING_ENABLED=false`。在它未明確設為 `true` 時，`live` 在登入前即中止，Shioaji 下單函式也會再次檢查。`TRADING_KILL_SWITCH=true` 禁止 BUY、保留 SELL。憑證與 `.env` 已被 gitignore。

## 資料格式

CSV/Parquet 每檔一個 symbol，欄位為 `date, open, high, low, close, volume`。檔案放在 `data/processed/{symbol}.parquet`。目前 `config/strategy.yaml` 提供可運行的高流動性普通股起始清單；若要真正掃描完整市場，應匯入完整且具商品分類/處置狀態的 universe master。

## 重要限制

此程式是研究與自動化框架，不構成投資建議。免費行情可能有調整、缺漏或交易所分類限制；正式使用必須校驗 corporate actions、交易日曆、漲跌停、整股/零股撮合與券商回報。
