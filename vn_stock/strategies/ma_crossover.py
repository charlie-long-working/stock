"""
Moving Average Crossover strategy for Vietnamese stocks (Long only).

Signal logic:
  LONG  – Fast MA crosses above Slow MA  AND  price > Slow MA  AND  volume confirmation
  EXIT  – Fast MA crosses below Slow MA  OR  hit SL/TP (ATR-based)

Supports SMA and EMA.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional

import numpy as np


class MACrossSignalType(Enum):
    LONG = "long"
    EXIT = "exit"
    NEUTRAL = "neutral"


@dataclass
class MACrossParams:
    fast_period: int = 20
    slow_period: int = 50
    use_ema: bool = False
    atr_period: int = 14
    atr_sl_mult: float = 2.0
    atr_tp_mult: float = 3.0
    volume_confirm: bool = True
    volume_period: int = 20


@dataclass
class MACrossResult:
    signal: MACrossSignalType
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    fast_ma: float = 0.0
    slow_ma: float = 0.0
    reason: str = ""


def _sma(data: np.ndarray, period: int) -> np.ndarray:
    out = np.full_like(data, np.nan, dtype=np.float64)
    if len(data) < period:
        return out
    cumsum = np.cumsum(data)
    out[period - 1] = cumsum[period - 1] / period
    out[period:] = (cumsum[period:] - cumsum[:-period]) / period
    return out


def _ema(data: np.ndarray, period: int) -> np.ndarray:
    out = np.empty_like(data, dtype=np.float64)
    out[0] = data[0]
    alpha = 2.0 / (period + 1)
    for i in range(1, len(data)):
        out[i] = alpha * data[i] + (1 - alpha) * out[i - 1]
    return out


def _atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int) -> np.ndarray:
    n = len(close)
    tr = np.empty(n)
    tr[0] = high[0] - low[0]
    for i in range(1, n):
        tr[i] = max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))
    atr = np.empty(n)
    atr[:period] = np.mean(tr[:period])
    for i in range(period, n):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
    return atr


def ma_crossover_signal(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    volume: np.ndarray,
    params: Optional[MACrossParams] = None,
) -> MACrossResult:
    """
    Evaluate MA crossover at the latest bar. Long-only for VN stocks.
    """
    if params is None:
        params = MACrossParams()

    n = len(close)
    if n < params.slow_period + 2:
        return MACrossResult(signal=MACrossSignalType.NEUTRAL, reason="insufficient_data")

    ma_func = _ema if params.use_ema else _sma
    fast_ma = ma_func(close, params.fast_period)
    slow_ma = ma_func(close, params.slow_period)

    cur_fast = fast_ma[-1]
    prev_fast = fast_ma[-2]
    cur_slow = slow_ma[-1]
    prev_slow = slow_ma[-2]

    if np.isnan(cur_fast) or np.isnan(cur_slow) or np.isnan(prev_fast) or np.isnan(prev_slow):
        return MACrossResult(signal=MACrossSignalType.NEUTRAL, reason="ma_nan")

    atr_arr = _atr(high, low, close, params.atr_period)
    cur_atr = atr_arr[-1]
    cur_close = close[-1]

    vol_ok = True
    if params.volume_confirm and len(volume) >= params.volume_period:
        avg_vol = np.mean(volume[-params.volume_period:])
        vol_ok = volume[-1] > avg_vol

    cross_up = prev_fast <= prev_slow and cur_fast > cur_slow
    cross_down = prev_fast >= prev_slow and cur_fast < cur_slow

    if cross_up and cur_close > cur_slow and vol_ok:
        sl = cur_close - params.atr_sl_mult * cur_atr
        tp = cur_close + params.atr_tp_mult * cur_atr
        return MACrossResult(
            signal=MACrossSignalType.LONG,
            stop_loss=sl,
            take_profit=tp,
            fast_ma=float(cur_fast),
            slow_ma=float(cur_slow),
            reason=f"ma{params.fast_period}_cross_above_ma{params.slow_period}",
        )

    if cross_down:
        return MACrossResult(
            signal=MACrossSignalType.EXIT,
            fast_ma=float(cur_fast),
            slow_ma=float(cur_slow),
            reason=f"ma{params.fast_period}_cross_below_ma{params.slow_period}",
        )

    return MACrossResult(
        signal=MACrossSignalType.NEUTRAL,
        fast_ma=float(cur_fast),
        slow_ma=float(cur_slow),
        reason="no_cross",
    )


def precompute_ma_cross(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    volume: np.ndarray,
    params: Optional[MACrossParams] = None,
):
    """Precompute all indicator arrays for backtest efficiency."""
    if params is None:
        params = MACrossParams()
    ma_func = _ema if params.use_ema else _sma
    fast_ma = ma_func(close, params.fast_period)
    slow_ma = ma_func(close, params.slow_period)
    atr_arr = _atr(high, low, close, params.atr_period)
    vol_sma = _sma(volume, params.volume_period) if params.volume_confirm else None
    return fast_ma, slow_ma, atr_arr, vol_sma
