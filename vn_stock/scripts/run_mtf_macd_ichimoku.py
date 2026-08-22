#!/usr/bin/env python3
"""
Crawl W/D/H1 (+ build H4), backtest MACD+RSI vs Ichimoku across timeframes.

Usage:
  .venv/bin/python -m vn_stock.scripts.run_mtf_macd_ichimoku
  .venv/bin/python -m vn_stock.scripts.run_mtf_macd_ichimoku --symbols VCB,FPT,HPG --no-fetch
"""

from __future__ import annotations

import argparse
import csv
import json
import time
from datetime import datetime
from pathlib import Path

from vn_stock import DATA_DIR
from vn_stock.backtest.engine import run_backtest
from vn_stock.data_loaders.vn_ohlcv import (
    build_h4_from_h1,
    load_ohlcv,
    update_ohlcv,
)
from vn_stock.data_loaders.vietnam_rates import load_vn_policy_rates, rates_snapshot

DEFAULT_SYMBOLS = [
    "VCB", "BID", "TCB", "CTG", "MBB",
    "FPT", "HPG", "MWG", "MSN", "GAS",
    "VHM", "VNM", "SSI", "ACB", "VPB",
]
STRATEGIES = ["macd_rsi", "ichimoku"]
TIMEFRAMES = ["1W", "1D", "4H", "1H"]


def ensure_data(symbols: list[str], delay: float = 4.0, fetch: bool = True) -> dict:
    """Update 1D/1W/1H and build 4H. Returns coverage stats."""
    coverage = {}
    for i, symbol in enumerate(symbols, 1):
        coverage[symbol] = {}
        for tf in ("1D", "1W", "1H"):
            print(f"[{i}/{len(symbols)}] {symbol} {tf}...", end=" ", flush=True)
            try:
                if fetch:
                    df = update_ohlcv(symbol, tf)
                else:
                    df = load_ohlcv(symbol, tf)
                n = 0 if df is None else len(df)
                coverage[symbol][tf] = n
                print(f"{n} bars")
            except Exception as e:
                coverage[symbol][tf] = 0
                print(f"ERR {e}")
            if fetch:
                time.sleep(delay)

        df4 = build_h4_from_h1(symbol)
        coverage[symbol]["4H"] = 0 if df4 is None else len(df4)
        print(f"         {symbol} 4H... {coverage[symbol]['4H']} bars (from 1H)")
    return coverage


def run_compare(symbols: list[str], start: str | None, end: str | None) -> list[dict]:
    rows = []
    total = len(symbols) * len(STRATEGIES) * len(TIMEFRAMES)
    done = 0
    for symbol in symbols:
        for tf in TIMEFRAMES:
            df = load_ohlcv(symbol, tf)
            min_bars = 80 if tf in ("1D", "1W") else 120
            if df is None or len(df) < min_bars:
                done += len(STRATEGIES)
                continue
            for strat in STRATEGIES:
                done += 1
                print(f"[{done}/{total}] {symbol} {strat} {tf}...", end=" ", flush=True)
                try:
                    r = run_backtest(
                        symbol=symbol,
                        strategy=strat,
                        interval=tf,
                        start_date=start,
                        end_date=end,
                    )
                    if r is None:
                        print("no data")
                        continue
                    row = {
                        "symbol": symbol,
                        "strategy": strat,
                        "interval": tf,
                        "num_trades": r.num_trades,
                        "total_return_pct": round(r.total_return_pct, 2),
                        "hold_return_pct": round(r.hold_return_pct, 2),
                        "alpha_pct": round(r.total_return_pct - r.hold_return_pct, 2),
                        "win_rate": round(r.win_rate, 1),
                        "profit_factor": round(r.profit_factor, 2),
                        "sharpe_ratio": round(r.sharpe_ratio, 2),
                        "max_drawdown_pct": round(r.max_drawdown_pct, 1),
                    }
                    rows.append(row)
                    print(
                        f"ret={row['total_return_pct']:+.1f}% "
                        f"hold={row['hold_return_pct']:+.1f}% "
                        f"trades={row['num_trades']} "
                        f"win={row['win_rate']:.0f}% "
                        f"DD={row['max_drawdown_pct']:.1f}%"
                    )
                except Exception as e:
                    print(f"ERR {e}")
    return rows


