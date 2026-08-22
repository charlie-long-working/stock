#!/usr/bin/env python3
"""
Daily data crawler for VN stocks.

Tasks:
  1. Update OHLCV: mặc định 1D + 1W + 1H (dùng --no-h1 nếu chỉ cần D/W)
  2. Refresh top 100 + top 10 market cap list
  3. Báo cáo tài chính: thứ Hai tự chạy; các ngày khác dùng --fundamentals để ép tải
  4. Save summary to JSON

Usage:
  python -m vn_stock.scripts.crawl_daily
  python -m vn_stock.scripts.crawl_daily --no-h1
  python -m vn_stock.scripts.crawl_daily --fundamentals
"""

import argparse
import json
import time
from datetime import datetime

from vn_stock import DATA_DIR
from vn_stock.data_loaders.vn_ohlcv import update_ohlcv, batch_fetch_ohlcv, DATA_START
from vn_stock.data_loaders.vn_screener import (
    get_top100, get_top10, get_multi_sector_symbols, _fallback_multi_sector,
)
from vn_stock.data_loaders.vn_fundamentals import batch_fetch_fundamentals


def get_all_tracked_symbols() -> list:
    """Get all unique symbols from all sectors."""
    try:
        sectors = get_multi_sector_symbols()
    except Exception:
        sectors = _fallback_multi_sector()

    all_symbols = set()
    for syms in sectors.values():
        all_symbols.update(syms)

    try:
        top100 = get_top100(save=True)
        col = "symbol" if "symbol" in top100.columns else "ticker"
        if col in top100.columns:
            all_symbols.update(top100[col].tolist())
    except Exception as e:
        print(f"[crawl] Could not get top 100: {e}")

    return sorted(all_symbols)


def crawl_ohlcv(symbols: list, intervals: list, delay: float = 0.3):
    """Update OHLCV data for all symbols and intervals."""
    total = len(symbols) * len(intervals)
    done = 0
    errors = []

    for symbol in symbols:
        for interval in intervals:
            done += 1
            print(f"[{done}/{total}] Updating {symbol} {interval}... ", end="", flush=True)
            try:
                df = update_ohlcv(symbol, interval)
                if df is not None:
                    print(f"OK ({len(df)} bars)")
                else:
                    print("no data")
            except Exception as e:
                print(f"ERROR: {e}")
                errors.append(f"{symbol}_{interval}: {e}")
            time.sleep(delay)

    return errors


def crawl_top_lists():
    """Refresh top 100 and top 10 lists."""
    print("\n--- Top 100 ---")
    try:
        top100 = get_top100(save=True)
        print(f"Top 100: {len(top100)} symbols")
    except Exception as e:
        print(f"Top 100 error: {e}")

    print("\n--- Top 10 ---")
    try:
        top10 = get_top10(save=True)
        col = "symbol" if "symbol" in top10.columns else "ticker"
        if col in top10.columns:
            print(f"Top 10: {', '.join(top10[col].tolist())}")
        else:
            print(f"Top 10: {len(top10)} entries")
    except Exception as e:
        print(f"Top 10 error: {e}")


def crawl_fundamentals(symbols: list, force: bool = False):
    """Fetch financial statements. By default only runs weekly (Monday)."""
    today = datetime.now()
    if not force and today.weekday() != 0:
        print("[fundamentals] Skipping (not Monday). Use --fundamentals to force.")
        return

    print(f"\n--- Fundamentals ({len(symbols)} symbols) ---")
    batch_fetch_fundamentals(symbols, period="annual", delay=1.0)
    print(f"\n--- Quarterly data ---")
    batch_fetch_fundamentals(symbols, period="quarter", delay=1.0)


def save_crawl_summary(errors: list):
    """Save crawl summary."""
    summary = {
        "last_crawl": datetime.now().isoformat(),
        "errors": errors,
    }
    path = DATA_DIR / "crawl_summary.json"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"\nSummary saved to {path}")


def main():
    parser = argparse.ArgumentParser(description="VN Stock Daily Crawler")
    parser.add_argument("--no-h1", action="store_true", help="Bỏ nến 1H (mặc định vẫn tải 1D+1W+1H)")
    parser.add_argument("--fundamentals", action="store_true", help="Force fundamentals update")
    parser.add_argument("--symbols", type=str, default=None, help="Override symbol list")
    parser.add_argument("--delay", type=float, default=0.3, help="Delay between API calls")
    parser.add_argument("--initial", action="store_true",
                        help="Initial full crawl (fetch all data from 2012)")
    args = parser.parse_args()

    start = time.time()
    print(f"=== VN Stock Crawler — {datetime.now().strftime('%Y-%m-%d %H:%M')} ===\n")

    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",")]
    else:
        symbols = get_all_tracked_symbols()

    print(f"Tracking {len(symbols)} symbols\n")

    intervals = ["1D", "1W", "1H"]
    if args.no_h1:
        intervals = ["1D", "1W"]

    if args.initial:
        print("=== INITIAL FULL CRAWL ===")
        print(f"Fetching all data from {DATA_START}...\n")
        batch_fetch_ohlcv(symbols, intervals, start=DATA_START, delay=args.delay)
        errors = []
    else:
        errors = crawl_ohlcv(symbols, intervals, delay=args.delay)

    crawl_top_lists()
    crawl_fundamentals(symbols, force=args.fundamentals)
    save_crawl_summary(errors)

    elapsed = time.time() - start
    print(f"\nDone in {elapsed:.0f}s. Errors: {len(errors)}")


if __name__ == "__main__":
    main()
