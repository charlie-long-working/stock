#!/usr/bin/env python3
"""
Backtest strategy trên crypto (Yahoo Finance) — dùng cùng engine vn_stock.

Ví dụ Bitcoin daily:
  pip install yfinance
  cd stock
  python3 -m vn_stock.scripts.run_backtest_crypto --ticker BTC-USD --interval 1D --fetch

Dữ liệu lưu: vn_stock/data/crypto/ohlcv/BTC-USD/1D.csv
"""

import argparse
import sys
from pathlib import Path

from vn_stock.backtest.engine import run_backtest
from vn_stock.data_loaders.crypto_ohlcv import default_crypto_data_root, fetch_and_save_yahoo


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest crypto (Yahoo OHLCV)")
    parser.add_argument("--ticker", type=str, default="BTC-USD", help="Yahoo symbol, e.g. BTC-USD, ETH-USD")
    parser.add_argument("--interval", type=str, default="1D", help="1H, 1D, 1W")
    parser.add_argument("--start", type=str, default="2017-01-01", help="Ngày bắt đầu tải dữ liệu YYYY-MM-DD")
    parser.add_argument("--end", type=str, default=None, help="Ngày kết thúc (optional)")
    parser.add_argument("--fetch", action="store_true", help="Tải / cập nhật CSV từ Yahoo trước khi chạy")
    parser.add_argument("--strategy", type=str, default="div_macd_rsi", help="macd_rsi, ma_crossover, regime_fusion, div_macd_rsi")
    parser.add_argument("--bt-start", type=str, default=None, help="Giới hạn backtest từ (YYYY-MM-DD)")
    parser.add_argument("--bt-end", type=str, default=None, help="Giới hạn backtest đến (YYYY-MM-DD)")
    args = parser.parse_args()

    sym = args.ticker.strip().upper()
    root = default_crypto_data_root()
    root.mkdir(parents=True, exist_ok=True)

    if args.fetch:
        print(f"Đang tải {sym} {args.interval} từ Yahoo (start={args.start}) …")
        p = fetch_and_save_yahoo(
            sym,
            interval=args.interval,
            start=args.start,
            end=args.end,
            data_root=root,
        )
        if p is None:
            print("Không tải được dữ liệu.", file=sys.stderr)
            sys.exit(1)
        print(f"Đã lưu: {p}")

    print(f"Backtest {sym} | {args.strategy} | {args.interval} …")
    r = run_backtest(
        symbol=sym,
        strategy=args.strategy,
        interval=args.interval.upper(),
        start_date=args.bt_start,
        end_date=args.bt_end,
        data_root=root,
    )
    if r is None:
        print("Không chạy được backtest (thiếu CSV hoặc không đủ dữ liệu). Chạy thêm --fetch.", file=sys.stderr)
        sys.exit(1)

    print(
        f"return={r.total_return_pct:+.2f}%  hold={r.hold_return_pct:+.2f}%  "
        f"trades={r.num_trades}  win={r.win_rate:.1f}%  "
        f"sharpe={r.sharpe_ratio:.2f}  maxDD={r.max_drawdown_pct:.1f}%"
    )


if __name__ == "__main__":
    main()
