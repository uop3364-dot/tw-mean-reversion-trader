# TW Mean Reversion Trader

## Research status

**NOT YET VALIDATED — GRADE_C_BLOCKED (Research Data Recovery v3, 2026-08-21).**

Pre-audit results are retained under `reports/legacy/` and explicitly marked
`LEGACY_INVALID_OR_UNVALIDATED`. They are not evidence of performance.

One authoritative readiness gate protects every formal research command. The
v3 recovery resolved every original off-calendar row, established an official
security master, separated raw trade prices from adjusted analysis prices, and
recovered 5,773 verified TPEx corporate actions. Formal research remains
blocked: TWSE imposed an endpoint security block before full official OHLCV and
action recovery completed. Remaining gaps are explicit in
`reports/data_audit/blockers.csv`; final OOS remains unavailable.

## Install and test

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[test]"
pytest -q
```

## Reproduce the audit

```powershell
python -m trader data-audit
python -m trader research-readiness
```

Both commands return non-zero while a hard requirement fails. Machine-readable
results are in `reports/data_audit/`.

After every requirement passes, the formal sequence is:

```powershell
python -m trader ablation
python -m trader backtest
python -m trader optimize
python -m trader walk-forward
python -m trader final-oos
python -m trader report
```

`backtest` covers development (2019–2021) and validation (2022–2023) only.
`final-oos` is a separate explicit one-time locked operation for 2024 onward.
It is never run automatically.

## Methodology

- 2018: warm-up only
- 2019–2021: development
- 2022–2023: validation
- 2024–latest: locked final OOS
- Entry: next trading-session open
- Intraday TP: daily high may trigger a fill
- Close-derived thesis/time exits: next session open
- No fixed-percentage stop loss and no averaging down
- T+2 settlement uses exchange sessions
- Formal scenarios: optimistic, base, conservative
- LLM output is never part of historical research

The original hypothesis is preserved: repeated oscillation plus an ideal
low-price zone and conditional mean reversion, while rejecting a broken price
regime. A large decline by itself is neither a buy nor an exit reason.

## Safety

Live trading is disabled by default. `.env` must explicitly set
`LIVE_TRADING_ENABLED=true` before a live order can be sent.
`TRADING_KILL_SWITCH=true` blocks buys while allowing exits. Secrets,
certificates, and private keys are excluded by `.gitignore`.
