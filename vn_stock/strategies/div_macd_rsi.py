"""
MACD/RSI pivot divergence — khớp Pine strategy MA200 Neutral + Div.

Long tại bull div; short tại bear div (tùy use_short).
Thoát: TP/SL % trên giá vào (mặc định +5% / −2.5% long; short đối xứng),
thêm đóng long khi bear / cover short khi bull (tùy exit_long_on_bear, cover_short_on_bull).
TP/SL chỉ xét từ nến sau nến vào (trùng Pine bar_index > entry_bar).
"""

from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np

from vn_stock.strategies.macd_rsi import _ema, _rsi


@dataclass
class DivMacdRsiParams:
    # Divergence / MACD / RSI
    pivot_left: int = 5
    pivot_right: int = 5
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    rsi_period: int = 14
    buy_macd: bool = True
    buy_rsi: bool = True
    sell_macd: bool = True
    sell_rsi: bool = True
    require_neutral: bool = False
    # TP/SL % on entry price; short uses same magnitudes (TP = giá giảm tp_pct, SL = giá tăng sl_pct)
    take_profit_pct: float = 5.0
    stop_loss_pct: float = 2.5
    use_short: bool = True
    exit_long_on_bear: bool = True
    cover_short_on_bull: bool = True
    # Neutral index (Pine)
    ma200_period: int = 200
    short_ma: int = 20
    long_ma: int = 50
    vol_period: int = 20
    max_spread_pct: float = 1.0
    max_vol_ratio: float = 0.8
    min_vol_ratio: float = 0.2
    use_ma200_filter: bool = True
    max_ma200_dist_pct: float = 10.0
    neutral_threshold: float = 70.0


def _sma(a: np.ndarray, period: int) -> np.ndarray:
    n = len(a)
    out = np.full(n, np.nan)
    if period <= 0 or n < period:
        return out
    c = np.cumsum(a, dtype=np.float64)
    out[period - 1] = c[period - 1] / period
    for i in range(period, n):
        out[i] = (c[i] - c[i - period]) / period
    return out


def _rolling_stdev_ddof1(a: np.ndarray, period: int) -> np.ndarray:
    """Sample stdev (ddof=1), khớp Pine ta.stdev (unbiased)."""
    n = len(a)
    out = np.full(n, np.nan)
    for i in range(period - 1, n):
        w = a[i - period + 1 : i + 1]
        out[i] = float(np.std(w, ddof=1)) if period > 1 else 0.0
    return out


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _pivot_low_confirmed(low: np.ndarray, i: int, left: int, right: int) -> bool:
    p = i - right
    if p < left or p + right >= len(low):
        return False
    v = low[p]
    for k in range(1, left + 1):
        if v >= low[p - k]:
            return False
    for k in range(1, right + 1):
        if v >= low[p + k]:
            return False
    return True


def _pivot_high_confirmed(high: np.ndarray, i: int, left: int, right: int) -> bool:
    p = i - right
    if p < left or p + right >= len(high):
        return False
    v = high[p]
    for k in range(1, left + 1):
        if v <= high[p - k]:
            return False
    for k in range(1, right + 1):
        if v <= high[p + k]:
            return False
    return True


def _macd_line(close: np.ndarray, fast: int, slow: int, signal: int) -> np.ndarray:
    ema_f = _ema(close, fast)
    ema_s = _ema(close, slow)
    line = ema_f - ema_s
    _ = _ema(line, signal)
    return line


