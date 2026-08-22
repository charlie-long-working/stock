#!/usr/bin/env python3
"""
Mix MACD+RSI / Ichimoku / Confluence across uptrend · sideways · downtrend.

Regime (per bar, EMA20/50):
  uptrend   – EMA20 > EMA50 AND close > EMA50
  downtrend – EMA20 < EMA50 AND close < EMA50
  sideways  – otherwise

Mixes:
  macd_rsi      – entry MACD hist↑ + RSI<70
  ichimoku      – TK cross↑ above bull cloud
  confluence    – MACD+RSI AND above bull cloud
  mix_A         – uptrend→macd_rsi | sideways→confluence | downtrend→no new long
  mix_B         – uptrend→ichimoku | sideways→macd_rsi | downtrend→no new long
  mix_C         – uptrend→confluence | sideways→ichimoku | downtrend→cash

Also reports per-regime columns: only entries that fire while bar is in that regime
(for macd_rsi / ichimoku / confluence standalone).

Output CAGR (%/năm) = (1+total_return)^(365/days)−1 over trade span.

Usage:
  .venv/bin/python -m vn_stock.scripts.run_regime_strategy_mix
  .venv/bin/python -m vn_stock.scripts.run_regime_strategy_mix --symbols VCB,FPT --no-fetch
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from vn_stock import DATA_DIR
from vn_stock.backtest.engine import Trade, _exit_position
from vn_stock.data_loaders.vn_ohlcv import load_ohlcv_arrays
from vn_stock.strategies.ichimoku import IchimokuParams, precompute_ichimoku
from vn_stock.strategies.macd_rsi import MACDRSIParams, precompute_macd_rsi

SYMBOLS_DEFAULT = [
    "VCB", "BID", "TCB", "FPT", "HPG", "MWG", "MSN", "GAS", "VHM", "VNM",
]
REGIMES = ("uptrend", "sideways", "downtrend")
MIXES = ("macd_rsi", "ichimoku", "confluence", "mix_A", "mix_B", "mix_C")


def _ema(close: np.ndarray, period: int) -> np.ndarray:
    out = np.empty_like(close, dtype=np.float64)
    out[0] = close[0]
    a = 2.0 / (period + 1)
    for i in range(1, len(close)):
        out[i] = a * close[i] + (1 - a) * out[i - 1]
    return out


def label_regimes(close: np.ndarray, fast: int = 20, slow: int = 50) -> np.ndarray:
    """Return array of regime strings per bar."""
    ema_f = _ema(close, fast)
    ema_s = _ema(close, slow)
    n = len(close)
    labels = np.array(["sideways"] * n, dtype=object)
    for i in range(slow, n):
        if ema_f[i] > ema_s[i] and close[i] > ema_s[i]:
            labels[i] = "uptrend"
        elif ema_f[i] < ema_s[i] and close[i] < ema_s[i]:
            labels[i] = "downtrend"
        else:
            labels[i] = "sideways"
    return labels


def _cagr(total_return_frac: float, days: float) -> Optional[float]:
    if days is None or days < 30 or total_return_frac <= -1:
        return None
    years = days / 365.25
    if years <= 0:
        return None
    return (float(1.0 + total_return_frac) ** (1.0 / years) - 1.0) * 100.0


def _ts_to_days(ot: np.ndarray, i0: int, i1: int) -> float:
    t0, t1 = float(ot[i0]), float(ot[i1])
    # seconds vs ms
    if t0 < 1e12:
        return max((t1 - t0) / 86400.0, 1.0)
    return max((t1 - t0) / 86400_000.0, 1.0)


@dataclass
class RunStats:
    symbol: str
    strategy: str
    regime_filter: str  # "all" or uptrend|sideways|downtrend
    num_trades: int
    total_return_pct: float
    win_rate: float
    max_drawdown_pct: float
    cagr_pct: Optional[float]
    span_days: float
    regime_bar_pct: float  # share of bars in this regime (if filtered)


def simulate(
    symbol: str,
    open_time: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    strategy: str,
    regime_filter: str = "all",
) -> Optional[RunStats]:
    """
    Walk-forward long-only with ATR exits.
    regime_filter: if not 'all', only allow NEW entries when bar regime matches.
    For mix_*: entry rule switches by bar regime (still optional filter='all').
    """
    n = len(close)
    mp = MACDRSIParams()
    ip = IchimokuParams()
    lookback = max(mp.slow_period + mp.signal_period + 2, ip.senkou_b_period + ip.displacement + 2, 55)
    if n < lookback + 10:
        return None

    hist, rsi, atr = precompute_macd_rsi(high, low, close, mp)
    tenkan, kijun, sa, sb, _ = precompute_ichimoku(high, low, close, ip)
    regimes = label_regimes(close)

    if regime_filter != "all":
        regime_bar_pct = float(np.mean(regimes[lookback:] == regime_filter) * 100)
    else:
        regime_bar_pct = 100.0

    trades: List[Trade] = []
    equity = 1.0
    curve = np.ones(n)
    position = None
    first_entry = None
    last_exit = None

    def macd_long(i: int) -> bool:
        return hist[i - 1] <= 0 < hist[i] and rsi[i] < mp.rsi_overbought

    def ichi_long(i: int) -> bool:
        t0, t1 = tenkan[i - 1], tenkan[i]
        k0, k1 = kijun[i - 1], kijun[i]
        a, b = sa[i], sb[i]
        if any(np.isnan(x) for x in (t0, t1, k0, k1, a, b)):
            return False
        return t0 <= k0 and t1 > k1 and close[i] > max(a, b) and a >= b

    def confluence_long(i: int) -> bool:
        a, b = sa[i], sb[i]
        if np.isnan(a) or np.isnan(b):
            return False
        return macd_long(i) and close[i] > max(a, b) and a >= b

    def want_entry(i: int) -> bool:
        reg = regimes[i]
        if strategy == "macd_rsi":
            sig = macd_long(i)
        elif strategy == "ichimoku":
            sig = ichi_long(i)
        elif strategy == "confluence":
            sig = confluence_long(i)
        elif strategy == "mix_A":
            # up→macd, side→confluence, down→flat
            if reg == "uptrend":
                sig = macd_long(i)
            elif reg == "sideways":
                sig = confluence_long(i)
            else:
                sig = False
        elif strategy == "mix_B":
            if reg == "uptrend":
                sig = ichi_long(i)
            elif reg == "sideways":
                sig = macd_long(i)
            else:
                sig = False
        elif strategy == "mix_C":
            if reg == "uptrend":
                sig = confluence_long(i)
            elif reg == "sideways":
                sig = ichi_long(i)
            else:
                sig = False
        else:
            raise ValueError(strategy)

        if not sig:
            return False
        if regime_filter != "all" and regimes[i] != regime_filter:
            return False
        return True

    for i in range(lookback, n):
        if position is not None:
            exit_price, exit_reason = _exit_position(position, i, high[i], low[i], close[i])
            # mix: optional early exit on downtrend flip for open long
            if exit_price is None and strategy.startswith("mix_") and regimes[i] == "downtrend":
                exit_price, exit_reason = close[i], "regime_down"
            if exit_price is not None:
                pnl = (exit_price - position["entry_price"]) / position["entry_price"] * 100
                trades.append(Trade(
                    entry_bar=position["entry_bar"], exit_bar=i,
                    entry_price=position["entry_price"], exit_price=exit_price,
                    pnl_pct=pnl, exit_reason=exit_reason,
                    stop_loss=position["stop"], take_profit=position["target"],
                ))
                equity *= 1 + pnl / 100
                last_exit = i
                position = None

        if position is None and i >= 1 and want_entry(i):
            cur_atr = atr[i]
            position = {
                "entry_price": close[i],
                "entry_bar": i,
                "stop": close[i] - mp.atr_sl_mult * cur_atr,
                "target": close[i] + mp.atr_tp_mult * cur_atr,
            }
            if first_entry is None:
                first_entry = i

        curve[i] = equity

    if position is not None:
        pnl = (close[n - 1] - position["entry_price"]) / position["entry_price"] * 100
        trades.append(Trade(
            entry_bar=position["entry_bar"], exit_bar=n - 1,
            entry_price=position["entry_price"], exit_price=close[n - 1],
            pnl_pct=pnl, exit_reason="end",
            stop_loss=position.get("stop"), take_profit=position.get("target"),
        ))
        equity *= 1 + pnl / 100
        last_exit = n - 1
        curve[n - 1] = equity

    total_return_pct = (equity - 1.0) * 100
    wins = [t for t in trades if t.pnl_pct > 0]
    win_rate = len(wins) / len(trades) * 100 if trades else 0.0

    peak = np.maximum.accumulate(curve[lookback:])
    dd = (peak - curve[lookback:]) / np.where(peak > 0, peak, 1)
    max_dd = float(np.max(dd) * 100) if len(dd) else 0.0

    if first_entry is not None and last_exit is not None and last_exit > first_entry:
        span = _ts_to_days(open_time, first_entry, last_exit)
    else:
        span = _ts_to_days(open_time, lookback, n - 1)
    cagr = _cagr(equity - 1.0, span) if trades else None

    return RunStats(
        symbol=symbol,
        strategy=strategy,
        regime_filter=regime_filter,
        num_trades=len(trades),
        total_return_pct=round(total_return_pct, 2),
        win_rate=round(win_rate, 1),
        max_drawdown_pct=round(max_dd, 1),
        cagr_pct=round(cagr, 2) if cagr is not None else None,
        span_days=round(span, 1),
        regime_bar_pct=round(regime_bar_pct, 1),
    )


def aggregate(rows: List[RunStats]) -> Dict[str, dict]:
    """Mean across symbols for each (strategy, regime_filter)."""
    buckets: Dict[Tuple[str, str], List[RunStats]] = defaultdict(list)
    for r in rows:
        buckets[(r.strategy, r.regime_filter)].append(r)

    out = {}
    for (strat, reg), items in sorted(buckets.items()):
        with_trades = [x for x in items if x.num_trades >= 1]
        cagrs = [x.cagr_pct for x in with_trades if x.cagr_pct is not None]
        rets = [x.total_return_pct for x in with_trades]
        wins = [x.win_rate for x in with_trades]
        dds = [x.max_drawdown_pct for x in with_trades]
        key = f"{strat}|{reg}"
        out[key] = {
            "strategy": strat,
            "regime": reg,
            "n_symbols": len(with_trades),
            "avg_total_return_pct": round(float(np.mean(rets)), 2) if rets else None,
            "avg_cagr_pct": round(float(np.mean(cagrs)), 2) if cagrs else None,
            "median_cagr_pct": round(float(np.median(cagrs)), 2) if cagrs else None,
            "avg_win_rate": round(float(np.mean(wins)), 1) if wins else None,
            "avg_max_dd_pct": round(float(np.mean(dds)), 1) if dds else None,
            "avg_trades": round(float(np.mean([x.num_trades for x in with_trades])), 1) if with_trades else 0,
            "pos_rate_pct": round(100.0 * sum(1 for x in with_trades if x.total_return_pct > 0) / len(with_trades), 1) if with_trades else 0,
        }
    return out


def build_cagr_matrix(agg: Dict[str, dict], strategies: List[str], regimes: List[str]) -> List[dict]:
    """Rows=regime, columns=strategy → avg CAGR."""
    matrix = []
    for reg in regimes:
        row = {"regime": reg}
        for st in strategies:
            cell = agg.get(f"{st}|{reg}")
            row[st] = cell["avg_cagr_pct"] if cell else None
            row[f"{st}_n"] = cell["n_symbols"] if cell else 0
            row[f"{st}_ret"] = cell["avg_total_return_pct"] if cell else None
        matrix.append(row)
    # all-regime row for mixes
    row_all = {"regime": "all"}
    for st in strategies:
        cell = agg.get(f"{st}|all")
        row_all[st] = cell["avg_cagr_pct"] if cell else None
        row_all[f"{st}_n"] = cell["n_symbols"] if cell else 0
        row_all[f"{st}_ret"] = cell["avg_total_return_pct"] if cell else None
    matrix.append(row_all)
    return matrix


def regime_share(symbols: List[str]) -> dict:
    shares = {r: [] for r in REGIMES}
    for sym in symbols:
        data = load_ohlcv_arrays(sym, "1D")
        if not data:
            continue
        _, _, _, _, c, _ = data
        labels = label_regimes(c)[55:]
        for r in REGIMES:
            shares[r].append(float(np.mean(labels == r) * 100))
    return {r: round(float(np.mean(v)), 1) if v else 0 for r, v in shares.items()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", type=str, default=",".join(SYMBOLS_DEFAULT))
    parser.add_argument("--interval", type=str, default="1D")
    args = parser.parse_args()
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]

    print(f"=== Regime × Strategy mix — {datetime.now():%Y-%m-%d %H:%M} ===\n")
    share = regime_share(symbols)
    print(f"Avg bar share: uptrend {share['uptrend']}% | sideways {share['sideways']}% | downtrend {share['downtrend']}%\n")

    rows: List[RunStats] = []
    # 1) Standalone strategies sliced by entry-regime
    for strat in ("macd_rsi", "ichimoku", "confluence"):
        for reg in ("all",) + REGIMES:
            for sym in symbols:
                data = load_ohlcv_arrays(sym, args.interval)
                if not data:
                    continue
                ot, o, h, l, c, v = data
                r = simulate(sym, ot, h, l, c, strat, regime_filter=reg)
                if r:
                    rows.append(r)
                    if r.num_trades >= 1:
                        cagr_s = f"{r.cagr_pct:+.1f}%/y" if r.cagr_pct is not None else "n/a"
                        print(f"{sym:4} {strat:12} entry@{reg:9} ret={r.total_return_pct:+7.1f}%  CAGR={cagr_s:>10}  n={r.num_trades:3}  win={r.win_rate:4.0f}%")

    # 2) Adaptive mixes (always filter=all; regime routes inside)
    for strat in ("mix_A", "mix_B", "mix_C"):
        for sym in symbols:
            data = load_ohlcv_arrays(sym, args.interval)
            if not data:
                continue
            ot, o, h, l, c, v = data
            r = simulate(sym, ot, h, l, c, strat, regime_filter="all")
            if r:
                rows.append(r)
                cagr_s = f"{r.cagr_pct:+.1f}%/y" if r.cagr_pct is not None else "n/a"
                print(f"{sym:4} {strat:12} entry@all       ret={r.total_return_pct:+7.1f}%  CAGR={cagr_s:>10}  n={r.num_trades:3}  win={r.win_rate:4.0f}%")

    agg = aggregate(rows)
    matrix = build_cagr_matrix(
        agg,
        strategies=["macd_rsi", "ichimoku", "confluence", "mix_A", "mix_B", "mix_C"],
        regimes=list(REGIMES),
    )

    # Pick best mix by avg CAGR on all
    mix_rank = []
    for m in ("mix_A", "mix_B", "mix_C", "macd_rsi", "ichimoku", "confluence"):
        cell = agg.get(f"{m}|all")
        if cell and cell["avg_cagr_pct"] is not None:
            mix_rank.append({**cell})
    mix_rank.sort(key=lambda x: x["avg_cagr_pct"], reverse=True)

    out_dir = DATA_DIR / "screening"
    out_dir.mkdir(parents=True, exist_ok=True)

    detail_path = out_dir / "regime_strategy_mix_detail.csv"
    with open(detail_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "symbol", "strategy", "regime_filter", "num_trades",
            "total_return_pct", "cagr_pct", "win_rate", "max_drawdown_pct",
            "span_days", "regime_bar_pct",
        ])
        for r in rows:
            w.writerow([
                r.symbol, r.strategy, r.regime_filter, r.num_trades,
                r.total_return_pct, r.cagr_pct if r.cagr_pct is not None else "",
                r.win_rate, r.max_drawdown_pct, r.span_days, r.regime_bar_pct,
            ])

    # CAGR matrix CSV (rows=regime, cols=strategy)
    matrix_path = out_dir / "regime_strategy_mix_cagr_matrix.csv"
    cols = ["regime", "macd_rsi", "ichimoku", "confluence", "mix_A", "mix_B", "mix_C"]
    with open(matrix_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for row in matrix:
            w.writerow({k: row.get(k) for k in cols})

    report = {
        "generated_at": datetime.now().isoformat(),
        "interval": args.interval,
        "symbols": symbols,
        "regime_definition": "EMA20/EMA50 + close vs EMA50",
        "regime_bar_share_pct": share,
        "mix_rules": {
            "mix_A": "uptrend→macd_rsi | sideways→confluence | downtrend→no entry (+exit if open)",
            "mix_B": "uptrend→ichimoku | sideways→macd_rsi | downtrend→flat",
            "mix_C": "uptrend→confluence | sideways→ichimoku | downtrend→flat",
        },
        "cagr_note": "CAGR %/năm = (1+total_return)^(365.25/span_days)−1; avg across symbols with ≥1 trade",
        "aggregate": agg,
        "cagr_matrix_avg_pct_per_year": matrix,
        "ranking_all_regime": mix_rank,
        "files": {"detail": str(detail_path), "matrix": str(matrix_path)},
    }
    json_path = out_dir / "regime_strategy_mix_report.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== Ma trận CAGR trung bình (%/năm) — cột = strategy, hàng = regime entry ===")
    header = f"{'regime':10}" + "".join(f"{s:>12}" for s in cols[1:])
    print(header)
    for row in matrix:
        line = f"{row['regime']:10}"
        for s in cols[1:]:
            v = row.get(s)
            line += f"{v:>11.1f}%" if v is not None else f"{'—':>12}"
        print(line)

    print("\n=== Ranking (all regimes) by avg CAGR ===")
    for i, r in enumerate(mix_rank, 1):
        print(
            f"{i}. {r['strategy']:12}  CAGR={r['avg_cagr_pct']:+.1f}%/y  "
            f"ret={r['avg_total_return_pct']:+.1f}%  win={r['avg_win_rate']:.0f}%  "
            f"DD={r['avg_max_dd_pct']:.1f}%  pos={r['pos_rate_pct']:.0f}%"
        )

    print(f"\nJSON: {json_path}")
    print(f"Matrix CSV: {matrix_path}")
    print(f"Detail CSV: {detail_path}")


if __name__ == "__main__":
    main()
