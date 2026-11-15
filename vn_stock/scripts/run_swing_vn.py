#!/usr/bin/env python3
"""
Tín hiệu cổ phiếu VN trên nến NGÀY đã đóng + bản tin xu hướng TUẦN → Telegram (bot-trading-charlie).

Chạy local bằng launchd com.cursor.swing-vn (T2–T6 16:00, sau Stock Intelligence 15:30).
Không gọi API giá: đọc kho giá đã điều chỉnh cổ tức `vn_stock/data/intel/ohlcv_adj/` do lần quét
Stock Intelligence cập nhật; chờ tối đa --wait-min phút nếu lần quét hôm nay chưa xong.

1D — chỉ lệnh MUA (tài khoản thường không bán khống), T+2:
  - macd_rsi_atr : MACD hist cắt lên 0 + RSI<70; SL 1,5×ATR, TP 2,5×ATR (backtest VN30 tốt nhất toàn mẫu)
  - macd_signed  : MACD+ cross/tiếp diễn/đảo chiều, SL swing+ATR, TP 2R (bản long-only)
  Lọc thanh khoản: GTGD TB 20 phiên ≥ --min-value-bn tỷ. Kèm điểm/khuyến nghị Stock Intelligence,
  cờ EMA20/50, chế độ thị trường, xu hướng tuần.
1W — bản tin xu hướng tuần (EMA20/50, mây Ichimoku, MACD, RSI) khi tuần đã đóng (sau 15:00 thứ 6).
Thêm (11/2026):
  - Thu thập mua/bán chủ động (vn_stock/tape) sau Stock Intelligence; tin "Dòng tiền chủ động" top 10/ngày.
  - Setup nền giá/phân kỳ theo kết luận backtest đã khoá (vn_stock/setups/config.json): ship → MUA, watch → THEO DÕI.
  - Sổ lệnh giấy (vn_stock/setups/ledger.py): mọi lệnh MUA đã gửi được theo dõi; báo BÁN/THOÁT theo cùng engine
    thoát của backtest (T+2). Tin MUA ghi % vốn tối đa theo rủi ro 1% (trần 20%/mã, tối đa 5 mã).

  PYTHONPATH="$PWD:$PWD/../Trading-bot" .venv/bin/python -m vn_stock.scripts.run_swing_vn --dry-run
  ... --symbols VCB,FPT --wait-min 0 --dry-run
  ... --weekly-only --dry-run
  ... --no-tape            # bỏ bước thu thập mua/bán chủ động (~6 phút, 100 request)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

STOCK_ROOT = Path(__file__).resolve().parents[2]
TB_ROOT = STOCK_ROOT.parent / "Trading-bot"
for p in (str(STOCK_ROOT), str(TB_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from botdown.swing_common import (  # noqa: E402  (shared with Trading-bot / precious-metals)
    SentStore,
    Signal,
    deliver,
    format_signal,
    h,
    now_vn,
    resample_ohlc,
    split_messages,
    trend_line,
    weekly_trend,
)
from vn_stock import DATA_DIR  # noqa: E402
from vn_stock.setups import live as LIVE  # noqa: E402
from vn_stock.setups.ledger import STRATEGY_EXITS, Ledger, format_exit  # noqa: E402
from vn_stock.setups.sizing import sizing_note  # noqa: E402
from vn_stock.tape import collect as TAPE  # noqa: E402
from vn_stock.tape.metrics import daily_leaders, format_leaders, tape_features, tape_note  # noqa: E402
from vn_stock.strategies.macd_rsi import MACDRSISignalType, macd_rsi_signal  # noqa: E402
from vn_stock.strategies.macd_signed import MacdSignedParams, macd_signed_signal  # noqa: E402

INTEL = DATA_DIR / "intel"
ADJ = INTEL / "ohlcv_adj"
STORE = DATA_DIR / "screening" / "swing_vn_sent.json"
LEDGER_PATH = DATA_DIR / "screening" / "swing_vn_ledger.json"
INDICES = ["VNINDEX", "VN30", "HNXINDEX"]

EVIDENCE = {
    "macd_rsi_atr": "ngoài mẫu 2024+ (97 mã, sau phí, T+2): 2.235 lệnh, win 33%, PF 0,78, TB −0,63%/lệnh — "
                    "CHƯA có lợi thế (docs/BACKTEST_SETUPS_2026-11-15.md)",
    "macd_signed": "VN30: PF trung vị 1,37 (bản có short); bản chỉ MUA chưa backtest riêng",
}


def _today() -> str:
    return now_vn().strftime("%Y-%m-%d")


def _load(sym: str) -> Optional[pd.DataFrame]:
    p = ADJ / f"{sym}.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p, parse_dates=["time"]).dropna(subset=["close"])
    return df.sort_values("time").drop_duplicates("time", keep="last").reset_index(drop=True)


def _expected_last_session() -> str:
    """Phiên gần nhất đã đóng (T2–T6; trước 15:00 thì là phiên hôm trước). Chưa tính ngày lễ."""
    now = now_vn()
    d = pd.Timestamp(now.date())
    if now.hour < 15:
        d -= pd.Timedelta(days=1)
    while d.weekday() >= 5:
        d -= pd.Timedelta(days=1)
    return d.strftime("%Y-%m-%d")


def wait_for_intel(wait_min: float) -> str:
    """Chờ lần quét Stock Intelligence hôm nay xong (state=done). Trả về mô tả trạng thái."""
    status_p = INTEL / "scan_status.json"
    deadline = time.time() + wait_min * 60
    while True:
        try:
            st = json.loads(status_p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            st = {}
        started = str(st.get("started_at", ""))[:10]
        if st.get("state") == "done" and started == _today():
            return f"intel scan {st.get('scan_id')} xong"
        if time.time() >= deadline:
            return f"intel chưa xong (state={st.get('state')}, started={started}) — dùng dữ liệu hiện có"
        time.sleep(60)


def _intel_index() -> Tuple[Dict[str, dict], dict]:
    try:
        d = json.loads((INTEL / "latest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}, {}
    return {s["symbol"]: s for s in d.get("stocks", [])}, d.get("regime", {}) or {}


def _ema(x: np.ndarray, n: int) -> np.ndarray:
    return pd.Series(x).ewm(span=n, adjust=False).mean().to_numpy()


def _intel_note(rec: Optional[dict]) -> Optional[str]:
    if not rec:
        return None
    r = rec.get("recommendations", {}) or {}
    s = r.get("short", {}) or {}
    m = r.get("medium", {}) or {}
    score = s.get("score")
    flag = " ★ ưu tiên (≥80)" if isinstance(score, (int, float)) and score >= 80 else ""
    return (f"Stock Intelligence: ngắn hạn {s.get('rating', '?')} {score if score is not None else '?'}/100"
            f" · trung hạn {m.get('rating', '?')}{flag}")


def _weekly(df: pd.DataFrame) -> Tuple[Optional[dict], Optional[str]]:
    """Tuần T2–T6 đã đóng (W-FRI). Tuần hiện tại chỉ tính khi đã có phiên thứ 6 sau 15:00."""
    w = resample_ohlc(df.rename(columns={"time": "date"}), "W-FRI")
    last_session = _expected_last_session()
    w = w[w["week_end"] <= pd.Timestamp(last_session)]
    if len(w) and pd.Timestamp(last_session).weekday() != 4 and w["week_end"].iloc[-1] >= pd.Timestamp(last_session):
        w = w.iloc[:-1]
    if len(w) == 0:
        return None, None
    return (weekly_trend(w["high"].to_numpy(), w["low"].to_numpy(), w["close"].to_numpy()),
            pd.Timestamp(w["week_end"].iloc[-1]).strftime("%Y-%m-%d"))


def scan_symbol(sym: str, df: pd.DataFrame, rec: Optional[dict], regime: str,
                min_value_bn: float, tape: Optional[dict] = None) -> Tuple[List[Signal], Optional[str]]:
    """Trả về (tín hiệu, lý do bỏ qua)."""
    if len(df) < 80:
        return [], "thiếu dữ liệu"
    hi, lo, cl = (df[c].to_numpy(float) for c in ("high", "low", "close"))
    vol = df["volume"].to_numpy(float)
    value_bn = float(np.mean(cl[-20:] * 1000 * vol[-20:]) / 1e9)
    if value_bn < min_value_bn:
        return [], f"GTGD {value_bn:.1f} tỷ < {min_value_bn:g}"
    bar = pd.Timestamp(df["time"].iloc[-1]).strftime("%Y-%m-%d")
    e20, e50 = _ema(cl, 20), _ema(cl, 50)
    notes = [
        f"GTGD TB20 {value_bn:,.0f} tỷ · EMA20{'>' if e20[-1] > e50[-1] else '<'}EMA50"
        f" · thị trường {regime or '?'}",
        "T+2: mua hôm nay, sớm nhất bán chiều T+2",
    ]
    note_i = _intel_note(rec)
    if note_i:
        notes.append(note_i)
    note_t = tape_note(tape) if tape else None
    if note_t:
        notes.append(note_t)

    out: List[Signal] = []
    r = macd_rsi_signal(hi, lo, cl)
    if r.signal == MACDRSISignalType.LONG:
        out.append(Signal(
            asset="vn", symbol=sym, tf="1D", side="long", strategy="macd_rsi_atr",
            rule=f"MACD hist cắt lên 0 + RSI {r.rsi:.0f} < 70; SL 1,5×ATR, TP 2,5×ATR",
            bar_time=bar, entry=float(cl[-1]), stop=r.stop_loss, target=r.take_profit,
            max_hold="tới khi hist MACD cắt xuống 0 hoặc chạm SL/TP", evidence=EVIDENCE["macd_rsi_atr"],
            notes=list(notes) + [sizing_note(float(cl[-1]), r.stop_loss)], unit="nghìn đ",
        ))

    p = MacdSignedParams(allow_short=False)
    idea = macd_signed_signal(hi, lo, cl, p)
    prev = macd_signed_signal(hi[:-1], lo[:-1], cl[:-1], p)
    fresh = idea is not None and (prev is None or (prev.setup, prev.side) != (idea.setup, idea.side))
    if idea is not None and idea.side == "long" and fresh:
        out.append(Signal(
            asset="vn", symbol=sym, tf="1D", side="long", strategy="macd_signed",
            rule=f"{idea.tier} · {idea.setup} · {idea.reason} · vùng mua {idea.entry_low:,.2f}–{idea.entry_high:,.2f}",
            bar_time=bar, entry=float(idea.entry), stop=float(idea.stop_loss), target=float(idea.take_profit),
            max_hold="tới khi hist MACD đảo chiều hoặc chạm SL/TP", evidence=EVIDENCE["macd_signed"],
            notes=list(notes) + [sizing_note(float(idea.entry), float(idea.stop_loss))], unit="nghìn đ",
        ))
    return out, None


def weekly_block(week_end: str, idx_rows: List[Tuple[str, Optional[dict]]],
                 stock_trends: Dict[str, Optional[dict]], rec_by: Dict[str, dict],
                 ledger_stats: Optional[dict] = None) -> str:
    up = sorted(s for s, t in stock_trends.items() if t and t["bias"] == "Tăng")
    dn = sorted(s for s, t in stock_trends.items() if t and t["bias"] == "Giảm")
    mid = sorted(s for s, t in stock_trends.items() if t and t["bias"] == "Trung tính")
    strong = sorted(
        (s for s in up if (stock_trends[s] or {}).get("chg_4w_pct") is not None),
        key=lambda s: stock_trends[s]["chg_4w_pct"], reverse=True,
    )[:10]
    lines = [f"📅 <b>Cổ phiếu VN — xu hướng tuần kết thúc {h(week_end)}</b>", ""]
    for name, t in idx_rows:
        chg = f" · 4 tuần {t['chg_4w_pct']:+.1f}%" if t and t.get("chg_4w_pct") is not None else ""
        lines.append(f"<b>{h(name)}</b>: {h(trend_line(t))}{h(chg)}")
    lines += [
        "",
        f"Độ rộng tuần ({len(stock_trends)} mã): Tăng {len(up)} · Trung tính {len(mid)} · Giảm {len(dn)}",
        f"<b>Mạnh nhất 4 tuần (xu hướng tăng):</b> "
        + h(", ".join(f"{s} {stock_trends[s]['chg_4w_pct']:+.0f}%" for s in strong) or "—"),
        f"<b>Tăng:</b> {h(', '.join(up) or '—')}",
        f"<b>Giảm:</b> {h(', '.join(dn) or '—')}",
        "",
        "<i>Xu hướng tuần = bộ lọc bối cảnh cho lệnh 1D (ưu tiên MUA mã đang Tăng), chưa backtest như tín hiệu riêng.</i>",
    ]
    if ledger_stats and ledger_stats.get("closed"):
        lines.append(f"Sổ lệnh giấy: {ledger_stats['closed']} lệnh đã đóng · win {ledger_stats['win'] * 100:.0f}% · "
                     f"TB {ledger_stats['avg_ret'] * 100:+.2f}%/lệnh · {ledger_stats['avg_r']:+.2f}R · "
                     f"đang mở {ledger_stats['open']}")
    elif ledger_stats:
        lines.append(f"Sổ lệnh giấy: chưa có lệnh đóng · đang chờ/mở {ledger_stats.get('open', 0)}")
    return "\n".join(lines)


def watch_block(date: str, items: List[Tuple[str, dict]], live_cfg: dict) -> str:
    lines = [f"👀 <b>Theo dõi — chưa đạt kiểm chứng</b> {h(date)}"]
    for sym, it in items:
        lines.append(f"• <b>{h(sym)}</b> {h(LIVE.NAMES.get(it['setup'], it['setup']))}: {h(it['note'])}")
    ev = {it["setup"] for _, it in items}
    for s in sorted(ev):
        e = LIVE.evidence(s, live_cfg)
        if e:
            lines.append(f"<i>{h(LIVE.NAMES.get(s, s))} — {h(e)}</i>")
    lines.append("<i>Không có mức giá vào lệnh và không vào sổ lệnh vì backtest ngoài mẫu chưa đạt ngưỡng.</i>")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbols", help="mặc định: 100 mã của Stock Intelligence")
    ap.add_argument("--min-value-bn", type=float, default=10.0, help="GTGD TB 20 phiên tối thiểu (tỷ đồng)")
    ap.add_argument("--wait-min", type=float, default=25.0, help="chờ quét Stock Intelligence hôm nay xong")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-dedupe", action="store_true")
    ap.add_argument("--heartbeat", action="store_true")
    ap.add_argument("--weekly-only", action="store_true")
    ap.add_argument("--daily-only", action="store_true")
    ap.add_argument("--no-tape", action="store_true", help="không thu thập mua/bán chủ động")
    ap.add_argument("--tape", action="store_true", help="thu thập cả khi --dry-run (gọi API thật)")
    args = ap.parse_args()

    from vn_stock.notify.telegram import send_message

    print(f"=== VN swing {now_vn():%Y-%m-%d %H:%M} VN ===")
    print("  " + wait_for_intel(args.wait_min if not args.dry_run else min(args.wait_min, 0.0)))
    rec_by, regime = _intel_index()
    symbols = ([s.strip().upper() for s in args.symbols.split(",") if s.strip()] if args.symbols
               else sorted(rec_by) or sorted(p.stem for p in ADJ.glob("*.csv") if p.stem not in INDICES))
    expected = _expected_last_session()
    store = SentStore(STORE)
    seen = (lambda k: False) if args.no_dedupe else (lambda k: k in store)
    live_cfg = LIVE.load_live_config()
    ledger = Ledger(LEDGER_PATH)

    if not args.weekly_only and not args.no_tape and (not args.dry_run or args.tape):
        try:
            TAPE.collect(symbols, expected)
        except Exception as e:  # noqa: BLE001 — thiếu tape không chặn tín hiệu
            print(f"  tape lỗi: {e}")
    tape_daily = TAPE.load_daily()
    tape_cov = int((tape_daily["date"] == expected).sum()) if len(tape_daily) else 0

    blocks: List[str] = []
    keys: List[str] = []
    stock_trends: Dict[str, Optional[dict]] = {}
    week_end: Optional[str] = None
    signals: List[Signal] = []
    watch_items: List[Tuple[str, dict]] = []
    exit_blocks: List[Tuple[str, str]] = []
    data_by: Dict[str, pd.DataFrame] = {}
    stale, skipped = [], 0
    active_syms = {p["symbol"] for p in ledger.active()}

    for sym in symbols:
        df = _load(sym)
        if df is None:
            stale.append(sym)
            continue
        last = pd.Timestamp(df["time"].iloc[-1]).strftime("%Y-%m-%d")
        t, we = _weekly(df)
        stock_trends[sym] = t
        week_end = max(filter(None, [week_end, we]), default=None)
        if last < expected:
            stale.append(sym)
            continue
        if args.weekly_only:
            continue
        data_by[sym] = df
        if sym in active_syms:
            for rec in ledger.process(sym, df, LIVE.flag_arrays(df)):
                exit_blocks.append((f"EXIT|{rec['id']}", format_exit(rec)))
        tf = tape_features(tape_daily, sym, expected) if len(tape_daily) else None
        sigs, why = scan_symbol(sym, df, rec_by.get(sym), regime.get("regime", ""), args.min_value_bn, tf)
        if why:
            skipped += 1
        else:
            ship, watch = LIVE.scan_setups(sym, df, live_cfg)
            watch_items += [(sym, w) for w in watch]
            for it in ship:
                ep = LIVE.exit_params(it["setup"], live_cfg)
                sigs.append(Signal(
                    asset="vn", symbol=sym, tf="1D", side="long", strategy=it["setup"], rule=it["note"],
                    bar_time=pd.Timestamp(df["time"].iloc[-1]).strftime("%Y-%m-%d"), entry=it["close"],
                    stop=it["stop"], target=it["target"],
                    max_hold=f"{ep.time_stop} phiên" + (" · trailing" if ep.mode == "B" else ""),
                    evidence=LIVE.evidence(it["setup"], live_cfg),
                    notes=[n for n in [tape_note(tf) if tf else None, sizing_note(it["close"], it["stop"]),
                                       "T+2: mua hôm nay, sớm nhất bán chiều T+2"] if n],
                    unit="nghìn đ"))
                sigs[-1]._base_low = it.get("base_low")
        for s in sigs:
            tp = f"{s.target:.2f}" if s.target is not None else "trailing"
            print(f"  SIGNAL {s.strategy} {sym} {s.bar_time} entry={s.entry:.2f} SL={s.stop:.2f} TP={tp}")
            signals.append(s)
    print(f"  {len(symbols)} mã · dữ liệu cũ {len(stale)} · lọc thanh khoản {skipped} · tín hiệu {len(signals)}"
          f" · phiên mong đợi {expected}")

    # vị thế đang mở của mã không được quét (vd dữ liệu cũ) vẫn cần tính lại
    for sym in sorted(active_syms - set(data_by)):
        df = _load(sym)
        if df is not None and not args.weekly_only:
            for rec in ledger.process(sym, df, LIVE.flag_arrays(df)):
                exit_blocks.append((f"EXIT|{rec['id']}", format_exit(rec)))

    for k, b in exit_blocks:            # BÁN trước
        if not seen(k):
            blocks.append(b)
            keys.append(k)

    for s in signals:
        if seen(s.key):
            continue
        ep = STRATEGY_EXITS.get(s.strategy) or LIVE.exit_params(s.strategy, live_cfg)
        pid = ledger.add(s.symbol, s.strategy, s.bar_time, s.entry, s.stop, s.target, ep,
                         getattr(s, "_base_low", None)) if ep else None
        if pid is None and ep:
            s.notes.append("Sổ lệnh giấy đã đủ 5 vị thế (hoặc đã có) — lệnh này không được theo dõi để báo BÁN")
        blocks.append(format_signal(s, stock_trends.get(s.symbol)))
        keys.append(s.key)

    if watch_items and not seen(f"WATCH|vn|{expected}"):
        blocks.append(watch_block(expected, watch_items, live_cfg))
        keys.append(f"WATCH|vn|{expected}")

    if not args.weekly_only and tape_cov and not seen(f"TAPE|{expected}"):
        tb, ts = daily_leaders(tape_daily, expected)
        cov = f"Dữ liệu {tape_cov}/{len(symbols)} mã" + (" — thiếu, tham khảo thận trọng" if tape_cov < 0.8 * len(symbols) else "")
        msg = format_leaders(expected, tb, ts, cov)
        if msg:
            blocks.append(msg)
            keys.append(f"TAPE|{expected}")

    if not args.daily_only and week_end and not seen(f"WEEKLY|vn|{week_end}"):
        idx_rows = []
        for name in INDICES:
            d = _load(name)
            idx_rows.append((name, _weekly(d)[0] if d is not None else None))
        blocks.append(weekly_block(week_end, idx_rows, stock_trends, rec_by, ledger.stats()))
        keys.append(f"WEEKLY|vn|{week_end}")

    if not args.weekly_only and not signals and args.heartbeat and not seen(f"HEARTBEAT|vn|{expected}"):
        blocks.append(f"📭 Cổ phiếu VN 1D {h(expected)}: không có tín hiệu MUA "
                      f"({len(symbols) - len(stale)} mã có dữ liệu, thị trường {h(regime.get('regime', '?'))}).")
        keys.append(f"HEARTBEAT|vn|{expected}")
    if stale and len(stale) > len(symbols) / 2 and not args.weekly_only:
        blocks.append(f"⚠️ {len(stale)}/{len(symbols)} mã chưa có phiên {h(expected)} — "
                      "Stock Intelligence chưa cập nhật? Tín hiệu có thể thiếu.")

    if not blocks:
        print("Không có gì mới để gửi.")
        return 0
    ok = deliver(split_messages(blocks), send_message, args.dry_run)
    if ok and not args.dry_run:
        for k in keys:
            store.add(k)
        store.save()
        ledger.save()
    print(f"{'DRY ' if args.dry_run else ''}blocks={len(blocks)} ok={ok}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
