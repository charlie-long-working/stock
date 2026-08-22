#!/usr/bin/env python3
"""
Run backtest for VN stocks across multiple strategies and timeframes.

Usage:
  python -m vn_stock.scripts.run_backtest --symbols VCB,BID,TCB --strategies macd_rsi,ma_crossover,regime_fusion --timeframes 1D,1W
  python -m vn_stock.scripts.run_backtest --top100        # Backtest all top 100 symbols
  python -m vn_stock.scripts.run_backtest --sector ngan_hang  # Backtest a specific sector
  # Dữ liệu CSV bundle ngành (ohlcv/{MÃ}/1D.csv):
  python -m vn_stock.scripts.run_backtest --symbols CEO,VIC --strategies div_macd_rsi --timeframes 1D \\
      --data-root vn_stock/data/sectors/bat_dong_san
"""

import argparse
import csv
from datetime import datetime
from pathlib import Path

from vn_stock import DATA_DIR
from vn_stock.backtest.engine import run_backtest, BacktestResult
from vn_stock.data_loaders.vn_screener import (
    get_top100, get_financial_sector_symbols, get_multi_sector_symbols,
    _fallback_multi_sector,
)
from vn_stock.data_loaders.vn_ohlcv import load_ohlcv

ALL_STRATEGIES = ["macd_rsi", "ma_crossover", "regime_fusion", "div_macd_rsi", "ichimoku"]
ALL_TIMEFRAMES = ["1H", "4H", "1D", "1W"]


def run_full_backtest(
    symbols: list,
    strategies: list = None,
    timeframes: list = None,
    start_date: str = None,
    end_date: str = None,
    output_csv: str = None,
    data_root: Path = None,
) -> list:
    """Run backtest for all combinations and return results."""
    if strategies is None:
        strategies = ALL_STRATEGIES
    if timeframes is None:
        timeframes = ["1D", "1W"]

    results = []
    total = len(symbols) * len(strategies) * len(timeframes)
    done = 0

    for symbol in symbols:
        for tf in timeframes:
            df = load_ohlcv(symbol, tf, data_root=data_root)
            min_bars = 250 if any(s == "div_macd_rsi" for s in strategies) else 50
            if df is None or len(df) < min_bars:
                done += len(strategies)
                continue

            for strat in strategies:
                done += 1
                print(f"[{done}/{total}] {symbol} | {strat} | {tf} ... ", end="", flush=True)
                try:
                    r = run_backtest(
                        symbol=symbol,
                        strategy=strat,
                        interval=tf,
                        start_date=start_date,
                        end_date=end_date,
                        data_root=data_root,
                    )
                    if r is not None:
                        results.append(r)
                        print(
                            f"return={r.total_return_pct:+.1f}% "
                            f"hold={r.hold_return_pct:+.1f}% "
                            f"trades={r.num_trades} "
                            f"win={r.win_rate:.1f}% "
                            f"sharpe={r.sharpe_ratio:.2f} "
                            f"DD={r.max_drawdown_pct:.1f}%"
                        )
                    else:
                        print("no data")
                except Exception as e:
                    print(f"ERROR: {e}")

    if output_csv:
        _save_results_csv(results, output_csv)

    return results


def _save_results_csv(results: list, path: str):
    """Save backtest results to CSV."""
    if not results:
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "symbol", "strategy", "interval", "num_trades",
            "total_return_pct", "hold_return_pct", "win_rate",
            "profit_factor", "sharpe_ratio", "max_drawdown_pct",
            "avg_win_pct", "avg_loss_pct",
        ])
        for r in results:
            writer.writerow([
                r.symbol, r.strategy, r.interval, r.num_trades,
                f"{r.total_return_pct:.2f}", f"{r.hold_return_pct:.2f}",
                f"{r.win_rate:.1f}", f"{r.profit_factor:.2f}",
                f"{r.sharpe_ratio:.2f}", f"{r.max_drawdown_pct:.1f}",
                f"{r.avg_win_pct:.2f}", f"{r.avg_loss_pct:.2f}",
            ])
    print(f"\nResults saved to {path}")


