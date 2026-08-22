#!/usr/bin/env python3
"""
Apply crypto botdown engines to VN stocks — import only, no edits under Trading-bot/.

Strategies (crypto defaults: TP 10% / SL 4% / fee 0.1%, long-only):
  - macd_rsi
  - macd_rsi + EMA trend filter
  - smc (order block / FVG / S&D)
  - smc + EMA trend filter

Usage:
  cd stock
  export PYTHONPATH="$PWD:$PWD/../Trading-bot"
  .venv/bin/python -m vn_stock.scripts.run_crypto_engines_on_vn
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import numpy as np
import pandas as pd

from botdown.engine_macd_rsi_bt import MacdRsiParams, run_macd_rsi_backtest
from botdown.engine_smc_bt import SmcParams, run_smc_backtest
from vn_stock import DATA_DIR
from vn_stock.data_loaders.vn_ohlcv import load_ohlcv_arrays

SYMBOLS_DEFAULT = [
    "VCB", "BID", "TCB", "FPT", "HPG", "MWG", "MSN", "GAS", "VHM", "VNM",
]
DEPOSIT_BENCH_PCT = 4.75  # trần TG 1–<6m NHNN


def _bar_dates(ot: np.ndarray) -> tuple[str, str]:
    unit = "ms" if ot[0] > 1e12 else "s"
    start = str(pd.to_datetime(int(ot[0]), unit=unit).date())
    end = str(pd.to_datetime(int(ot[-1]), unit=unit).date())
    return start, end


def _span_days(ot: np.ndarray) -> float:
    t0, t1 = float(ot[0]), float(ot[-1])
    if t0 < 1e12:
        return max((t1 - t0) / 86400.0, 1.0)
    return max((t1 - t0) / 86_400_000.0, 1.0)


def _cagr(total_return_frac: float, days: float) -> Optional[float]:
    if days < 30 or total_return_frac <= -1:
        return None
    years = days / 365.25
    return (float(1.0 + total_return_frac) ** (1.0 / years) - 1.0) * 100.0


def run_one(symbol: str, label: str, runner) -> Optional[dict]:
    data = load_ohlcv_arrays(symbol, "1D")
    if data is None:
        return None
    ot, o, h, l, c, v = data
    start, end = _bar_dates(ot)
    days = _span_days(ot)
    r = runner(ot, o, h, l, c, start, end)
    if r is None:
        return None
    ret = float(r.total_return_pct)
    cagr = _cagr(ret / 100.0, days)
    ann_simple = ret / (days / 365.25)
    hold = float(getattr(r, "buy_hold_pct", 0.0))
    return {
        "symbol": symbol,
        "strategy": label,
        "total_return_pct": round(ret, 2),
        "buy_hold_pct": round(hold, 2),
        "cagr_pct": round(cagr, 2) if cagr is not None else None,
        "ann_simple_pct": round(ann_simple, 2),
        "num_trades": int(r.num_trades),
        "win_rate": round(float(r.win_rate), 1),
        "max_drawdown_pct": round(float(r.max_drawdown_pct), 1),
        "span_days": round(days, 1),
        "start": start,
        "end": end,
        "beats_deposit_4_75": bool(cagr is not None and cagr > DEPOSIT_BENCH_PCT),
    }


def main():
    parser = argparse.ArgumentParser(description="Crypto engines on VN stocks (no crypto code edits)")
    parser.add_argument("--symbols", type=str, default=",".join(SYMBOLS_DEFAULT))
    args = parser.parse_args()
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]

    configs = [
        (
            "macd_rsi_pct",
            lambda ot, o, h, l, c, s, e: run_macd_rsi_backtest(
                ot, h, l, c, s, e,
                params=MacdRsiParams(exit_mode="pct", take_profit_pct=0.10, stop_loss_pct=0.04),
                allow_short=False,
            ),
        ),
        (
            "macd_rsi_pct_ema",
            lambda ot, o, h, l, c, s, e: run_macd_rsi_backtest(
                ot, h, l, c, s, e,
                params=MacdRsiParams(
                    exit_mode="pct", take_profit_pct=0.10, stop_loss_pct=0.04,
                    use_ema_trend_filter=True,
                ),
                allow_short=False,
            ),
        ),
        (
            "smc_pct",
            lambda ot, o, h, l, c, s, e: run_smc_backtest(
                ot, o, h, l, c, s, e,
                params=SmcParams(take_profit_pct=0.10, stop_loss_pct=0.04),
                allow_short=False,
            ),
        ),
        (
            "smc_pct_ema",
            lambda ot, o, h, l, c, s, e: run_smc_backtest(
                ot, o, h, l, c, s, e,
                params=SmcParams(
                    take_profit_pct=0.10, stop_loss_pct=0.04, use_ema_trend_filter=True,
                ),
                allow_short=False,
            ),
        ),
    ]

    print(f"=== Crypto engines → VN 1D (long-only TP10/SL4) — {datetime.now():%Y-%m-%d %H:%M} ===")
    print(f"Benchmark tiết kiệm: {DEPOSIT_BENCH_PCT}%/năm (trần TG 1–<6m)\n")
    print("(Không sửa code Trading-bot/botdown — chỉ import)\n")

    rows: List[dict] = []
    for label, runner in configs:
        for sym in symbols:
            try:
                row = run_one(sym, label, runner)
            except Exception as ex:
                print(f"{sym} {label} ERROR: {ex}")
                continue
            if row is None:
                continue
            rows.append(row)
            beat = "YES" if row["beats_deposit_4_75"] else "no"
            cagr_s = f"{row['cagr_pct']:+.1f}%" if row["cagr_pct"] is not None else "n/a"
            print(
                f"{sym:4} {label:18} ret={row['total_return_pct']:+7.1f}%  "
                f"CAGR={cagr_s:>8}/y  ann={row['ann_simple_pct']:+6.1f}%  "
                f"n={row['num_trades']:3} win={row['win_rate']:4.0f}%  "
                f"DD={row['max_drawdown_pct']:5.1f}%  >deposit? {beat}"
            )

    # Aggregate
    from collections import defaultdict

    buckets = defaultdict(list)
    for r in rows:
        buckets[r["strategy"]].append(r)

    summary = {}
    print("\n=== Trung bình 10 mã — so tiết kiệm 4.75%/năm ===")
    print(f"{'strategy':20} {'CAGR':>8} {'annSim':>8} {'ret':>8} {'win':>6} {'DD':>6} {'%>dep':>6} {'pos%':>6}")
    for label, _ in configs:
        items = buckets.get(label, [])
        if not items:
            continue
        cagrs = [x["cagr_pct"] for x in items if x["cagr_pct"] is not None]
        summary[label] = {
            "n": len(items),
            "avg_cagr_pct": round(float(np.mean(cagrs)), 2) if cagrs else None,
            "avg_ann_simple_pct": round(float(np.mean([x["ann_simple_pct"] for x in items])), 2),
            "avg_total_return_pct": round(float(np.mean([x["total_return_pct"] for x in items])), 2),
            "avg_win_rate": round(float(np.mean([x["win_rate"] for x in items])), 1),
            "avg_max_dd_pct": round(float(np.mean([x["max_drawdown_pct"] for x in items])), 1),
            "avg_trades": round(float(np.mean([x["num_trades"] for x in items])), 1),
            "pct_beat_deposit": round(100.0 * sum(1 for x in items if x["beats_deposit_4_75"]) / len(items), 1),
            "pos_rate_pct": round(100.0 * sum(1 for x in items if x["total_return_pct"] > 0) / len(items), 1),
            "vs_deposit_4_75": (
                "beats"
                if cagrs and float(np.mean(cagrs)) > DEPOSIT_BENCH_PCT
                else "loses"
            ),
        }
        s = summary[label]
        print(
            f"{label:20} {s['avg_cagr_pct']:>+7.2f}% {s['avg_ann_simple_pct']:>+7.2f}% "
            f"{s['avg_total_return_pct']:>+7.1f}% {s['avg_win_rate']:>5.1f}% "
            f"{s['avg_max_dd_pct']:>5.1f}% {s['pct_beat_deposit']:>5.0f}% {s['pos_rate_pct']:>5.0f}%"
        )

    out_dir = DATA_DIR / "screening"
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "crypto_engines_on_vn.csv"
    if rows:
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)

    report = {
        "generated_at": datetime.now().isoformat(),
        "note": "Imported botdown engines only; Trading-bot code untouched. Long-only VN 1D.",
        "params": "TP 10% / SL 4% / fee 0.1% round-trip (crypto defaults)",
        "deposit_benchmark_pct": DEPOSIT_BENCH_PCT,
        "symbols": symbols,
        "summary": summary,
        "csv": str(csv_path),
    }
    json_path = out_dir / "crypto_engines_on_vn_report.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nCSV:  {csv_path}")
    print(f"JSON: {json_path}")


if __name__ == "__main__":
    main()
