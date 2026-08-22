#!/usr/bin/env python3
"""
Telegram signal bot for Vietnamese stocks.

Scans configured symbols, sends Long signals + combined analysis to Telegram.

Usage:
  python -m vn_stock.scripts.run_telegram_signal
  python -m vn_stock.scripts.run_telegram_signal --symbols VCB,BID,TCB --dry-run
  python -m vn_stock.scripts.run_telegram_signal --combined  # Include fundamental analysis
  python -m vn_stock.scripts.run_telegram_signal --loop       # Run continuously during market hours
"""

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    from dotenv import load_dotenv
    _stock_root = Path(__file__).resolve().parent.parent.parent
    load_dotenv(_stock_root / ".env")
except ImportError:
    pass

from vn_stock.signals.vn_signal import (
    scan_signals,
    format_signal_telegram,
    format_consensus_telegram,
    VNConsensusSignal,
)
from vn_stock.analysis.combined_signal import get_combined_signals, format_combined_telegram, load_live_vn_models
from vn_stock.data_loaders.vn_screener import _fallback_multi_sector
from vn_stock.notify.telegram import send_message


DEFAULT_SYMBOLS = [
    "VCB", "BID", "CTG", "TCB", "MBB", "ACB", "VPB", "FPT",
    "HPG", "VHM", "GAS", "SSI", "VNM", "MSN", "PLX", "SAB",
    "VIC", "NVL", "DPM", "DCM", "STB", "HDB", "TPB",
]

MARKET_OPEN_HOUR = 8   # ICT — phiên hourly từ 8h
MARKET_CLOSE_HOUR = 15  # exclusive → tới hết 14h
SCAN_INTERVAL_MINUTES = 60


def _is_market_hours() -> bool:
    """T2–T6, [MARKET_OPEN_HOUR, MARKET_CLOSE_HOUR) theo giờ máy (nên đặt TZ=Asia/Ho_Chi_Minh)."""
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    return MARKET_OPEN_HOUR <= now.hour < MARKET_CLOSE_HOUR


def run_signal_scan(
    symbols: list,
    intervals: list,
    strategies: list,
    use_combined: bool = False,
    use_consensus: bool = True,
    min_votes: int = 2,
    dry_run: bool = False,
    update_data: bool = True,
) -> int:
    """Run one scan cycle. Returns number of signals sent."""
    sent = 0
    live_models = load_live_vn_models()

    if use_combined:
        combined = get_combined_signals(
            symbols=symbols,
            intervals=intervals,
            strategies=strategies,
            update_data=update_data,
            min_tech_votes=min_votes,
            require_consensus=use_consensus,
            live_models=live_models,
            log_signals=not dry_run,
        )
        for sig in combined:
            msg = format_combined_telegram(sig)
            if dry_run:
                print("---")
                print(msg.replace("<b>", "").replace("</b>", "").replace("<code>", "").replace("</code>", ""))
                sent += 1
            else:
                ok, err = send_message(msg)
                if ok:
                    sent += 1
                    print(f"Sent: {sig.symbol} ({sig.interval}) tier={sig.consensus_tier} score={sig.combined_score:.2f}")
                else:
                    print(f"Failed: {sig.symbol}: {err}", file=sys.stderr)
    elif use_consensus:
        signals = scan_signals(
            symbols=symbols,
            intervals=intervals,
            strategies=strategies,
            update_data=update_data,
            consensus=True,
            min_votes=min_votes,
            live_models=live_models,
        )
        for sig in signals:
            if not isinstance(sig, VNConsensusSignal):
                continue
            msg = format_consensus_telegram(sig)
            if dry_run:
                print("---")
                print(msg.replace("<b>", "").replace("</b>", "").replace("<code>", "").replace("</code>", ""))
                sent += 1
            else:
                ok, err = send_message(msg)
                if ok:
                    sent += 1
                    c = sig.consensus
                    print(f"Sent: {sig.symbol} ({sig.interval}) tier={c.tier} votes={c.vote_count}/3")
                else:
                    print(f"Failed: {sig.symbol}: {err}", file=sys.stderr)
    else:
        signals = scan_signals(
            symbols=symbols,
            intervals=intervals,
            strategies=strategies,
            update_data=update_data,
        )
        for sig in signals:
            msg = format_signal_telegram(sig)
            if dry_run:
                print("---")
                print(msg.replace("<b>", "").replace("</b>", "").replace("<code>", "").replace("</code>", ""))
                sent += 1
            else:
                ok, err = send_message(msg)
                if ok:
                    sent += 1
                    print(f"Sent: {sig.symbol} {sig.strategy} ({sig.interval})")
                else:
                    print(f"Failed: {sig.symbol}: {err}", file=sys.stderr)

    return sent


def run_loop(symbols, intervals, strategies, use_combined, use_consensus, min_votes, dry_run):
    """Run continuously during market hours."""
    print(f"Starting signal loop. Interval: {SCAN_INTERVAL_MINUTES}m. Market hours: {MARKET_OPEN_HOUR}:00-{MARKET_CLOSE_HOUR}:00")
    print(f"Symbols: {len(symbols)} | Strategies: {strategies} | TF: {intervals} | consensus={use_consensus}")

    while True:
        if _is_market_hours():
            now = datetime.now().strftime("%H:%M:%S")
            print(f"\n[{now}] Scanning...")
            try:
                sent = run_signal_scan(
                    symbols, intervals, strategies, use_combined, use_consensus, min_votes, dry_run, update_data=True
                )
                print(f"[{now}] Sent {sent} signals")
            except Exception as e:
                print(f"[{now}] Error: {e}", file=sys.stderr)
        else:
            now = datetime.now().strftime("%H:%M")
            print(f"[{now}] Outside market hours. Waiting...")

        time.sleep(SCAN_INTERVAL_MINUTES * 60)


def main():
    parser = argparse.ArgumentParser(description="VN Stock Telegram Signal Bot")
    parser.add_argument("--symbols", type=str, default=None,
                        help="Comma-separated symbols")
    parser.add_argument("--intervals", type=str, default="1D",
                        help="Comma-separated timeframes (1H,1D,1W)")
    parser.add_argument("--strategies", type=str, default="macd_rsi,ma_crossover,regime_fusion",
                        help="Comma-separated strategies")
    parser.add_argument("--combined", action="store_true",
                        help="Use combined (tech consensus + fundamental) analysis")
    parser.add_argument("--no-consensus", action="store_true",
                        help="Legacy OR mode (any 1 strategy fires)")
    parser.add_argument("--min-votes", type=int, default=2,
                        help="Min agreeing models (default 2/3)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print signals without sending to Telegram")
    parser.add_argument("--loop", action="store_true",
                        help="Run continuously during market hours")
    parser.add_argument("--update", action="store_true", default=True,
                        help="Update OHLCV data before scanning")
    args = parser.parse_args()

    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",")]
    else:
        symbols = DEFAULT_SYMBOLS

    intervals = [t.strip() for t in args.intervals.split(",")]
    strategies = [s.strip() for s in args.strategies.split(",")]

    use_consensus = not args.no_consensus

    if args.loop:
        run_loop(symbols, intervals, strategies, args.combined, use_consensus, args.min_votes, args.dry_run)
    else:
        sent = run_signal_scan(
            symbols, intervals, strategies, args.combined, use_consensus, args.min_votes, args.dry_run, args.update
        )
        if sent == 0:
            print("No Long signals found for current scan.")


if __name__ == "__main__":
    main()
