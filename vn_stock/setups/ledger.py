"""
Sổ lệnh giấy cho các tín hiệu MUA bot đã gửi → tín hiệu BÁN (thoát) bằng đúng engine của backtest.

- Mỗi vị thế lưu mức giá TƯƠNG ĐỐI so với giá đóng cửa ngày tín hiệu (stop_pct, target_pct, base_low_pct):
  kho giá điều chỉnh cổ tức có thể đổi giá quá khứ, nhưng tỷ lệ không đổi.
- Mỗi lần chạy, vị thế được tính lại TỪ ĐẦU trên dữ liệu hiện có (idempotent): vào lệnh mở cửa phiên sau tín hiệu
  (bỏ nếu mở cửa ≥ close × 1,06 hoặc ≤ SL), rồi `exits.step` từng phiên (T+2, SL/TP/trailing/cấu trúc).
- Tối đa MAX_POSITIONS vị thế đang chờ/mở. Không lưu số vốn hay dữ liệu cá nhân.
- File: data/screening/swing_vn_ledger.json (gitignored).
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional

import numpy as np
import pandas as pd

from vn_stock import DATA_DIR
from vn_stock.setups.exits import ExitParams, Position, init_target, step
from vn_stock.setups.sizing import MAX_POSITIONS

LEDGER = DATA_DIR / "screening" / "swing_vn_ledger.json"
COSTS = {"fee_buy": 0.0015, "fee_sell": 0.0015, "tax_sell": 0.001}
CHASE_MAX = 1.06
REASON_VI = {"SL": "chạm cắt lỗ", "TP": "chạm chốt lời", "trail": "trailing stop", "breakeven": "về hoà vốn",
             "breakdown": "gãy nền", "bear_div": "phân kỳ âm", "signal": "MACD hist cắt xuống 0",
             "time": "hết thời gian giữ"}

# Thoát cho các chiến lược đang chạy (setup mới lấy từ setups/config.json)
STRATEGY_EXITS = {
    "macd_rsi_atr": ExitParams(mode="A", tp_r=2.5 / 1.5, time_stop=60, use_breakdown=False, use_signal_exit=True),
    "macd_signed": ExitParams(mode="A", time_stop=30, use_breakdown=False, use_signal_exit=True),
}


def _net(entry: float, exit_px: float) -> float:
    return exit_px * (1 - COSTS["fee_sell"] - COSTS["tax_sell"]) / (entry * (1 + COSTS["fee_buy"])) - 1


class Ledger:
    def __init__(self, path: Path = LEDGER):
        self.path = Path(path)
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
            self.positions: List[Dict] = d.get("positions", [])
        except (OSError, ValueError):
            self.positions = []

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"version": 1, "updated_at": datetime.now().isoformat(timespec="seconds"),
                                   "positions": self.positions}, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    def active(self) -> List[Dict]:
        return [p for p in self.positions if p["status"] in ("pending", "open")]

    def has(self, pid: str) -> bool:
        return any(p["id"] == pid for p in self.positions)

    def add(self, symbol: str, strategy: str, signal_date: str, close_ref: float, stop: float,
            target: Optional[float], exit_params: ExitParams, base_low: Optional[float] = None) -> Optional[str]:
        """Thêm vị thế chờ vào lệnh. None nếu đã đủ MAX_POSITIONS hoặc đã có."""
        pid = f"{symbol}|{signal_date}|{strategy}"
        if self.has(pid) or len(self.active()) >= MAX_POSITIONS or not close_ref or stop is None:
            return None
        self.positions.append({
            "id": pid, "symbol": symbol, "strategy": strategy, "signal_date": signal_date, "status": "pending",
            "stop_pct": stop / close_ref, "target_pct": (target / close_ref) if target else None,
            "base_low_pct": (base_low / close_ref) if base_low else None, "exit": exit_params.to_dict(),
            "created_at": datetime.now().isoformat(timespec="seconds"),
        })
        return pid

    def process(self, symbol: str, df: pd.DataFrame, flags: Dict[str, np.ndarray]) -> List[Dict]:
        """Tính lại các vị thế của `symbol`; trả các vị thế VỪA chuyển sang đóng/huỷ trong lần này."""
        changed = []
        for rec in self.positions:
            if rec["symbol"] != symbol or rec["status"] in ("closed", "cancelled"):
                continue
            before = rec["status"]
            replay(rec, df, flags)
            if rec["status"] != before and rec["status"] in ("closed", "cancelled"):
                changed.append(rec)
        return changed

    def stats(self) -> Dict:
        closed = [p for p in self.positions if p["status"] == "closed"]
        if not closed:
            return {"closed": 0, "open": len(self.active())}
        r = np.array([p["ret"] for p in closed])
        return {"closed": len(closed), "open": len(self.active()), "win": float((r > 0).mean()),
                "avg_ret": float(r.mean()), "avg_r": float(np.mean([p.get("r_mult", 0) for p in closed]))}


def replay(rec: Dict, df: pd.DataFrame, flags: Dict[str, np.ndarray]) -> Dict:
    """Tính trạng thái vị thế từ đầu trên df (time, open, high, low, close). Ghi kết quả vào rec."""
    times = pd.to_datetime(df["time"]).dt.strftime("%Y-%m-%d").to_numpy()
    hit = np.nonzero(times == rec["signal_date"])[0]
    if len(hit) == 0:
        return rec
    s = int(hit[0])
    if s + 1 >= len(df):
        rec["status"] = "pending"
        return rec
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    close_ref = c[s]
    entry_px = o[s + 1]
    stop = close_ref * rec["stop_pct"]
    rec["entry_date"] = times[s + 1]
    if entry_px >= close_ref * CHASE_MAX:
        rec.update(status="cancelled", reason="mở cửa tăng ≥ 6% so với giá tín hiệu (không đuổi giá)")
        return rec
    if stop >= entry_px:
        rec.update(status="cancelled", reason="giá mở cửa đã dưới mức cắt lỗ")
        return rec
    ep = ExitParams(**rec["exit"])
    tr = pd.concat([df["high"] - df["low"], (df["high"] - df["close"].shift()).abs(),
                    (df["low"] - df["close"].shift()).abs()], axis=1).max(axis=1)
    atr = float(tr.iloc[max(0, s - 13): s + 1].mean())
    pos = Position(rec["symbol"], rec["strategy"], s + 1, float(entry_px), float(stop), atr,
                   target=close_ref * rec["target_pct"] if rec.get("target_pct") else None)
    init_target(pos, ep)
    base_low = close_ref * rec["base_low_pct"] if rec.get("base_low_pct") else None
    rec.update(entry_px=round(float(entry_px), 4), stop=round(float(stop), 4),
               target=None if pos.target is None else round(float(pos.target), 4))
    for i in range(s + 1, len(df)):
        fl = {"breakdown": bool(base_low is not None and c[i] < base_low * 0.995),
              "bear_div": bool(flags.get("bear_div", np.zeros(len(df), bool))[i]),
              "signal_exit": bool(flags.get("signal_exit", np.zeros(len(df), bool))[i])}
        ev = step(pos, i, o[i], h[i], l[i], c[i], ep, fl)
        if ev:
            rec.update(status="closed", exit_date=times[i], exit_px=round(float(ev.px), 4), exit_reason=ev.reason,
                       ret=_net(entry_px, ev.px), r_mult=(ev.px - entry_px) / pos.r, bars=i - s)
            return rec
    rec.update(status="open", last_bar=times[-1], bars=len(df) - 1 - s, mark_ret=_net(entry_px, c[-1]),
               current_stop=round(float(pos.stop), 4))
    return rec


def format_exit(rec: Dict) -> str:
    import html

    e = html.escape
    if rec["status"] == "cancelled":
        return (f"⚪️ <b>HUỶ</b> {e(rec['symbol'])} · <code>{e(rec['strategy'])}</code> — tín hiệu {e(rec['signal_date'])}"
                f" không vào lệnh: {e(rec.get('reason', ''))}")
    reason = REASON_VI.get(rec["exit_reason"], rec["exit_reason"])
    return "\n".join([
        f"🔴 <b>BÁN / THOÁT</b> {e(rec['symbol'])} · <code>{e(rec['strategy'])}</code>",
        f"Mua {e(rec['entry_date'])} @ <code>{rec['entry_px']:,.2f}</code> → bán {e(rec['exit_date'])} @ "
        f"<code>{rec['exit_px']:,.2f}</code> nghìn đ",
        f"Lý do: {e(reason)} · giữ {rec['bars']} phiên",
        f"Kết quả sổ giấy (sau phí/thuế): <b>{rec['ret'] * 100:+.2f}%</b> · {rec['r_mult']:+.2f}R",
        "<i>Thoát theo sổ lệnh giấy của bot (T+2). Không phải lời khuyên đầu tư.</i>",
    ])
