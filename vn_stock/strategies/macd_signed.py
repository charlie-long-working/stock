"""
MACD dương / âm + vào–thoát động (không TP/SL % cố định).

MACD+ (hist > 0): long — cross lên 0, hoặc tiếp diễn khi hist dương hồi rồi tăng lại.
MACD− (hist < 0): short — cross xuống 0, hoặc tiếp diễn khi hist âm nảy rồi giảm lại.
Tier2: đảo chiều sớm (hist âm đang lên / hist dương đang xuống) kèm RSI.

Điểm vào: close tín hiệu, vùng kéo về EMA nhanh / swing gần nhất.
Điểm thoát: SL dưới (trên) swing + đệm ATR; TP = R-multiple theo độ rộng SL,
            hoặc swing đối diện nếu nằm trong khoảng R hợp lý. Thoát thêm khi hist đảo dấu.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np

from vn_stock.strategies.macd_rsi import _atr, _ema, _rsi
from vn_stock.strategies.technical import swing_highs, swing_lows


@dataclass
class MacdSignedParams:
    fast_period: int = 12
    slow_period: int = 26
    signal_period: int = 9
    rsi_period: int = 14
    rsi_overbought: float = 70.0
    rsi_oversold: float = 30.0
    atr_period: int = 14
    swing_left: int = 2
    swing_right: int = 2
    swing_lookback: int = 40
    sl_swing_buffer_atr: float = 0.25
    min_sl_atr: float = 0.7
    max_sl_atr: float = 2.8
    rr_multiple: float = 2.0
    use_ema_filter: bool = True
    ema_trend_fast: int = 20
    ema_trend_slow: int = 50
    allow_short: bool = True
    allow_reversal: bool = True


@dataclass
class MacdSignedIdea:
    side: str
    regime: str  # macd_pos | macd_neg
    setup: str  # cross | continuation | reversal
    tier: str
    entry: float
    entry_low: float
    entry_high: float
    stop_loss: float
    take_profit: float
    risk: float
    rr: float
    rsi: float
    hist: float
    reason: str


def precompute_macd_signed(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    params: Optional[MacdSignedParams] = None,
):
    p = params or MacdSignedParams()
    cl = np.asarray(close, dtype=np.float64)
    hi = np.asarray(high, dtype=np.float64)
    lo = np.asarray(low, dtype=np.float64)
    ema_f = _ema(cl, p.fast_period)
    ema_s = _ema(cl, p.slow_period)
    macd_line = ema_f - ema_s
    signal_line = _ema(macd_line, p.signal_period)
    hist = macd_line - signal_line
    rsi = _rsi(cl, p.rsi_period)
    atr = _atr(hi, lo, cl, p.atr_period)
    ema_tf = _ema(cl, p.ema_trend_fast)
    ema_ts = _ema(cl, p.ema_trend_slow)
    sh_idx = swing_highs(hi, p.swing_left, p.swing_right)
    sl_idx = swing_lows(lo, p.swing_left, p.swing_right)
    return hist, rsi, atr, ema_f, ema_tf, ema_ts, sh_idx, sl_idx


def _last_swing(
    idxs: np.ndarray,
    values: np.ndarray,
    i: int,
    lookback: int,
    fallback: float,
) -> float:
    if idxs.size == 0:
        return float(fallback)
    lo_i = max(0, i - lookback)
    prev = idxs[(idxs < i) & (idxs >= lo_i)]
    if prev.size == 0:
        prev = idxs[idxs < i]
    if prev.size == 0:
        return float(fallback)
    return float(values[int(prev[-1])])


def _clamp_sl(entry: float, raw_sl: float, atr: float, side: str, p: MacdSignedParams) -> float:
    atr = max(float(atr), 1e-9)
    if side == "long":
        risk = entry - raw_sl
        if risk < p.min_sl_atr * atr:
            return entry - p.min_sl_atr * atr
        if risk > p.max_sl_atr * atr:
            return entry - p.max_sl_atr * atr
        return raw_sl
    risk = raw_sl - entry
    if risk < p.min_sl_atr * atr:
        return entry + p.min_sl_atr * atr
    if risk > p.max_sl_atr * atr:
        return entry + p.max_sl_atr * atr
    return raw_sl


def _dynamic_levels(
    side: str,
    close: float,
    ema_fast: float,
    atr: float,
    swing_hi: float,
    swing_lo: float,
    p: MacdSignedParams,
) -> Tuple[float, float, float, float, float, float]:
    """entry, zone_low, zone_high, sl, tp, risk."""
    atr = max(float(atr), 1e-9)
    if side == "long":
        zone_low = min(close, ema_fast, swing_lo + 0.15 * atr)
        zone_high = close
        entry = close
        raw_sl = swing_lo - p.sl_swing_buffer_atr * atr
        sl = _clamp_sl(entry, raw_sl, atr, "long", p)
        risk = max(entry - sl, atr * p.min_sl_atr)
        tp = entry + p.rr_multiple * risk
        swing_r = (swing_hi - entry) / risk if risk > 0 else 0.0
        if 1.15 <= swing_r <= 2.8:
            tp = swing_hi
        return entry, min(zone_low, entry), zone_high, sl, tp, risk

    zone_high = max(close, ema_fast, swing_hi - 0.15 * atr)
    zone_low = close
    entry = close
    raw_sl = swing_hi + p.sl_swing_buffer_atr * atr
    sl = _clamp_sl(entry, raw_sl, atr, "short", p)
    risk = max(sl - entry, atr * p.min_sl_atr)
    tp = entry - p.rr_multiple * risk
    swing_r = (entry - swing_lo) / risk if risk > 0 else 0.0
    if 1.15 <= swing_r <= 2.8:
        tp = swing_lo
    return entry, zone_low, max(zone_high, entry), sl, tp, risk


def _build_idea(
    side: str,
    regime: str,
    setup: str,
    tier: str,
    close: float,
    ema_fast: float,
    atr: float,
    swing_hi: float,
    swing_lo: float,
    rsi: float,
    hist: float,
    reason: str,
    p: MacdSignedParams,
) -> MacdSignedIdea:
    entry, zlo, zhi, sl, tp, risk = _dynamic_levels(
        side, close, ema_fast, atr, swing_hi, swing_lo, p
    )
    rr = abs(tp - entry) / risk if risk > 0 else p.rr_multiple
    return MacdSignedIdea(
        side=side,
        regime=regime,
        setup=setup,
        tier=tier,
        entry=float(entry),
        entry_low=float(zlo),
        entry_high=float(zhi),
        stop_loss=float(sl),
        take_profit=float(tp),
        risk=float(risk),
        rr=float(rr),
        rsi=float(rsi),
        hist=float(hist),
        reason=reason,
    )


def idea_at(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    i: int,
    arrays=None,
    params: Optional[MacdSignedParams] = None,
) -> Optional[MacdSignedIdea]:
    p = params or MacdSignedParams()
    if arrays is None:
        arrays = precompute_macd_signed(high, low, close, p)
    hist, rsi, atr, ema_f, ema_tf, ema_ts, sh_idx, sl_idx = arrays
    if i < 2 or i >= len(close):
        return None

    hi = np.asarray(high, dtype=np.float64)
    lo = np.asarray(low, dtype=np.float64)
    cl = np.asarray(close, dtype=np.float64)
    cur_h, prev_h = hist[i], hist[i - 1]
    prev2_h = hist[i - 2]
    cur_rsi = rsi[i]
    cur_atr = atr[i]
    cur_c = float(cl[i])
    bull = ema_tf[i] > ema_ts[i] and cur_c > ema_ts[i]
    bear = ema_tf[i] < ema_ts[i] and cur_c < ema_ts[i]
    swing_hi = _last_swing(sh_idx, hi, i, p.swing_lookback, float(np.max(hi[max(0, i - 20) : i + 1])))
    swing_lo = _last_swing(sl_idx, lo, i, p.swing_lookback, float(np.min(lo[max(0, i - 20) : i + 1])))

    # --- MACD+ long: hist cắt lên 0 ---
    if prev_h <= 0 < cur_h and cur_rsi < p.rsi_overbought and (not p.use_ema_filter or bull):
        return _build_idea(
            "long", "macd_pos", "cross", "tier1",
            cur_c, ema_f[i], cur_atr, swing_hi, swing_lo, cur_rsi, cur_h,
            "MACD+ cross lên 0 · vào động (swing/ATR) · thoát hist đảo hoặc TP cấu trúc",
            p,
        )

    # --- MACD− short: hist cắt xuống 0 ---
    if (
        p.allow_short
        and prev_h >= 0 > cur_h
        and cur_rsi > p.rsi_oversold
        and (not p.use_ema_filter or bear)
    ):
        return _build_idea(
            "short", "macd_neg", "cross", "tier1",
            cur_c, ema_f[i], cur_atr, swing_hi, swing_lo, cur_rsi, cur_h,
            "MACD− cross xuống 0 · vào động (swing/ATR) · thoát hist đảo hoặc TP cấu trúc",
            p,
        )

    # --- Tiếp diễn MACD+ (hist dương, đáy hist rồi tăng lại) ---
    if (
        cur_h > 0
        and prev_h > 0
        and prev_h <= prev2_h
        and cur_h > prev_h
        and cur_rsi < p.rsi_overbought
        and (not p.use_ema_filter or bull)
    ):
        return _build_idea(
            "long", "macd_pos", "continuation", "tier1",
            cur_c, ema_f[i], cur_atr, swing_hi, swing_lo, cur_rsi, cur_h,
            "MACD+ tiếp diễn · hist dương hồi rồi tăng · SL swing + ATR",
            p,
        )

    # --- Tiếp diễn MACD− ---
    if (
        p.allow_short
        and cur_h < 0
        and prev_h < 0
        and prev_h >= prev2_h
        and cur_h < prev_h
        and cur_rsi > p.rsi_oversold
        and (not p.use_ema_filter or bear)
    ):
        return _build_idea(
            "short", "macd_neg", "continuation", "tier1",
            cur_c, ema_f[i], cur_atr, swing_hi, swing_lo, cur_rsi, cur_h,
            "MACD− tiếp diễn · hist âm nảy rồi giảm · SL swing + ATR",
            p,
        )

    if not p.allow_reversal:
        return None

    # --- Tier2 đảo chiều sớm trong MACD− (mua hồi) ---
    if (
        cur_h < 0
        and cur_h > prev_h
        and p.rsi_oversold <= cur_rsi <= 48
        and (not p.use_ema_filter or bull)
    ):
        return _build_idea(
            "long", "macd_neg", "reversal", "tier2",
            cur_c, ema_f[i], cur_atr, swing_hi, swing_lo, cur_rsi, cur_h,
            "MACD− đang dương hóa · RSI kéo · chờ cross 0 · SL/TP động",
            p,
        )

    # --- Tier2 đảo chiều sớm trong MACD+ (bán hồi) ---
    if (
        p.allow_short
        and cur_h > 0
        and cur_h < prev_h
        and 52 <= cur_rsi <= p.rsi_overbought
        and (not p.use_ema_filter or bear)
    ):
        return _build_idea(
            "short", "macd_pos", "reversal", "tier2",
            cur_c, ema_f[i], cur_atr, swing_hi, swing_lo, cur_rsi, cur_h,
            "MACD+ đang yếu · RSI cao · chờ cross 0 xuống · SL/TP động",
            p,
        )

    return None


def macd_signed_signal(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    params: Optional[MacdSignedParams] = None,
) -> Optional[MacdSignedIdea]:
    """Tín hiệu trên nến cuối."""
    n = len(close)
    if n < 60:
        return None
    p = params or MacdSignedParams()
    arrays = precompute_macd_signed(high, low, close, p)
    return idea_at(high, low, close, n - 1, arrays=arrays, params=p)


def hist_flip_exit(hist: np.ndarray, i: int, side: str) -> bool:
    """Thoát động khi histogram đảo dấu so với hướng lệnh."""
    if i < 1:
        return False
    if side == "long":
        return hist[i - 1] >= 0 > hist[i]
    return hist[i - 1] <= 0 < hist[i]


def scan_macd_signed(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    params: Optional[MacdSignedParams] = None,
) -> List[MacdSignedIdea]:
    idea = macd_signed_signal(high, low, close, params)
    return [idea] if idea else []