def precompute_div_signals(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    params: Optional[DivMacdRsiParams] = None,
) -> Tuple[
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
]:
    """
    Trả về (bull_macd, bull_rsi, bear_macd, bear_rsi, neutral_mode) — boolean mỗi bar,
    tín hiệu tại đóng nến i (sau khi pivot được xác nhận).
    """
    p = params or DivMacdRsiParams()
    n = len(close)

    macd_line = _macd_line(close, p.macd_fast, p.macd_slow, p.macd_signal)
    rsi_arr = _rsi(close, p.rsi_period)

    short_ma = _sma(close, p.short_ma)
    long_ma = _sma(close, p.long_ma)
    spread_pct = np.full(n, np.nan)
    for i in range(n):
        if not np.isnan(long_ma[i]) and long_ma[i] != 0:
            spread_pct[i] = abs(short_ma[i] - long_ma[i]) / long_ma[i] * 100.0

    recent_std = _rolling_stdev_ddof1(close, p.vol_period)
    prev_std = np.full(n, np.nan)
    P = p.vol_period
    for i in range(n):
        if i - P >= P - 1:
            prev_std[i] = recent_std[i - P]

    vol_ratio = np.full(n, np.nan)
    for i in range(n):
        if not np.isnan(recent_std[i]) and not np.isnan(prev_std[i]) and prev_std[i] > 0:
            vol_ratio[i] = recent_std[i] / prev_std[i]

    vol_contracting = np.zeros(n, dtype=bool)
    for i in range(n):
        if not np.isnan(vol_ratio[i]) and vol_ratio[i] <= p.max_vol_ratio:
            vol_contracting[i] = True

    ma200 = _sma(close, p.ma200_period)
    ma200_dist_pct = np.full(n, np.nan)
    for i in range(n):
        if not np.isnan(ma200[i]) and ma200[i] != 0:
            ma200_dist_pct[i] = abs(close[i] - ma200[i]) / ma200[i] * 100.0

    trend_score = np.zeros(n)
    vol_score = np.zeros(n)
    ma200_score = np.zeros(n)
    for i in range(n):
        if not np.isnan(spread_pct[i]):
            trend_score[i] = _clamp(100.0 * (1.0 - spread_pct[i] / p.max_spread_pct), 0.0, 100.0)
        if not np.isnan(vol_ratio[i]):
            denom = max(p.max_vol_ratio - p.min_vol_ratio, 0.0001)
            vol_score[i] = _clamp(100.0 * (p.max_vol_ratio - vol_ratio[i]) / denom, 0.0, 100.0)
        if p.use_ma200_filter and not np.isnan(ma200_dist_pct[i]):
            ma200_score[i] = _clamp(
                100.0 * (1.0 - ma200_dist_pct[i] / p.max_ma200_dist_pct), 0.0, 100.0
            )
        else:
            ma200_score[i] = 50.0

    neutral_score = 0.45 * trend_score + 0.35 * vol_score + 0.20 * ma200_score
    neutral_mode = (neutral_score >= p.neutral_threshold) & vol_contracting

    bull_macd = np.zeros(n, dtype=bool)
    bull_rsi = np.zeros(n, dtype=bool)
    bear_macd = np.zeros(n, dtype=bool)
    bear_rsi = np.zeros(n, dtype=bool)

    prev_pl_price_macd = np.nan
    prev_pl_macd = np.nan
    prev_ph_price_macd = np.nan
    prev_ph_macd = np.nan
    prev_pl_price_rsi = np.nan
    prev_pl_rsi = np.nan
    prev_ph_price_rsi = np.nan
    prev_ph_rsi = np.nan

    L, R = p.pivot_left, p.pivot_right

    for i in range(n):
        if _pivot_low_confirmed(low, i, L, R):
            pivot_bar = i - R
            pl_price = low[pivot_bar]
            macd_at_pl = macd_line[pivot_bar]
            rsi_at_pl = rsi_arr[pivot_bar]

            if not np.isnan(prev_pl_price_macd) and pl_price < prev_pl_price_macd:
                if not np.isnan(macd_at_pl) and not np.isnan(prev_pl_macd) and macd_at_pl > prev_pl_macd:
                    bull_macd[i] = True
            prev_pl_price_macd = pl_price
            prev_pl_macd = macd_at_pl

            if not np.isnan(prev_pl_price_rsi) and pl_price < prev_pl_price_rsi:
                if not np.isnan(rsi_at_pl) and not np.isnan(prev_pl_rsi) and rsi_at_pl > prev_pl_rsi:
                    bull_rsi[i] = True
            prev_pl_price_rsi = pl_price
            prev_pl_rsi = rsi_at_pl

        if _pivot_high_confirmed(high, i, L, R):
            pivot_bar = i - R
            ph_price = high[pivot_bar]
            macd_at_ph = macd_line[pivot_bar]
            rsi_at_ph = rsi_arr[pivot_bar]

            if not np.isnan(prev_ph_price_macd) and ph_price > prev_ph_price_macd:
                if not np.isnan(macd_at_ph) and not np.isnan(prev_ph_macd) and macd_at_ph < prev_ph_macd:
                    bear_macd[i] = True
            prev_ph_price_macd = ph_price
            prev_ph_macd = macd_at_ph

            if not np.isnan(prev_ph_price_rsi) and ph_price > prev_ph_price_rsi:
                if not np.isnan(rsi_at_ph) and not np.isnan(prev_ph_rsi) and rsi_at_ph < prev_ph_rsi:
                    bear_rsi[i] = True
            prev_ph_price_rsi = ph_price
            prev_ph_rsi = rsi_at_ph

    return bull_macd, bull_rsi, bear_macd, bear_rsi, neutral_mode