def print_summary(results: list):
    """Print summary table to console."""
    if not results:
        print("No results.")
        return

    print("\n" + "=" * 120)
    print(f"{'Symbol':<8} {'Strategy':<15} {'TF':<4} {'Trades':>6} {'Return%':>9} {'Hold%':>8} "
          f"{'Win%':>6} {'PF':>5} {'Sharpe':>7} {'MaxDD%':>7}")
    print("-" * 120)

    for r in sorted(results, key=lambda x: x.total_return_pct, reverse=True):
        print(
            f"{r.symbol:<8} {r.strategy:<15} {r.interval:<4} {r.num_trades:>6} "
            f"{r.total_return_pct:>+8.1f}% {r.hold_return_pct:>+7.1f}% "
            f"{r.win_rate:>5.1f}% {r.profit_factor:>5.2f} {r.sharpe_ratio:>6.2f} "
            f"{r.max_drawdown_pct:>6.1f}%"
        )
    print("=" * 120)

    best = max(results, key=lambda x: x.total_return_pct)
    print(f"\nBest: {best.symbol} | {best.strategy} | {best.interval} → {best.total_return_pct:+.1f}%")


def main():
    parser = argparse.ArgumentParser(description="Backtest VN stocks")
    parser.add_argument("--symbols", type=str, default=None,
                        help="Comma-separated symbols (e.g., VCB,BID,TCB)")
    parser.add_argument("--strategies", type=str, default=",".join(ALL_STRATEGIES),
                        help="Comma-separated strategies")
    parser.add_argument("--timeframes", type=str, default="1D,1W",
                        help="Comma-separated timeframes (1H,1D,1W)")
    parser.add_argument("--start", type=str, default=None,
                        help="Start date YYYY-MM-DD")
    parser.add_argument("--end", type=str, default=None,
                        help="End date YYYY-MM-DD")
    parser.add_argument("--top100", action="store_true",
                        help="Backtest all top 100 symbols")
    parser.add_argument("--sector", type=str, default=None,
                        help="Sector key (ngan_hang, bat_dong_san, etc.)")
    parser.add_argument("--output", type=str, default=None,
                        help="Output CSV path")
    parser.add_argument("--data-root", type=str, default=None,
                        help="Thư mục bundle có ohlcv/ (vd: vn_stock/data/sectors/bat_dong_san). Mặc định: vn_stock/data/ohlcv")
    args = parser.parse_args()

    data_root = Path(args.data_root).resolve() if args.data_root else None

    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",")]
    elif args.top100:
        top = get_top100(save=False)
        col = "symbol" if "symbol" in top.columns else "ticker"
        symbols = top[col].tolist() if col in top.columns else []
        if not symbols:
            sectors = _fallback_multi_sector()
            symbols = list({s for syms in sectors.values() for s in syms})
    elif args.sector:
        sectors = get_multi_sector_symbols()
        symbols = sectors.get(args.sector, [])
        if not symbols:
            fb = _fallback_multi_sector()
            symbols = fb.get(args.sector, [])
    else:
        symbols = ["VCB", "BID", "TCB", "MBB", "FPT", "HPG", "VHM", "GAS", "SSI", "VNM"]

    strategies = [s.strip() for s in args.strategies.split(",")]
    timeframes = [t.strip() for t in args.timeframes.split(",")]

    output = args.output
    if output is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output = str(DATA_DIR / f"backtest_results_{ts}.csv")

    print(f"Symbols: {len(symbols)} | Strategies: {strategies} | Timeframes: {timeframes}")
    print(f"Date range: {args.start or 'all'} → {args.end or 'latest'}\n")

    results = run_full_backtest(symbols, strategies, timeframes,
                                args.start, args.end, output, data_root=data_root)
    print_summary(results)


if __name__ == "__main__":
    main()
