"""Single-instrument, long-only backtester. Python 3.9+, standard library only.

Run: python backtest.py
CSV: python backtest.py nifty.csv --fast 10 --slow 30 --out nifty_run

CSV columns: timestamp,open,close (extra columns are ignored). Use ISO dates
or datetimes, in order, with one consistent timezone. Each row is one bar.
The cash account holds whole units and carries them across sessions. Index
prices give a hypothetical unit-value simulation. Use instrument prices and
appropriate costs to study a particular ETF. No dividends or interest.
"""

import argparse
import csv
import math
import random
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import NamedTuple


class Bar(NamedTuple):
    time: datetime
    open: float
    close: float


def read_bars(path):
    with path.open(encoding="utf-8-sig", newline="") as source:
        rows = csv.DictReader(source)
        names = [name.strip().lower() for name in rows.fieldnames or []]
        if len(names) != len(set(names)) or not {"timestamp", "open", "close"} <= set(names):
            raise ValueError("CSV needs distinct headers including timestamp, open and close")
        rows.fieldnames = names
        previous = None
        for row in rows:
            try:
                stamp = datetime.fromisoformat(row["timestamp"].strip().replace("Z", "+00:00"))
                bar = Bar(stamp, float(row["open"]), float(row["close"]))
                if not all(math.isfinite(p) and p > 0 for p in (bar.open, bar.close)):
                    raise ValueError("prices must be positive and finite")
                if previous is not None and stamp <= previous:
                    raise ValueError("timestamps must increase strictly")
            except (ValueError, TypeError, AttributeError) as exc:
                raise ValueError(f"CSV line {rows.line_num}: {exc}") from exc
            previous = stamp
            yield bar


def demo_bars():
    rng = random.Random(42)
    price = 100.0
    start = datetime(2026, 1, 5, 9, 15)
    for day in range(5):
        for minute in range(375):
            opening = round(price * math.exp(rng.gauss(0, 0.0004)), 2)
            drift = 0.00025 * math.sin(minute / 32)
            price = round(opening * math.exp(drift + rng.gauss(0, 0.0015)), 2)
            yield Bar(start + timedelta(days=day, minutes=minute), opening, price)


class MovingAverage:
    """Hold when the fast average is above the slow average at the close."""

    def __init__(self, fast, slow):
        if not 0 < fast < slow:
            raise ValueError("windows must satisfy 0 < fast < slow")
        self.fast = deque(maxlen=fast)
        self.slow = deque(maxlen=slow)

    def __call__(self, bar):
        self.fast.append(bar.close)
        self.slow.append(bar.close)
        if len(self.slow) < self.slow.maxlen:
            return False
        return sum(self.fast) / len(self.fast) > sum(self.slow) / len(self.slow)


class Trade(NamedTuple):
    entry_time: datetime
    exit_time: datetime
    units: int
    entry_fill: float
    exit_fill: float
    fees: float
    net_pnl: float
    exit_reason: str


class Mark(NamedTuple):
    timestamp: datetime
    cash: float
    units: int
    equity: float
    drawdown_pct: float


def run(bars, signal, capital=100000, fee_bps=1, slip_bps=2):
    """signal(bar) sees one completed bar and returns True (long) or False (flat)."""
    if not math.isfinite(capital) or capital <= 0:
        raise ValueError("capital must be positive and finite")
    if not all(0 <= x < 10000 for x in (fee_bps, slip_bps)):
        raise ValueError("costs must be in [0, 10000) basis points")
    fee = fee_bps / 10000
    slip = slip_bps / 10000
    cash = peak = capital
    units = 0
    want_long = False
    trades, curve = [], []

    def sell(time, reference, reason):
        nonlocal cash, units
        fill = reference * (1 - slip)
        proceeds = units * fill
        exit_fee = proceeds * fee
        cash += proceeds - exit_fee
        pnl = units * (fill - entry_fill) - entry_fee - exit_fee
        trades.append(Trade(entry_time, time, units, entry_fill, fill,
                            entry_fee + exit_fee, pnl, reason))
        units = 0

    for bar in bars:
        if want_long and units == 0:
            entry_fill = bar.open * (1 + slip)
            units = math.floor(cash / (entry_fill * (1 + fee)))
            entry_fee = units * entry_fill * fee
            cash -= units * entry_fill + entry_fee
            entry_time = bar.time
        elif not want_long and units:
            sell(bar.time, bar.open, "signal at previous close")

        equity = cash + units * bar.close
        peak = max(peak, equity)
        drawdown = 100 * (1 - equity / peak)
        curve.append(Mark(bar.time, cash, units, equity, drawdown))
        want_long = signal(bar)

    if not curve:
        raise ValueError("no price bars")
    if units:
        # Replace the final mark with settled cash, including closing costs.
        sell(bar.time, bar.close, "final close")
        prior_peak = max(capital, max((m.equity for m in curve[:-1]), default=capital))
        drawdown = 100 * (1 - cash / max(prior_peak, cash))
        curve[-1] = Mark(bar.time, cash, 0, cash, drawdown)
    return trades, curve


def write_rows(path, columns, rows):
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.writer(output)
        writer.writerow(columns)
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("csv", nargs="?", type=Path)
    parser.add_argument("--fast", type=int, default=10)
    parser.add_argument("--slow", type=int, default=30)
    parser.add_argument("--capital", type=float, default=100000)
    parser.add_argument("--fee-bps", type=float, default=1, help="fee per fill, basis points")
    parser.add_argument("--slip-bps", type=float, default=2, help="adverse slippage per fill")
    parser.add_argument("--out", type=Path, default=Path("backtest_results"))
    args = parser.parse_args()
    costs = (args.capital, args.fee_bps, args.slip_bps)
    try:
        bars = list(read_bars(args.csv) if args.csv else demo_bars())
        trades, curve = run(bars, MovingAverage(args.fast, args.slow), *costs)
        # Both accounts can first trade at the second open.
        _, hold = run(bars, lambda bar: True, *costs)
        args.out.mkdir(parents=True, exist_ok=True)
        write_rows(args.out / "trades.csv", Trade._fields, trades)
        marks = (tuple(mark) + (baseline.equity,) for mark, baseline in zip(curve, hold))
        write_rows(args.out / "equity.csv", Mark._fields + ("buy_hold_equity",), marks)
    except (OSError, ValueError, csv.Error) as exc:
        parser.exit(2, f"Backtest error: {exc}\n")

    final = curve[-1].equity
    wins = sum(t.net_pnl > 0 for t in trades)
    print(f"Data           {args.csv or 'synthetic demo (seed 42)'} | {len(bars):,} bars")
    print(f"Ending cash    {final:,.2f}")
    print(f"Net return     {100 * (final / args.capital - 1):.2f}%")
    print(f"Buy and hold   {100 * (hold[-1].equity / args.capital - 1):.2f}%")
    print(f"Max drawdown   {max(m.drawdown_pct for m in curve):.2f}% (at bar closes)")
    print(f"Closed trades  {len(trades)}")
    if trades:
        print(f"Win rate       {wins / len(trades):.1%} after costs")
    print(f"Trade log and equity curve written to {args.out.resolve()}")


if __name__ == "__main__":
    main()
