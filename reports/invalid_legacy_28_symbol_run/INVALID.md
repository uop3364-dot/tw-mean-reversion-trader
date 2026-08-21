# Invalid legacy research output

These files are preserved only for auditability. They are **not valid research
results** because the run used a hard-coded 28-symbol list (including ETF 0050)
instead of the full point-in-time TWSE/TPEx ordinary-stock universe. The six
trades and all metrics from this directory must not be cited as strategy results.

Replacement outputs may be generated only after `python -m trader
research-readiness` passes every check.
