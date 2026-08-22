#!/usr/bin/env python3
"""
Thu thập & phân tích cổ phiếu ngành Bất động sản — dữ liệu trong folder riêng.

Cấu trúc:
  vn_stock/data/sectors/bat_dong_san/
    symbols.json              # danh sách mã + mô tả
    ohlcv/{SYMBOL}/1H.csv, 1D.csv, 1W.csv
    fundamentals/{SYMBOL}/    # BCTC CSV (năm + quý)
    analysis/
      fundamental_scores.json
      backtest_1D.csv
      technical_signals.json
      combined_buy_candidates.json
      report_YYYY-MM-DD.md

Usage:
  cd stock && PYTHONPATH=. python -m vn_stock.scripts.crawl_bat_dong_san
  python -m vn_stock.scripts.crawl_bat_dong_san --ohlcv-only
  python -m vn_stock.scripts.crawl_bat_dong_san --analyze-only   # chỉ chạy phân tích trên data đã có
  python -m vn_stock.scripts.crawl_bat_dong_san --symbols VIC,VHM --no-fundamentals
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from vn_stock.analysis.combined_signal import get_combined_signals
from vn_stock.analysis.fundamental_trend import (
    FundamentalScore,
    analyze_fundamentals,
    batch_analyze,
    format_score_report,
)
from vn_stock.backtest.engine import run_backtest
from vn_stock.data_loaders.vn_fundamentals import batch_fetch_fundamentals
from vn_stock.data_loaders.vn_ohlcv import DATA_START, batch_fetch_ohlcv
from vn_stock.sectors.bat_dong_san import BAT_DONG_SAN_SYMBOLS, bat_dong_san_data_root
from vn_stock.signals.vn_signal import scan_symbol


def _json_safe_metrics(d: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in d.items():
        if v is None:
            out[k] = None
        elif isinstance(v, (str, bool, int)):
            out[k] = v
        elif isinstance(v, float):
            out[k] = v
        else:
            try:
                out[k] = float(v)
            except (TypeError, ValueError):
                out[k] = str(v)
    return out


def _score_to_dict(s: FundamentalScore) -> Dict[str, Any]:
    return {
        "symbol": s.symbol,
        "overall_score": s.overall_score,
        "trend": s.trend,
        "profitability_score": s.profitability_score,
        "growth_score": s.growth_score,
        "health_score": s.health_score,
        "cashflow_score": s.cashflow_score,
        "valuation_score": s.valuation_score,
        "metrics": _json_safe_metrics(dict(s.metrics)),
        "flags": s.flags,
    }


def _combined_to_dict(c) -> Dict[str, Any]:
    return {
        "symbol": c.symbol,
        "interval": c.interval,
        "combined_score": c.combined_score,
        "fundamental_trend": c.fundamental_trend,
        "fundamental_score": c.fundamental_score,
        "entry_price": c.entry_price,
        "stop_loss": c.stop_loss,
        "take_profit": c.take_profit,
        "best_strategy": c.best_strategy,
        "technical": [f"{t.strategy}:{t.reason}" for t in c.technical_signals],
        "flags": c.flags,
    }


def ensure_layout(root: Path) -> Path:
    analysis = root / "analysis"
    analysis.mkdir(parents=True, exist_ok=True)
    return analysis


def write_symbols_manifest(root: Path, symbols: List[str]) -> None:
    meta = {
        "sector": "bat_dong_san",
        "sector_name_vi": "Bất động sản",
        "updated_at": datetime.now().isoformat(),
        "symbols": symbols,
        "count": len(symbols),
    }
    path = root / "symbols.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print(f"Wrote {path}")


def run_fundamental_analysis(root: Path, symbols: List[str]) -> List[FundamentalScore]:
    scores = batch_analyze(symbols, data_root=root)
    out = root / "analysis" / "fundamental_scores.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump([_score_to_dict(s) for s in scores], f, ensure_ascii=False, indent=2)
    print(f"Wrote {out}")
    return scores


def run_backtests(root: Path, symbols: List[str], interval: str = "1D") -> List[Dict[str, Any]]:
    strategies = ["macd_rsi", "ma_crossover", "regime_fusion"]
    rows: List[Dict[str, Any]] = []
    for sym in symbols:
        for strat in strategies:
            r = run_backtest(sym, strategy=strat, interval=interval, data_root=root)
            if r is None:
                continue
            rows.append({
                "symbol": sym,
                "strategy": strat,
                "interval": interval,
                "num_trades": r.num_trades,
                "total_return_pct": round(r.total_return_pct, 2),
                "hold_return_pct": round(r.hold_return_pct, 2),
                "win_rate": round(r.win_rate, 2),
                "profit_factor": round(r.profit_factor, 2),
                "sharpe_ratio": round(r.sharpe_ratio, 2),
                "max_drawdown_pct": round(r.max_drawdown_pct, 2),
            })
    out_csv = root / "analysis" / f"backtest_{interval}.csv"
    if rows:
        with open(out_csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        print(f"Wrote {out_csv}")
    return rows


def run_technical_scan(root: Path, symbols: List[str], interval: str = "1D") -> List[Dict[str, Any]]:
    out_list: List[Dict[str, Any]] = []
    strategies = ["macd_rsi", "ma_crossover", "regime_fusion"]
    for sym in symbols:
        sigs = scan_symbol(sym, interval, strategies, update_data=False, data_root=root)
        for s in sigs:
            out_list.append({
                "symbol": s.symbol,
                "interval": s.interval,
                "strategy": s.strategy,
                "entry_price": s.entry_price,
                "stop_loss": s.stop_loss,
                "take_profit": s.take_profit,
                "reason": s.reason,
                "regime": s.regime,
            })
    path = root / "analysis" / "technical_signals.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            {"generated_at": datetime.now().isoformat(), "signals": out_list},
            f,
            ensure_ascii=False,
            indent=2,
        )
    print(f"Wrote {path} ({len(out_list)} signals)")
    return out_list


def run_combined(root: Path, symbols: List[str], interval: str = "1D") -> None:
    combined = get_combined_signals(
        symbols,
        intervals=[interval],
        update_data=False,
        data_root=root,
    )
    path = root / "analysis" / "combined_buy_candidates.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "generated_at": datetime.now().isoformat(),
                "candidates": [_combined_to_dict(c) for c in combined],
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    print(f"Wrote {path} ({len(combined)} candidates)")


def write_markdown_report(root: Path, scores: List[FundamentalScore]) -> None:
    day = datetime.now().strftime("%Y-%m-%d")
    path = root / "analysis" / f"report_{day}.md"
    lines = [
        f"# Báo cáo ngành Bất động sản — {day}",
        "",
        f"- Số mã: {len(scores)}",
        f"- Thư mục dữ liệu: `{root}`",
        "",
        "## Xu hướng cơ bản (theo điểm số)",
        "",
    ]
    for s in sorted(scores, key=lambda x: x.overall_score, reverse=True):
        lines.append(format_score_report(s))
        lines.append("")
    lines.append("## File kèm theo")
    lines.append("- `fundamental_scores.json`")
    lines.append("- `backtest_1D.csv`")
    lines.append("- `technical_signals.json`")
    lines.append("- `combined_buy_candidates.json`")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"Wrote {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Crawl & analyze VN real estate sector")
    parser.add_argument("--symbols", type=str, default=None, help="Comma-separated override")
    parser.add_argument("--ohlcv-only", action="store_true")
    parser.add_argument("--analyze-only", action="store_true", help="Skip API crawl")
    parser.add_argument("--no-fundamentals", action="store_true")
    parser.add_argument("--no-h1", action="store_true", help="Skip 1H OHLCV (nhiều API hơn)")
    parser.add_argument("--delay", type=float, default=4.0, help="Delay giữa các request OHLCV")
    parser.add_argument("--fund-delay", type=float, default=4.0, help="Delay fundamentals")
    args = parser.parse_args()

    root = bat_dong_san_data_root()
    ensure_layout(root)

    symbols = [s.strip().upper() for s in args.symbols.split(",")] if args.symbols else list(BAT_DONG_SAN_SYMBOLS)
    write_symbols_manifest(root, symbols)

    if not args.analyze_only:
        intervals = ["1D", "1W"]
        if not args.no_h1:
            intervals.append("1H")
        print(f"=== Fetch OHLCV ({len(symbols)} mã, {intervals}) → {root / 'ohlcv'} ===")
        batch_fetch_ohlcv(symbols, intervals=intervals, start=DATA_START, delay=args.delay, data_root=root)

        if not args.no_fundamentals and not args.ohlcv_only:
            print(f"=== Fetch fundamentals (annual) → {root / 'fundamentals'} ===")
            batch_fetch_fundamentals(symbols, period="annual", delay=args.fund_delay, data_root=root)
            print(f"=== Fetch fundamentals (quarter) → {root / 'fundamentals'} ===")
            batch_fetch_fundamentals(symbols, period="quarter", delay=args.fund_delay, data_root=root)

    if args.ohlcv_only:
        print("Done (--ohlcv-only).")
        return

    print("=== Phân tích ===")
    scores = run_fundamental_analysis(root, symbols)
    run_backtests(root, symbols, "1D")
    run_technical_scan(root, symbols, "1D")
    run_combined(root, symbols, "1D")
    write_markdown_report(root, scores)

    readme = root / "README.md"
    if not readme.exists():
        readme.write_text(
            """# Dữ liệu ngành Bất động sản

Thư mục này tách biệt với `data/ohlcv` và `data/fundamentals` mặc định.

- `ohlcv/` — nến 1H, 1D, 1W theo từng mã
- `fundamentals/` — BCTC năm (`*.csv`) và quý (`*_quarter.csv`)
- `analysis/` — kết quả phân tích (JSON, CSV, Markdown)

Chạy cập nhật:

```bash
cd stock
PYTHONPATH=. python -m vn_stock.scripts.crawl_bat_dong_san
```
""",
            encoding="utf-8",
        )
        print(f"Wrote {readme}")

    print("\nHoàn tất. Xem kết quả trong:", root / "analysis")


if __name__ == "__main__":
    main()
