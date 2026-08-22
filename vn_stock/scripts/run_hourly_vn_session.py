#!/usr/bin/env python3
"""
Phiên hourly VN (T2–T6, 8h–14h Asia/Ho_Chi_Minh):

  1. Cập nhật nến 1H (+ build 4H, refresh 1D)
  2. Quét tín hiệu giao dịch (MACD+RSI crypto engine, long-only + EMA filter)
  3. Ghi snapshot JSON + gửi Telegram khi có lệnh (tier1/tier2)

Chạy một lần (cron/launchd gọi mỗi giờ):
  cd stock
  PYTHONPATH=".:../Trading-bot" .venv/bin/python -m vn_stock.scripts.run_hourly_vn_session
  ... --dry-run
  ... --force          # bỏ qua check giờ/thứ
  ... --heartbeat      # gửi tin "đã scan" kể cả khi không có signal
  ... --symbols VCB,FPT,HPG

Lịch gợi ý (cron, máy local ICT):
  5 8-14 * * 1-5  /path/to/stock/deploy/run_hourly_vn.sh
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

STOCK_ROOT = Path(__file__).resolve().parents[2]
TB_ROOT = STOCK_ROOT.parent / "Trading-bot"
for p in (str(STOCK_ROOT), str(TB_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from dotenv import load_dotenv

    load_dotenv(STOCK_ROOT / ".env")
    load_dotenv(TB_ROOT / ".env")
except ImportError:
    pass

import numpy as np

from vn_stock import DATA_DIR
from vn_stock.data_loaders.vn_ohlcv import (
    build_h4_from_h1,
    load_ohlcv_arrays,
    update_ohlcv,
)
from vn_stock.data_loaders.vn_screener import get_vn30
from vn_stock.notify.telegram import send_message

TZ = ZoneInfo("Asia/Ho_Chi_Minh")
DEFAULT_OPEN = 8
DEFAULT_CLOSE = 15  # exclusive → chạy tới hết giờ 14
DEFAULT_SYMBOLS = [
    "VCB", "BID", "TCB", "CTG", "MBB", "FPT", "HPG", "MWG",
    "MSN", "GAS", "VHM", "VNM", "SSI", "ACB", "VPB",
]
OUT_DIR = DATA_DIR / "screening"
SNAPSHOT_PATH = OUT_DIR / "hourly_vn_snapshot.json"
SENT_CACHE = OUT_DIR / "hourly_vn_sent.json"


@dataclass
class TradeIdea:
    symbol: str
    interval: str
    tier: str  # tier1 | tier2
    side: str
    close: float
    stop_loss: Optional[float]
    take_profit: Optional[float]
    rsi: Optional[float]
    hist: Optional[float]
    reason: str
    bar_time: str


def _now() -> datetime:
    return datetime.now(TZ)


def in_session(
    now: Optional[datetime] = None,
    open_hour: int = DEFAULT_OPEN,
    close_hour: int = DEFAULT_CLOSE,
) -> bool:
    """T2–T6, [open_hour, close_hour)."""
    now = now or _now()
    if now.weekday() >= 5:
        return False
    return open_hour <= now.hour < close_hour


def _symbols(arg: Optional[str]) -> List[str]:
    if arg:
        return [s.strip().upper() for s in arg.split(",") if s.strip()]
    try:
        df = get_vn30(save=False)
        col = next((c for c in ("symbol", "ticker", "Symbol") if c in df.columns), None)
        if col is not None and len(df):
            return sorted({str(x).strip().upper() for x in df[col].tolist()})[:30]
    except Exception:
        pass
    return list(DEFAULT_SYMBOLS)


def _bar_time_str(ot: np.ndarray, idx: int = -1) -> str:
    t = int(ot[idx])
    unit = "ms" if t > 1e12 else "s"
    import pandas as pd

    return str(pd.to_datetime(t, unit=unit))


def update_candles(symbols: List[str], delay: float, fetch: bool) -> Dict[str, dict]:
    coverage: Dict[str, dict] = {}
    for i, sym in enumerate(symbols, 1):
        coverage[sym] = {}
        for tf in ("1H", "1D"):
            print(f"[{i}/{len(symbols)}] update {sym} {tf}...", end=" ", flush=True)
            try:
                if fetch:
                    df = update_ohlcv(sym, tf)
                else:
                    from vn_stock.data_loaders.vn_ohlcv import load_ohlcv

                    df = load_ohlcv(sym, tf)
                n = 0 if df is None else len(df)
                coverage[sym][tf] = n
                print(f"{n} bars")
            except Exception as e:
                coverage[sym][tf] = 0
                print(f"ERR {e}")
            if fetch:
                time.sleep(delay)
        try:
            df4 = build_h4_from_h1(sym)
            coverage[sym]["4H"] = 0 if df4 is None else len(df4)
        except Exception:
            coverage[sym]["4H"] = 0
    return coverage


def _screen_interval(symbol: str, interval: str) -> Optional[TradeIdea]:
    """MACD+RSI + EMA filter (crypto engine), long-only — không sửa botdown."""
    from botdown.engine_macd_rsi_bt import (
        MacdRsiParams,
        macd_rsi_entry_snapshot,
        _rsi_wilder,
        _ema,
        ema_trend_bull_bear,
    )

    data = load_ohlcv_arrays(symbol, interval)
    if data is None:
        return None
    ot, o, h, l, c, v = data
    if len(c) < 60:
        return None

    p = MacdRsiParams(
        exit_mode="pct",
        take_profit_pct=0.10,
        stop_loss_pct=0.04,
        use_ema_trend_filter=True,
    )
    snap = macd_rsi_entry_snapshot(ot, h, l, c, params=p, allow_short=False)
    bar_t = _bar_time_str(ot)

    ema_f = _ema(c, 12)
    ema_s = _ema(c, 26)
    hist = (ema_f - ema_s) - _ema(ema_f - ema_s, 9)
    rsi = _rsi_wilder(c, 14)
    bull, _ = ema_trend_bull_bear(c, 20, 50)
    i = len(c) - 1
    close = float(c[i])

    if snap and snap.get("side") == "long":
        return TradeIdea(
            symbol=symbol,
            interval=interval,
            tier="tier1",
            side="long",
            close=close,
            stop_loss=float(snap["stop"]) if snap.get("stop") is not None else close * 0.96,
            take_profit=float(snap["tp"]) if snap.get("tp") is not None else close * 1.10,
            rsi=float(rsi[i]),
            hist=float(hist[i]),
            reason="MACD hist cross↑0 + RSI<OB + EMA bull",
            bar_time=bar_t,
        )

    # Tier2: bull + RSI kéo + hist đang hồi (chưa cross)
    if bull[i] and 30 <= rsi[i] <= 48 and hist[i] < 0 and i >= 1 and hist[i] > hist[i - 1]:
        return TradeIdea(
            symbol=symbol,
            interval=interval,
            tier="tier2",
            side="long",
            close=close,
            stop_loss=close * 0.96,
            take_profit=close * 1.10,
            rsi=float(rsi[i]),
            hist=float(hist[i]),
            reason="Bull EMA + RSI pullback + hist rising (chưa cross 0)",
            bar_time=bar_t,
        )
    return None


def scan_ideas(symbols: List[str], intervals: List[str]) -> List[TradeIdea]:
    ideas: List[TradeIdea] = []
    for sym in symbols:
        for tf in intervals:
            try:
                idea = _screen_interval(sym, tf)
                if idea:
                    ideas.append(idea)
                    print(f"  SIGNAL {idea.tier} {sym} {tf} close={idea.close:.2f}")
            except Exception as e:
                print(f"  scan fail {sym} {tf}: {e}", file=sys.stderr)
    # Prefer tier1, then 1D over 1H for same symbol
    rank = {"tier1": 0, "tier2": 1}
    tf_rank = {"1D": 0, "4H": 1, "1H": 2, "1W": 3}
    ideas.sort(key=lambda x: (rank.get(x.tier, 9), tf_rank.get(x.interval, 9), x.symbol))
    return ideas


def _load_sent() -> set:
    if not SENT_CACHE.exists():
        return set()
    try:
        return set(json.loads(SENT_CACHE.read_text(encoding="utf-8")).get("keys", []))
    except Exception:
        return set()


def _save_sent(keys: set) -> None:
    SENT_CACHE.parent.mkdir(parents=True, exist_ok=True)
    SENT_CACHE.write_text(
        json.dumps({"updated_at": _now().isoformat(), "keys": sorted(keys)[-400:]}, indent=2),
        encoding="utf-8",
    )


def _dedupe_key(idea: TradeIdea, day: str) -> str:
    return f"{day}|{idea.symbol}|{idea.interval}|{idea.tier}|{idea.side}"


def format_telegram(ideas: List[TradeIdea], now: datetime) -> str:
    lines = [
        f"<b>VN HOURLY</b> {now.strftime('%a %Y-%m-%d %H:%M')} ICT",
        f"Signals: <b>{len(ideas)}</b>",
        "",
    ]
    for idea in ideas:
        lines.append(
            f"<b>{idea.symbol}</b> {idea.interval} · {idea.tier.upper()} LONG"
        )
        lines.append(f"Close <code>{idea.close:.2f}</code> | RSI {idea.rsi:.1f}" if idea.rsi is not None else f"Close <code>{idea.close:.2f}</code>")
        if idea.stop_loss is not None:
            lines.append(f"SL <code>{idea.stop_loss:.2f}</code> · TP <code>{idea.take_profit:.2f}</code>")
        lines.append(f"<i>{idea.reason}</i>")
        lines.append("")
    lines.append("<i>Không phải lời khuyên đầu tư.</i>")
    return "\n".join(lines)


def format_heartbeat(now: datetime, n_sym: int, n_sig: int) -> str:
    return (
        f"<b>VN hourly OK</b> {now.strftime('%H:%M')} ICT\n"
        f"Đã cập nhật {n_sym} mã · tín hiệu mới: {n_sig}\n"
        f"<i>Không phải lời khuyên đầu tư.</i>"
    )


def write_snapshot(payload: dict) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    # also timestamped copy for history
    stamp = _now().strftime("%Y%m%d_%H%M")
    hist = OUT_DIR / f"hourly_vn_{stamp}.json"
    hist.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return SNAPSHOT_PATH


def main() -> int:
    ap = argparse.ArgumentParser(description="VN hourly update + trade ideas")
    ap.add_argument("--symbols", type=str, default=None)
    ap.add_argument("--intervals", type=str, default="1D,1H", help="Khung quét tín hiệu")
    ap.add_argument("--delay", type=float, default=3.5, help="Delay giữa API crawl")
    ap.add_argument("--no-fetch", action="store_true")
    ap.add_argument("--force", action="store_true", help="Bỏ qua cửa sổ T2–T6 8–14h")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--heartbeat", action="store_true", help="Telegram kể cả khi 0 signal")
    ap.add_argument("--open-hour", type=int, default=int(os.environ.get("VN_SESSION_OPEN", DEFAULT_OPEN)))
    ap.add_argument("--close-hour", type=int, default=int(os.environ.get("VN_SESSION_CLOSE", DEFAULT_CLOSE)))
    args = ap.parse_args()

    now = _now()
    if not args.force and not in_session(now, args.open_hour, args.close_hour):
        print(
            f"Ngoài phiên ({now.strftime('%a %H:%M')} ICT). "
            f"Cửa sổ: T2–T6 {args.open_hour}:00–{args.close_hour}:00. Dùng --force để chạy."
        )
        return 0

    symbols = _symbols(args.symbols)
    intervals = [x.strip().upper() for x in args.intervals.split(",") if x.strip()]
    print(f"=== VN hourly {now.strftime('%Y-%m-%d %H:%M %Z')} | {len(symbols)} mã | TF {intervals} ===\n")

    coverage = update_candles(symbols, delay=args.delay, fetch=not args.no_fetch)
    print("\n--- Scan ---")
    ideas = scan_ideas(symbols, intervals)

    day = now.strftime("%Y-%m-%d")
    sent_cache = _load_sent()
    new_ideas = [x for x in ideas if _dedupe_key(x, day) not in sent_cache]

    payload: Dict[str, Any] = {
        "generated_at": now.isoformat(),
        "session": f"T2-T6 {args.open_hour}:00-{args.close_hour}:00 ICT",
        "symbols": symbols,
        "intervals": intervals,
        "coverage": coverage,
        "ideas": [asdict(x) for x in ideas],
        "new_ideas": [asdict(x) for x in new_ideas],
        "note": "MACD+RSI TP10/SL4 + EMA filter (botdown import). Not investment advice.",
    }
    path = write_snapshot(payload)
    print(f"\nSnapshot: {path}")
    print(f"Ideas total={len(ideas)} new={len(new_ideas)}")

    if args.dry_run:
        if new_ideas:
            print("--- Telegram preview ---")
            print(format_telegram(new_ideas, now).replace("<b>", "").replace("</b>", "").replace("<code>", "").replace("</code>", "").replace("<i>", "").replace("</i>", ""))
        elif args.heartbeat:
            print(format_heartbeat(now, len(symbols), 0))
        return 0

    if new_ideas:
        ok, err = send_message(format_telegram(new_ideas, now))
        if ok:
            print(f"Telegram OK ({len(new_ideas)} signals)")
            for x in new_ideas:
                sent_cache.add(_dedupe_key(x, day))
            _save_sent(sent_cache)
        else:
            print(f"Telegram fail: {err}", file=sys.stderr)
            return 1
    elif args.heartbeat:
        ok, err = send_message(format_heartbeat(now, len(symbols), 0))
        print("Heartbeat sent" if ok else f"Heartbeat fail: {err}")
    else:
        print("Không có tín hiệu mới — không gửi Telegram.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
