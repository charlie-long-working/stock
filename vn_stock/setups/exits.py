"""
Một engine thoát lệnh dùng chung cho backtest và sổ lệnh live (đảm bảo lệnh BÁN live = lệnh thoát của backtest).

Quy ước T+2 (VN): mua khớp mở cửa phiên e → cổ phiếu về chiều phiên e+2.
  - Phiên e, e+1: KHÔNG bán được. Điều kiện xảy ra lúc đó (chạm SL, tín hiệu cấu trúc) được giữ "chờ".
  - Phiên e+2 (bán được buổi chiều): chạm SL (trong phiên hoặc đang chờ) → khớp min(SL, close);
    tín hiệu chờ khác → khớp close; TP chỉ khớp nếu close ≥ TP (khớp close).
  - Từ e+3: SL/TP trong phiên (giá mở cửa nhảy qua → khớp open), SL ưu tiên khi cùng phiên.
  - Thoát theo cấu trúc (gãy nền, phân kỳ âm, hết thời gian, trailing theo close): biết lúc đóng cửa t →
    khớp mở cửa t+1 (nếu t+1 ≥ e+3) hoặc close e+2.
Mode A: SL cố định, TP = entry + tp_r·R, giữ tối đa time_stop phiên.
Mode B: không TP; lãi ≥ be_r·R (theo close) → dời SL về hoà vốn; trailing SL = close cao nhất − trail_atr·ATR;
        giữ tối đa time_stop phiên.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Dict, Optional


@dataclass(frozen=True)
class ExitParams:
    mode: str = "A"
    tp_r: float = 2.0
    time_stop: int = 20
    be_r: float = 1.0
    trail_atr: float = 3.0
    use_breakdown: bool = True
    use_bear_div: bool = False
    use_signal_exit: bool = False      # thoát theo tín hiệu của chính chiến lược (vd MACD hist cắt xuống 0)

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class Position:
    symbol: str
    setup: str
    entry_i: int
    entry_px: float
    stop: float
    atr: float
    target: Optional[float] = None
    bars_held: int = 0
    highest_close: float = 0.0
    pending: Optional[str] = None      # lý do thoát đang chờ (cấu trúc / thời gian / SL trong T+2)
    initial_stop: float = 0.0

    def __post_init__(self):
        if not self.initial_stop:
            self.initial_stop = self.stop
        if not self.highest_close:
            self.highest_close = self.entry_px

    @property
    def r(self) -> float:
        return max(self.entry_px - self.initial_stop, 1e-9)

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class ExitEvent:
    i: int
    px: float
    reason: str   # SL | TP | trail | breakeven | breakdown | bear_div | signal | time


def init_target(pos: Position, p: ExitParams) -> Position:
    if p.mode == "A" and pos.target is None:
        pos.target = pos.entry_px + p.tp_r * pos.r
    return pos


def step(pos: Position, i: int, o: float, h: float, l: float, c: float,
         p: ExitParams, flags: Optional[Dict[str, bool]] = None) -> Optional[ExitEvent]:
    """Xử lý nến i (i ≥ entry_i). Trả ExitEvent nếu thoát tại nến này."""
    flags = flags or {}
    k = i - pos.entry_i          # 0 = phiên mua
    stop_reason = "SL" if pos.stop <= pos.initial_stop else ("breakeven" if pos.stop <= pos.entry_px else "trail")

    if k < 2:
        if l <= pos.stop and pos.pending is None:
            pos.pending = stop_reason
        _structural(pos, c, p, flags, k)
        pos.bars_held = k + 1
        return None

    if k == 2:
        if pos.pending in ("SL", "breakeven", "trail") or l <= pos.stop:
            return ExitEvent(i, min(pos.stop, c), pos.pending if pos.pending in ("SL", "breakeven", "trail") else stop_reason)
        if pos.pending:
            return ExitEvent(i, c, pos.pending)
        if pos.target is not None and c >= pos.target:
            return ExitEvent(i, c, "TP")
    else:
        if pos.pending:
            return ExitEvent(i, o, pos.pending)
        if o <= pos.stop:
            return ExitEvent(i, o, stop_reason)
        if l <= pos.stop:
            return ExitEvent(i, pos.stop, stop_reason)
        if pos.target is not None:
            if o >= pos.target:
                return ExitEvent(i, o, "TP")
            if h >= pos.target:
                return ExitEvent(i, pos.target, "TP")

    _structural(pos, c, p, flags, k)
    pos.bars_held = k + 1
    return None


def _structural(pos: Position, c: float, p: ExitParams, flags: Dict[str, bool], k: int) -> None:
    """Cập nhật trailing/hoà vốn theo close và đặt lý do thoát chờ cho nến sau."""
    pos.highest_close = max(pos.highest_close, c)
    if p.mode == "B":
        if c >= pos.entry_px + p.be_r * pos.r:
            pos.stop = max(pos.stop, pos.entry_px)
        pos.stop = max(pos.stop, pos.highest_close - p.trail_atr * pos.atr)
    if pos.pending:
        return
    if p.use_breakdown and flags.get("breakdown"):
        pos.pending = "breakdown"
    elif p.use_bear_div and flags.get("bear_div"):
        pos.pending = "bear_div"
    elif p.use_signal_exit and flags.get("signal_exit"):
        pos.pending = "signal"
    elif k + 1 >= p.time_stop:
        pos.pending = "time"