def summarize(rows: list[dict]) -> dict:
    """Aggregate by strategy × timeframe."""
    from collections import defaultdict

    buckets: dict[tuple, list] = defaultdict(list)
    for r in rows:
        if r["num_trades"] < 3:
            continue
        buckets[(r["strategy"], r["interval"])].append(r)

    summary = {}
    for (strat, tf), items in sorted(buckets.items()):
        n = len(items)
        avg_ret = sum(x["total_return_pct"] for x in items) / n
        avg_hold = sum(x["hold_return_pct"] for x in items) / n
        avg_alpha = sum(x["alpha_pct"] for x in items) / n
        avg_win = sum(x["win_rate"] for x in items) / n
        avg_dd = sum(x["max_drawdown_pct"] for x in items) / n
        avg_sharpe = sum(x["sharpe_ratio"] for x in items) / n
        beat_hold = sum(1 for x in items if x["total_return_pct"] > x["hold_return_pct"])
        summary[f"{strat}|{tf}"] = {
            "n_symbols": n,
            "avg_return_pct": round(avg_ret, 2),
            "avg_hold_pct": round(avg_hold, 2),
            "avg_alpha_pct": round(avg_alpha, 2),
            "avg_win_rate": round(avg_win, 1),
            "avg_max_dd_pct": round(avg_dd, 1),
            "avg_sharpe": round(avg_sharpe, 2),
            "beat_hold_pct": round(100.0 * beat_hold / n, 1),
        }
    return summary


def pick_stable(summary: dict) -> list[dict]:
    """
    Rank strategy×TF by stability score:
      alpha > 0, decent win rate, not extreme DD, enough symbols.
    """
    ranked = []
    for key, s in summary.items():
        strat, tf = key.split("|")
        # Prefer positive alpha, higher win rate, lower DD, higher beat-hold
        score = (
            s["avg_alpha_pct"] * 0.4
            + (s["avg_win_rate"] - 45) * 0.3
            + (50 - s["avg_max_dd_pct"]) * 0.2
            + (s["beat_hold_pct"] - 50) * 0.1
        )
        ranked.append({"strategy": strat, "interval": tf, "score": round(score, 2), **s})
    ranked.sort(key=lambda x: x["score"], reverse=True)
    return ranked


def main():
    parser = argparse.ArgumentParser(description="MTF MACD+RSI vs Ichimoku for VN stocks")
    parser.add_argument("--symbols", type=str, default=",".join(DEFAULT_SYMBOLS))
    parser.add_argument("--no-fetch", action="store_true", help="Use local CSV only")
    parser.add_argument("--delay", type=float, default=4.0)
    parser.add_argument("--start", type=str, default=None)
    parser.add_argument("--end", type=str, default=None)
    args = parser.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    out_dir = DATA_DIR / "screening"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"=== MTF MACD+RSI / Ichimoku — {datetime.now():%Y-%m-%d %H:%M} ===\n")
    coverage = ensure_data(symbols, delay=args.delay, fetch=not args.no_fetch)

    print("\n=== Backtest ===")
    rows = run_compare(symbols, args.start, args.end)
    summary = summarize(rows)
    ranking = pick_stable(summary)
    rates = rates_snapshot()

    csv_path = out_dir / "mtf_macd_ichimoku_backtest.csv"
    if rows:
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)

    report = {
        "generated_at": datetime.now().isoformat(),
        "symbols": symbols,
        "coverage": coverage,
        "summary_by_strategy_tf": summary,
        "ranking": ranking,
        "vn_policy_rates": rates,
        "csv": str(csv_path),
        "note": (
            "Long-only ATR exit (SL 1.5×ATR, TP 2.5×ATR). "
            "4H resampled from 1H. Not investment advice."
        ),
    }
    json_path = out_dir / "mtf_macd_ichimoku_report.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print("\n=== Ranking (strategy × TF) ===")
    for i, r in enumerate(ranking[:8], 1):
        print(
            f"{i}. {r['strategy']:10s} {r['interval']:3s}  "
            f"score={r['score']:+.1f}  alpha={r['avg_alpha_pct']:+.1f}%  "
            f"win={r['avg_win_rate']:.0f}%  DD={r['avg_max_dd_pct']:.1f}%  "
            f"beat_hold={r['beat_hold_pct']:.0f}%  n={r['n_symbols']}"
        )

    print("\n=== Lãi suất NHNN (snapshot) ===")
    for k, v in rates.items():
        print(f"  {k}: {v}")

    print(f"\nReport: {json_path}")
    print(f"CSV:    {csv_path}")


if __name__ == "__main__":
    main()
