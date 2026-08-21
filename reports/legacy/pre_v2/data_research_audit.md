# Data and research audit — 2026-08-21

## Why the earlier result is invalid

The earlier six-trade backtest used a hard-coded list of 28 symbols and included
ETF 0050 in the research inputs. It did not represent the TWSE/TPEx ordinary-stock
market. Those outputs are retained under `invalid_legacy_28_symbol_run/` only as
an audit trail and must not be cited as a strategy result.

## Universe evidence

| Dataset/action | Result | Research reason |
|---|---:|---|
| Current issuer masters: TWSE `t187ap03_L`, TPEx `mopsfin_t187ap03_O` | 1,979 ordinary-stock issuers (1,089 TWSE; 890 TPEx) | Company masters exclude ETF/ETN/warrant product lists and provide exchange/listing identity. |
| Official delisting masters since 2018 | 54 TWSE; 71 TPEx | Include stocks that disappeared, so failed/delisted firms are not omitted by survivorship bias. |
| Official TPEx daily market observations | 2,095 trading days; 962 historical symbols; zero missing dates | Establish point-in-time membership and replace corrupt third-party TPEx OHLC. |
| Combined historical catalog | 2,087 unique symbols | One explicit row per research symbol, source, first/last date, trading-day count and readiness status. |
| Minimum-history rule | 2,062 ready; 25 excluded with explicit reasons | Enforce the specified 120-day minimum instead of treating short histories as missing data. |

## Price evidence and validation

Current-universe coverage is 1,979/1,979, with zero missing symbols and zero OHLC
invariant violations after repair. TPEx uses official daily tables. TWSE currently
uses symbol-level provenance: validated Yahoo bootstrap histories plus targeted
FinMind replacement for missing/corrupt and delisted symbols. FinMind records
before the official listing date are excluded because its pre-listing emerging
market rows use a different field meaning and are not valid listed-market OHLC.

Each accepted bar must satisfy: `high >= low`, `high >= max(open, close)`,
`low <= min(open, close)`, non-negative volume, unique date, and calendar coverage.
The detailed outputs are `data_quality.csv`, `historical_universe.csv`,
`data_source_summary.csv`, `data_exclusions.csv`, and the Parquet provenance file.

## Formal strategy-filter audit

All readiness checks now pass. The point-in-time audit covers 3,367,973
symbol-days. Sequential survivors are: history 3,328,388; data quality 3,049,627;
liquidity 1,138,308; oscillation 846,080; low zone 59,560; historical-event sample
48,171; MR probability 9,735; official safety status 9,638; regime 5,621; and final
ranking 5,591. Historical events use the next session open plus configured buy
slippage; their outcomes are revealed only after the complete forward horizon.

Official status history contains 3,117 disposition periods and 87,685 altered,
full-cash-delivery, or suspended symbol-days. Every one of the 1,850 requested
trading dates succeeded for both TWSE and TPEx. A restriction is checked both on
the signal date and again before next-session execution.

The adjusted 0050 benchmark field comes from Yahoo Finance Adjusted Close and is
used only for benchmark comparison; 0050 is never admitted to the stock strategy
universe. TAIEX remains the market-regime series and price-index benchmark.
