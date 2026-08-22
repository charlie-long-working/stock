"""
Ichimoku Cloud strategy for Vietnamese stocks (Long only).

Default entry (classic TK cross + cloud filter):
  LONG  – Tenkan crosses above Kijun
          AND close above cloud (max(Senkou A, Senkou B))
          AND cloud bullish (Senkou A >= Senkou B) when require_bull_cloud=True
  EXIT  – Tenkan crosses below Kijun, or ATR SL/TP
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple

import numpy as np


class IchimokuSignalType(Enum):
    LONG = "long"
    EXIT = "exit"
    NEUTRAL = "neutral"


@dataclass
class IchimokuParams:
    tenkan_period: int = 9
    kijun_period: int = 26
    senkou_b_period: int = 52
    displacement: int = 26
    atr_period: int = 14
    atr_sl_mult: float = 1.5
    atr_tp_mult: float = 2.5
    require_above_cloud: bool = True
    require_bull_cloud: bool = True
    require_chikou: bool = False


@dataclass
class IchimokuResult:
    signal: IchimokuSignalType
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    tenkan: float = 0.0
    kijun: float = 0.0
    senkou_a: float = 0.0
    senkou_b: float = 0.0
    reason: str = ""


def _midpoint(high: np.ndarray, low: np.ndarray, period: int) -> np.ndarray:
    n = len(high)
    out = np.full(n, np.nan)
    for i in range(period - 1, n):
        out[i] = (np.max(high[i - period + 1 : i + 1]) + np.min(low[i - period + 1 : i + 1])) / 2.0
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


def compute_ichimoku(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    params: Optional[IchimokuParams] = None,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Returns tenkan, kijun, senkou_a, senkou_b, atr.
    Senkou lines are shifted forward by `displacement` (leading span as plotted).
    """
    if params is None:
        params = IchimokuParams()

    tenkan = _midpoint(high, low, params.tenkan_period)
    kijun = _midpoint(high, low, params.kijun_period)
    span_a_raw = (tenkan + kijun) / 2.0
    span_b_raw = _midpoint(high, low, params.senkou_b_period)

    n = len(close)
    d = params.displacement
    senkou_a = np.full(n, np.nan)
    senkou_b = np.full(n, np.nan)
    if d < n:
        senkou_a[d:] = span_a_raw[: n - d]
        senkou_b[d:] = span_b_raw[: n - d]

    atr = _atr(high, low, close, params.atr_period)
    return tenkan, kijun, senkou_a, senkou_b, atr


def precompute_ichimoku(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    params: Optional[IchimokuParams] = None,
):
    return compute_ichimoku(high, low, close, params)


def _long_filters_ok(
    i: int,
    close: np.ndarray,
    senkou_a: np.ndarray,
    senkou_b: np.ndarray,
    params: IchimokuParams,
) -> bool:
    sa, sb = senkou_a[i], senkou_b[i]
    if np.isnan(sa) or np.isnan(sb):
        return False
    cloud_top = max(sa, sb)
    cloud_bot = min(sa, sb)
    if params.require_above_cloud and close[i] <= cloud_top:
        return False
    if params.require_bull_cloud and sa < sb:
        return False
    if params.require_chikou:
        d = params.displacement
        if i < d or close[i] <= close[i - d]:
            return False
    return True


def ichimoku_signal(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    params: Optional[IchimokuParams] = None,
) -> IchimokuResult:
    if params is None:
        params = IchimokuParams()

    lookback = params.senkou_b_period + params.displacement + 2
    if len(close) < lookback:
        return IchimokuResult(signal=IchimokuSignalType.NEUTRAL, reason="insufficient_data")

    tenkan, kijun, senkou_a, senkou_b, atr = compute_ichimoku(high, low, close, params)
    i = len(close) - 1
    t0, t1 = tenkan[i - 1], tenkan[i]
    k0, k1 = kijun[i - 1], kijun[i]
    if any(np.isnan(x) for x in (t0, t1, k0, k1)):
        return IchimokuResult(signal=IchimokuSignalType.NEUTRAL, reason="nan_lines")

    sa, sb = float(senkou_a[i]), float(senkou_b[i])
    base = IchimokuResult(
        signal=IchimokuSignalType.NEUTRAL,
        tenkan=float(t1),
        kijun=float(k1),
        senkou_a=sa if not np.isnan(sa) else 0.0,
        senkou_b=sb if not np.isnan(sb) else 0.0,
    )

    if t0 <= k0 and t1 > k1 and _long_filters_ok(i, close, senkou_a, senkou_b, params):
        cur_atr = atr[i]
        return IchimokuResult(
            signal=IchimokuSignalType.LONG,
            stop_loss=close[i] - params.atr_sl_mult * cur_atr,
            take_profit=close[i] + params.atr_tp_mult * cur_atr,
            tenkan=float(t1),
            kijun=float(k1),
            senkou_a=base.senkou_a,
            senkou_b=base.senkou_b,
            reason="tk_cross_up_above_cloud",
        )

    if t0 >= k0 and t1 < k1:
        return IchimokuResult(
            signal=IchimokuSignalType.EXIT,
            tenkan=float(t1),
            kijun=float(k1),
            senkou_a=base.senkou_a,
            senkou_b=base.senkou_b,
            reason="tk_cross_down",
        )

    base.reason = "no_signal"
    return base
