#!/usr/bin/env python3
"""
Crawl/cập nhật OHLCV 1D cho mã blue-chip (VN30), lọc **điểm mua** theo MACD+RSI + EMA bull/bear
(khớp `botdown.engine_macd_rsi_bt` + Pine).

- **Ưu tiên 1 — Tín hiệu long (đẹp nhất):** MACD hist vừa cắt lên 0 + RSI < OB + bull (EMA20>EMA50 & close>EMA50).
- **Ưu tiên 2 — Setup kéo (theo dõi):** đang bull nhưng chưa có cross; RSI pullback; hist đang hồi lên.

Cần sibling repo **Trading-bot** (cùng thư mục cha với `stock/`) để import engine.

Chạy từ thư mục `stock`:
  python -m vn_stock.scripts.screen_bluechip_macd_buy
  python -m vn_stock.scripts.screen_bluechip_macd_buy --no-fetch   # chỉ đọc CSV có sẵn
  python -m vn_stock.scripts.screen_bluechip_macd_buy --symbols VCB,FPT,BID
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

# vn_stock
STOCK_ROOT = Path(__file__).resolve().parents[2]
if str(STOCK_ROOT) not in sys.path:
    sys.path.insert(0, str(STOCK_ROOT))

# Trading-bot (MACD engine)
CURSOR_ROOT = STOCK_ROOT.parent
TB_ROOT = CURSOR_ROOT / "Trading-bot"
if TB_ROOT.is_dir() and str(TB_ROOT) not in sys.path:
    sys.path.insert(0, str(TB_ROOT))

from vn_stock.data_loaders.vn_ohlcv import load_ohlcv_arrays, update_ohlcv  # noqa: E402
from vn_stock.data_loaders.vn_screener import get_vn30  # noqa: E402
from vn_stock import DATA_DIR  # noqa: E402


def _symbol_col(df) -> Optional[str]:
    for c in ("symbol", "ticker", "Symbol"):
        if c in df.columns:
            return c
    return None


def _analyze_secondary(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
) -> Tuple[bool, str]:
    """Setup pullback trong bull: chưa cross zero nhưng hist cải thiện, RSI vùng kéo."""
    from botdown.engine_macd_rsi_bt import (  # noqa: WPS433
        _ema,
        _rsi_wilder,
        ema_trend_bull_bear,
    )

    cl = np.asarray(close, dtype=float)
    hi = np.asarray(high, dtype=float)
    lo = np.asarray(low, dtype=float)
    n = len(cl)
    if n < 50:
        return False, ""
    fast, slow, sig = 12, 26, 9
    ema_f = _ema(cl, fast)
    ema_s = _ema(cl, slow)
    macd_line = ema_f - ema_s
    sig_line = _ema(macd_line, sig)
    hist = macd_line - sig_line
    rsi = _rsi_wilder(cl, 14)
    bull, _ = ema_trend_bull_bear(cl, 20, 50)
    i = n - 1
    if not bull[i]:
        return False, ""
    if hist[i] >= 0:
        return False, ""
    if not (hist[i] > hist[i - 1]):
        return False, ""
    r = rsi[i]
    if not (30 <= r <= 48):
        return False, ""
    return True, f"pullback bull RSI={r:.1f} hist↑ MACD chưa cắt 0"


def main() -> None:
    ap = argparse.ArgumentParser(description="Screen VN30 MACD+RSI + EMA buy")
    ap.add_argument("--no-fetch", action="store_true", help="Không gọi API cập nhật OHLCV")
    ap.add_argument("--sleep", type=float, default=4.0, help="Giây giữa mỗi lần fetch (rate limit)")
    ap.add_argument(
        "--symbols",
        type=str,
        default=None,
        help="Danh sách mã cách nhau bởi dấu phẩy (bỏ qua VN30 nếu có)",
    )
    args = ap.parse_args()

    try:
        from botdown.engine_macd_rsi_bt import MacdRsiParams, macd_rsi_entry_snapshot  # noqa: WPS433
    except ImportError:
        print(
            f"Không import được botdown. Đặt Trading-bot tại: {TB_ROOT} (cùng cấp với thư mục stock).",
            file=sys.stderr,
        )
        sys.exit(1)

    params = MacdRsiParams(
        exit_mode="pct",
        take_profit_pct=0.10,
        stop_loss_pct=0.04,
        fee_roundtrip=0.001,
        use_ema_trend_filter=True,
        ema_trend_fast=20,
        ema_trend_slow=50,
    )

    if args.symbols:
        symbols = sorted({s.strip().upper() for s in args.symbols.split(",") if s.strip()})
    else:
        df = get_vn30(save=True)
        col = _symbol_col(df)
        if col is None or len(df) == 0:
            print("Không lấy được danh sách VN30.", file=sys.stderr)
            sys.exit(1)
        symbols = sorted({str(s).strip().upper() for s in df[col].tolist() if str(s).strip()})
    print(f"VN30: {len(symbols)} mã — {', '.join(symbols)}\n")

    tier1: List[Dict[str, Any]] = []
    tier2: List[Dict[str, Any]] = []
    skipped: List[str] = []

    for sym in symbols:
        if not args.no_fetch:
            try:
                update_ohlcv(sym, "1D", source="VCI", data_root=DATA_DIR)
                time.sleep(max(0.5, args.sleep))
            except Exception as e:
                print(f"  [{sym}] update: {e}")

        raw = load_ohlcv_arrays(sym, "1D", data_root=DATA_DIR)
        if raw is None:
            skipped.append(f"{sym} (no CSV)")
            continue
        open_time, open_, high, low, close, volume = raw
        if len(close) < 60:
            skipped.append(f"{sym} (short history)")
            continue

        snap = macd_rsi_entry_snapshot(
            open_time, high, low, close, params=params, allow_short=False
        )
        if snap and snap.get("side") == "long":
            tier1.append(
                {
                    "symbol": sym,
                    "close": round(float(close[-1]), 2),
                    "entry_ref": round(snap["entry_ref"], 2),
                    "stop": round(snap["stop"], 2),
                    "tp": round(snap["tp"], 2),
                    "note": "MACD hist cắt 0 + RSI + bull EMA20/50",
                }
            )
            continue

        ok2, note2 = _analyze_secondary(high, low, close)
        if ok2:
            tier2.append(
                {
                    "symbol": sym,
                    "close": round(float(close[-1]), 2),
                    "note": note2,
                }
            )

    out_dir = DATA_DIR / "screening"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "bluechip_macd_ema_buy.json"
    payload = {
        "criteria": {
            "tier1": "macd_rsi_entry_snapshot long + EMA bull (20/50)",
            "tier2": "bull + RSI 30–48 + hist tăng, MACD hist vẫn < 0",
        },
        "tier1_signal_long": tier1,
        "tier2_setup_pullback": tier2,
        "skipped": skipped,
    }
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    print("=== Ưu tiên 1 — Tín hiệu LONG (điểm mua theo rule) ===")
    if not tier1:
        print("  (Không có mã nào khớp nến cuối)")
    for x in tier1:
        print(f"  {x['symbol']}: close {x['close']}  SL {x['stop']}  TP {x['tp']}  ref {x['entry_ref']}")

    print("\n=== Ưu tiên 2 — Setup pullback trong bull (theo dõi) ===")
    if not tier2:
        print("  (Không có)")
    for x in tier2:
        print(f"  {x['symbol']}: close {x['close']} — {x['note']}")

    if skipped:
        print("\n=== Bỏ qua ===")
        for s in skipped[:20]:
            print(f"  {s}")
        if len(skipped) > 20:
            print(f"  ... +{len(skipped) - 20} mã")

    print(f"\nĐã ghi {out_path}")
    print(
        "\nLưu ý: không phải lời khuyên đầu tư; dữ liệu phụ thuộc vnstock/VCI và CSV local."
    )


if __name__ == "__main__":
    main()
