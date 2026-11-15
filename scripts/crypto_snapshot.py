"""Ảnh chụp BTC/ETH từ Trading-bot – chạy bằng venv của Trading-bot (cwd = Trading-bot, PYTHONPATH = Trading-bot).

In JSON ra stdout: nến ngày (Binance spot → Bybit → fapi, hàm fetch_klines_resilient) và tín hiệu OI live I/K
(scan_oi_live: OI z-score, funding z-score, USDT.D) cho khung 1h và 4h. Không gửi Telegram, không đặt lệnh.
USDT.D: cache của Trading-bot không tự làm mới → làm mới nếu bản ghi cuối cũ hơn 2 ngày.
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import time
from datetime import datetime, timedelta, timezone

import pandas as pd


def _quiet(fn, *a, **k):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        return fn(*a, **k)


def main() -> int:
    from botdown.oi_live_signal import scan_oi_live
    from data_loaders.oi_history import fetch_klines_resilient
    from data_loaders.usdt_d import build_usdt_d_daily

    out = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "source": "Trading-bot data_loaders + botdown.oi_live_signal", "symbols": {}, "errors": []}
    start = (datetime.now(timezone.utc) - timedelta(days=760)).strftime("%Y-%m-%d")
    try:
        ud = _quiet(build_usdt_d_daily, start=start, force_refresh=False)
        last = pd.Timestamp(ud["date"].max())
        if (pd.Timestamp.now() - last).days > 2:
            ud = _quiet(build_usdt_d_daily, start=start, force_refresh=True)
        ud = ud.sort_values("date")
        out["usdt_d"] = {"last_date": str(pd.Timestamp(ud["date"].iloc[-1]).date()),
                         "value": float(ud["usdt_d"].iloc[-1]),
                         "series": [[str(pd.Timestamp(d).date()), round(float(v), 4)]
                                    for d, v in zip(ud["date"].iloc[-365:], ud["usdt_d"].iloc[-365:])],
                         "source": str(ud["usdt_d_source"].iloc[-1]) if "usdt_d_source" in ud.columns else "Trading-bot usdt_d"}
    except Exception as e:
        out["errors"].append(f"USDT.D: {type(e).__name__}: {str(e)[:200]}")
    for sym in ("BTCUSDT", "ETHUSDT"):
        d: dict = {}
        try:
            k = _quiet(fetch_klines_resilient, sym, interval="1d", start=start).sort_values("date")
            d["daily"] = [[str(pd.Timestamp(r.date).date()), float(r.open), float(r.high), float(r.low), float(r.close),
                           float(r.volume)] for r in k.itertuples()]
        except Exception as e:
            out["errors"].append(f"{sym} klines: {type(e).__name__}: {str(e)[:200]}")
        d["oi"] = {}
        for iv in ("1h", "4h"):
            try:
                a = _quiet(scan_oi_live, sym, interval=iv, include_liq=False)
                d["oi"][iv] = a.as_dict()
            except Exception as e:
                d["oi"][iv] = {"error": f"{type(e).__name__}: {str(e)[:200]}"}
            time.sleep(0.5)
        out["symbols"][sym] = d
    json.dump(out, sys.stdout, ensure_ascii=False, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(main())
