# Quantitative Strategy Backtesting Framework

A minimal single-instrument, long-only backtester with next-bar execution, costs and a buy-and-hold benchmark.

## Overview

This project separates the timing of signal generation from trade execution. The example strategy is a moving-average crossover; the engine is designed to accept a callable returning long or flat after observing a completed bar.

## Method

- Read ordered timestamp, open and close prices and reject invalid prices or non-increasing timestamps.
- Compute signals at bar close and fill at the next bar's open, avoiding same-close execution of the newly observed signal.
- Hold whole units using a cash account. Apply adverse slippage and a proportional fee on each fill.
- Mark equity at each bar close, settle remaining positions at the final close and export trades and equity.
- Compare with a buy-and-hold account using the same execution start and cost assumptions.

## Run

```bash
python backtest.py
python backtest.py nifty.csv --fast 10 --slow 30 --capital 100000 --fee-bps 1 --slip-bps 2 --out nifty_run
```

Input example (format only):

```csv
timestamp,open,close
2026-01-05T09:15:00,100.00,100.10
2026-01-05T09:16:00,100.10,100.15
```

The output directory contains `trades.csv` and `equity.csv` with the benchmark equity series. Defaults: 10/30-bar averages, 100,000 capital, 1 bp fee and 2 bps slippage per fill.

## Reproduced results

Synthetic price series, seed 42, 1,875 bars.

| Metric | Result |
|---|---:|
| Ending cash | 100,258.82 |
| Strategy net return | +0.26% |
| Buy-and-hold return | +0.96% |
| Maximum bar-close drawdown | 6.01% |
| Closed trades | 39 |
| Win rate after costs | 35.9% |

The moving-average strategy underperformed the benchmark. No profitable strategy or real-market performance is claimed.

## Limitations and next steps

The engine is long-only and single-instrument, without dividends, shorting, partial fills or intrabar stops. Bar-close drawdown may miss intrabar losses. Future work: independent walk-forward testing, richer execution models and portfolio-level risk accounting.

## Requirements and files

Python 3.9+; no third-party dependencies are required.

- `backtest.py` — original project implementation.
- `requirements.txt` — dependency notes.
- `results/` — outputs from the example run, including [terminal output](results/example_run.txt).

The example was rerun using the bundled source. This is a research/educational project; it is not a production system.
