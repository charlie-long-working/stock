"""
Backtest engine for Vietnamese stocks: walk OHLCV bars, apply strategy, simulate Long-only positions.

Supports strategies: regime_fusion, macd_rsi, ma_crossover, div_macd_rsi, ichimoku.
"""

from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import numpy as np

from vn_stock.data_loaders.vn_ohlcv import load_ohlcv_arrays
from vn_stock.strategies.macd_rsi import (
    MACDRSIParams,
    MACDRSISignalType,
    precompute_macd_rsi,
)
from vn_stock.strategies.ma_crossover import (
    MACrossParams,
    MACrossSignalType,
    precompute_ma_cross,
)
from vn_stock.strategies.div_macd_rsi import DivMacdRsiParams, precompute_div_signals
from vn_stock.strategies.ichimoku import IchimokuParams, precompute_ichimoku


@dataclass
class Trade:
    entry_bar: int
    exit_bar: int
    entry_price: float
    exit_price: float
    pnl_pct: float
    exit_reason: str
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None


@dataclass
class BacktestResult:
    symbol: str
    strategy: str
    interval: str
    start_bar: int
    end_bar: int
    trades: List[Trade] = field(default_factory=list)
    equity_curve: Optional[np.ndarray] = None
    total_return_pct: float = 0.0
    hold_return_pct: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown_pct: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    num_trades: int = 0
    avg_win_pct: float = 0.0
    avg_loss_pct: float = 0.0


def _parse_date_to_ts_ms(date_str: Optional[str]) -> Optional[int]:
    if not date_str:
        return None
    try:
        dt = datetime.strptime(date_str.strip()[:10], "%Y-%m-%d")
        return int(dt.replace(tzinfo=None).timestamp() * 1000)
    except Exception:
        return None


def _compute_metrics(
    trades: List[Trade],
    equity: float,
    equity_curve: np.ndarray,
    i_start: int,
    i_end: int,
    close: np.ndarray,
    symbol: str,
    strategy: str,
    interval: str,
) -> BacktestResult:
    total_return_pct = (equity - 1.0) * 100
    hold_return_pct = float((close[i_end] / close[i_start] - 1.0) * 100) if close[i_start] != 0 else 0.0

    if not trades:
        return BacktestResult(
            symbol=symbol, strategy=strategy, interval=interval,
            start_bar=i_start, end_bar=i_end, trades=[], equity_curve=equity_curve,
            total_return_pct=total_return_pct, hold_return_pct=hold_return_pct, num_trades=0,
        )

    returns = np.array([t.pnl_pct for t in trades])
    wins = returns[returns > 0]
    losses = returns[returns < 0]
    win_rate = len(wins) / len(trades) * 100 if trades else 0
    gross_profit = float(np.sum(wins)) if len(wins) else 0
    gross_loss = abs(float(np.sum(losses))) if len(losses) else 1e-12
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0
    avg_win_pct = float(np.mean(wins)) if len(wins) else 0.0
    avg_loss_pct = float(np.mean(losses)) if len(losses) else 0.0

    sharpe_ratio = 0.0
    if len(returns) > 1 and np.std(returns) > 0:
        sharpe_ratio = float(np.mean(returns) / np.std(returns) * np.sqrt(252))

    curve_slice = equity_curve[i_start: i_end + 1]
    peak = np.maximum.accumulate(curve_slice)
    dd = (peak - curve_slice) / np.where(peak > 0, peak, 1)
    max_drawdown_pct = float(np.max(dd) * 100) if len(dd) else 0

    return BacktestResult(
        symbol=symbol, strategy=strategy, interval=interval,
        start_bar=i_start, end_bar=i_end, trades=trades, equity_curve=equity_curve,
        total_return_pct=total_return_pct, hold_return_pct=hold_return_pct,
        sharpe_ratio=sharpe_ratio, max_drawdown_pct=max_drawdown_pct,
        win_rate=win_rate, profit_factor=profit_factor, num_trades=len(trades),
        avg_win_pct=avg_win_pct, avg_loss_pct=avg_loss_pct,
    )


def _get_bar_range(open_time, n, lookback, start_date, end_date):
    ot = np.asarray(open_time, dtype=np.int64)
    if ot.size and ot[0] < 1e12:
        ot = ot * 1000
    start_ts = _parse_date_to_ts_ms(start_date)
    end_ts = _parse_date_to_ts_ms(end_date)
    i_start = lookback
    i_end = n - 1
    if start_ts is not None:
        idx = int(np.searchsorted(ot, start_ts, side="left"))
        i_start = max(lookback, min(idx, n - 1))
    if end_ts is not None:
        idx = int(np.searchsorted(ot, end_ts, side="right"))
        i_end = min(idx - 1, n - 1)
    return i_start, i_end


def _exit_position(position, bar_idx, high_val, low_val, close_val):
    """Check if position should be exited via SL/TP. Returns (exit_price, reason) or (None, None)."""
    if low_val <= position["stop"]:
        return position["stop"], "stop"
    if position["target"] is not None and high_val >= position["target"]:
        return position["target"], "target"
    return None, None


def run_backtest(
    symbol: str,
    strategy: str = "macd_rsi",
    interval: str = "1D",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    params: dict = None,
    data_root: Optional[Path] = None,
) -> Optional[BacktestResult]:
    """
    Run backtest for a VN stock symbol.

    strategy: 'macd_rsi', 'ma_crossover', 'regime_fusion', 'div_macd_rsi', 'ichimoku'
      div_macd_rsi: long/short tại div, TP/SL % (mặc định +5%/-2.5%), đóng thêm theo tín hiệu đối nghịch (tùy DivMacdRsiParams).
      ichimoku: TK cross up above cloud, ATR SL/TP (long-only).
    data_root: sector bundle root (reads OHLCV from data_root/ohlcv/).
    """
    data = load_ohlcv_arrays(symbol, interval, data_root=data_root)
    if data is None:
        return None
    open_time, open_, high, low, close, volume = data
    n = len(close)

    if strategy == "macd_rsi":
        return _backtest_macd_rsi(open_time, open_, high, low, close, volume, n,
                                   symbol, interval, start_date, end_date, params)
    elif strategy == "ma_crossover":
        return _backtest_ma_crossover(open_time, open_, high, low, close, volume, n,
                                      symbol, interval, start_date, end_date, params)
    elif strategy == "div_macd_rsi":
        return _backtest_div_macd_rsi(open_time, open_, high, low, close, volume, n,
                                      symbol, interval, start_date, end_date, params)
    elif strategy == "ichimoku":
        return _backtest_ichimoku(open_time, open_, high, low, close, volume, n,
                                  symbol, interval, start_date, end_date, params)
    elif strategy == "regime_fusion":
        return _backtest_regime_fusion(open_time, open_, high, low, close, volume, n,
                                       symbol, interval, start_date, end_date)
    else:
        raise ValueError(f"Unknown strategy: {strategy}")


def _backtest_macd_rsi(open_time, open_, high, low, close, volume, n,
                        symbol, interval, start_date, end_date, params_dict):
    p = MACDRSIParams(**(params_dict or {}))
    lookback = p.slow_period + p.signal_period + 2
    if n < lookback:
        return None

    histogram, rsi_arr, atr_arr = precompute_macd_rsi(high, low, close, p)
    i_start, i_end = _get_bar_range(open_time, n, lookback, start_date, end_date)
    if i_start > i_end:
        return None

    trades: List[Trade] = []
    equity = 1.0
    equity_curve = np.ones(n)
    position = None

    for i in range(i_start, i_end + 1):
        if position is not None:
            exit_price, exit_reason = _exit_position(position, i, high[i], low[i], close[i])
            if exit_price is not None:
                pnl = (exit_price - position["entry_price"]) / position["entry_price"] * 100
                trades.append(Trade(
                    entry_bar=position["entry_bar"], exit_bar=i,
                    entry_price=position["entry_price"], exit_price=exit_price,
                    pnl_pct=pnl, exit_reason=exit_reason,
                    stop_loss=position["stop"], take_profit=position["target"],
                ))
                equity *= 1 + pnl / 100
                position = None

        if position is None and i >= 1:
            cur_hist = histogram[i]
            prev_hist = histogram[i - 1]
            cur_rsi = rsi_arr[i]
            cur_atr = atr_arr[i]

            if prev_hist <= 0 < cur_hist and cur_rsi < p.rsi_overbought:
                position = {
                    "entry_price": close[i],
                    "entry_bar": i,
                    "stop": close[i] - p.atr_sl_mult * cur_atr,
                    "target": close[i] + p.atr_tp_mult * cur_atr,
                }

        equity_curve[i] = equity

    if position is not None:
        pnl = (close[i_end] - position["entry_price"]) / position["entry_price"] * 100
        trades.append(Trade(
            entry_bar=position["entry_bar"], exit_bar=i_end,
            entry_price=position["entry_price"], exit_price=close[i_end],
            pnl_pct=pnl, exit_reason="end",
            stop_loss=position.get("stop"), take_profit=position.get("target"),
        ))
        equity *= 1 + pnl / 100
        equity_curve[i_end] = equity

    return _compute_metrics(trades, equity, equity_curve, i_start, i_end, close,
                            symbol, "macd_rsi", interval)


def _backtest_ichimoku(open_time, open_, high, low, close, volume, n,
                       symbol, interval, start_date, end_date, params_dict):
    p = IchimokuParams(**(params_dict or {}))
    lookback = p.senkou_b_period + p.displacement + 2
    if n < lookback:
        return None

    tenkan, kijun, senkou_a, senkou_b, atr_arr = precompute_ichimoku(high, low, close, p)
    i_start, i_end = _get_bar_range(open_time, n, lookback, start_date, end_date)
    if i_start > i_end:
        return None

    trades: List[Trade] = []
    equity = 1.0
    equity_curve = np.ones(n)
    position = None

    for i in range(i_start, i_end + 1):
        if position is not None:
            exit_price, exit_reason = _exit_position(position, i, high[i], low[i], close[i])
            if exit_price is None and i >= 1:
                t0, t1 = tenkan[i - 1], tenkan[i]
                k0, k1 = kijun[i - 1], kijun[i]
                if (not np.isnan(t0) and not np.isnan(t1) and not np.isnan(k0) and not np.isnan(k1)
                        and t0 >= k0 and t1 < k1):
                    exit_price, exit_reason = close[i], "tk_cross_down"

            if exit_price is not None:
                pnl = (exit_price - position["entry_price"]) / position["entry_price"] * 100
                trades.append(Trade(
                    entry_bar=position["entry_bar"], exit_bar=i,
                    entry_price=position["entry_price"], exit_price=exit_price,
                    pnl_pct=pnl, exit_reason=exit_reason,
                    stop_loss=position["stop"], take_profit=position["target"],
                ))
                equity *= 1 + pnl / 100
                position = None

        if position is None and i >= 1:
            t0, t1 = tenkan[i - 1], tenkan[i]
            k0, k1 = kijun[i - 1], kijun[i]
            sa, sb = senkou_a[i], senkou_b[i]
            if any(np.isnan(x) for x in (t0, t1, k0, k1, sa, sb)):
                equity_curve[i] = equity
                continue

            cross_up = t0 <= k0 and t1 > k1
            above_cloud = (not p.require_above_cloud) or close[i] > max(sa, sb)
            bull_cloud = (not p.require_bull_cloud) or sa >= sb
            chikou_ok = True
            if p.require_chikou:
                d = p.displacement
                chikou_ok = i >= d and close[i] > close[i - d]

            if cross_up and above_cloud and bull_cloud and chikou_ok:
                cur_atr = atr_arr[i]
                position = {
                    "entry_price": close[i],
                    "entry_bar": i,
                    "stop": close[i] - p.atr_sl_mult * cur_atr,
                    "target": close[i] + p.atr_tp_mult * cur_atr,
                }

        equity_curve[i] = equity

    if position is not None:
        pnl = (close[i_end] - position["entry_price"]) / position["entry_price"] * 100
        trades.append(Trade(
            entry_bar=position["entry_bar"], exit_bar=i_end,
            entry_price=position["entry_price"], exit_price=close[i_end],
            pnl_pct=pnl, exit_reason="end",
            stop_loss=position.get("stop"), take_profit=position.get("target"),
        ))
        equity *= 1 + pnl / 100
        equity_curve[i_end] = equity

    return _compute_metrics(trades, equity, equity_curve, i_start, i_end, close,
                            symbol, "ichimoku", interval)


def _backtest_div_macd_rsi(open_time, open_, high, low, close, volume, n,
                            symbol, interval, start_date, end_date, params_dict):
    p = DivMacdRsiParams()
    if params_dict:
        kw = {k: v for k, v in params_dict.items() if k in DivMacdRsiParams.__dataclass_fields__}
        p = replace(p, **kw)

    lookback = max(
        p.ma200_period + 5,
        p.macd_slow + p.macd_signal + 5,
        p.rsi_period + 5,
        p.vol_period * 2 + 5,
        p.short_ma,
        p.long_ma,
        p.pivot_left + p.pivot_right + 5,
    )
    if n < lookback:
        return None

    bull_macd, bull_rsi, bear_macd, bear_rsi, neutral_mode = precompute_div_signals(
        high, low, close, p
    )
    i_start, i_end = _get_bar_range(open_time, n, lookback, start_date, end_date)
    if i_start > i_end:
        return None

    trades: List[Trade] = []
    equity = 1.0
    equity_curve = np.ones(n)
    position = None
    tp = p.take_profit_pct
    sl = p.stop_loss_pct

    for i in range(i_start, i_end + 1):
        bear = (p.sell_macd and bear_macd[i]) or (p.sell_rsi and bear_rsi[i])
        bull = ((p.buy_macd and bull_macd[i]) or (p.buy_rsi and bull_rsi[i])) and (
            not p.require_neutral or neutral_mode[i]
        )
        short_ok = bear and (not p.require_neutral or neutral_mode[i]) and p.use_short

        if position is not None:
            entry = position["entry_price"]
            eb = position["entry_bar"]
            matured = i > eb
            exit_price = None
            exit_reason = None

            if position["side"] == "long":
                if matured and close[i] <= entry * (1.0 - sl / 100.0):
                    exit_price, exit_reason = close[i], "sl_long"
                elif matured and close[i] >= entry * (1.0 + tp / 100.0):
                    exit_price, exit_reason = close[i], "tp_long"
                elif p.exit_long_on_bear and bear:
                    exit_price, exit_reason = close[i], "bear"

                if exit_price is not None:
                    pnl = (exit_price - entry) / entry * 100
                    trades.append(Trade(
                        entry_bar=eb, exit_bar=i,
                        entry_price=entry, exit_price=exit_price,
                        pnl_pct=pnl, exit_reason=exit_reason,
                    ))
                    equity *= 1.0 + pnl / 100.0
                    position = None

            else:
                if matured and close[i] >= entry * (1.0 + sl / 100.0):
                    exit_price, exit_reason = close[i], "sl_short"
                elif matured and close[i] <= entry * (1.0 - tp / 100.0):
                    exit_price, exit_reason = close[i], "tp_short"
                elif p.cover_short_on_bull and bull:
                    exit_price, exit_reason = close[i], "bull"

                if exit_price is not None:
                    pnl = (entry - exit_price) / entry * 100
                    trades.append(Trade(
                        entry_bar=eb, exit_bar=i,
                        entry_price=entry, exit_price=exit_price,
                        pnl_pct=pnl, exit_reason=exit_reason,
                    ))
                    equity *= 1.0 + pnl / 100.0
                    position = None

        if position is None:
            if bull:
                position = {"side": "long", "entry_price": close[i], "entry_bar": i}
            elif short_ok:
                position = {"side": "short", "entry_price": close[i], "entry_bar": i}

        equity_curve[i] = equity

    if position is not None:
        entry = position["entry_price"]
        eb = position["entry_bar"]
        ex = close[i_end]
        if position["side"] == "long":
            pnl = (ex - entry) / entry * 100
        else:
            pnl = (entry - ex) / entry * 100
        trades.append(Trade(
            entry_bar=eb, exit_bar=i_end,
            entry_price=entry, exit_price=ex,
            pnl_pct=pnl, exit_reason="end",
        ))
        equity *= 1.0 + pnl / 100.0
        equity_curve[i_end] = equity

    return _compute_metrics(trades, equity, equity_curve, i_start, i_end, close,
                            symbol, "div_macd_rsi", interval)


def _backtest_ma_crossover(open_time, open_, high, low, close, volume, n,
                            symbol, interval, start_date, end_date, params_dict):
    p = MACrossParams(**(params_dict or {}))
    lookback = p.slow_period + 2
    if n < lookback:
        return None

    fast_ma, slow_ma, atr_arr, vol_sma = precompute_ma_cross(high, low, close, volume, p)
    i_start, i_end = _get_bar_range(open_time, n, lookback, start_date, end_date)
    if i_start > i_end:
        return None

    trades: List[Trade] = []
    equity = 1.0
    equity_curve = np.ones(n)
    position = None

    for i in range(i_start, i_end + 1):
        if position is not None:
            exit_price, exit_reason = _exit_position(position, i, high[i], low[i], close[i])
            if exit_price is None:
                if i >= 1 and not np.isnan(fast_ma[i]) and not np.isnan(slow_ma[i]):
                    if fast_ma[i - 1] >= slow_ma[i - 1] and fast_ma[i] < slow_ma[i]:
                        exit_price = close[i]
                        exit_reason = "signal"

            if exit_price is not None:
                pnl = (exit_price - position["entry_price"]) / position["entry_price"] * 100
                trades.append(Trade(
                    entry_bar=position["entry_bar"], exit_bar=i,
                    entry_price=position["entry_price"], exit_price=exit_price,
                    pnl_pct=pnl, exit_reason=exit_reason,
                    stop_loss=position["stop"], take_profit=position["target"],
                ))
                equity *= 1 + pnl / 100
                position = None

        if position is None and i >= 1:
            cur_fast = fast_ma[i]
            prev_fast = fast_ma[i - 1]
            cur_slow = slow_ma[i]
            prev_slow = slow_ma[i - 1]

            if (not np.isnan(cur_fast) and not np.isnan(cur_slow) and
                    not np.isnan(prev_fast) and not np.isnan(prev_slow)):
                cross_up = prev_fast <= prev_slow and cur_fast > cur_slow
                price_above = close[i] > cur_slow
                vol_ok = True
                if vol_sma is not None and not np.isnan(vol_sma[i]):
                    vol_ok = volume[i] > vol_sma[i]

                if cross_up and price_above and vol_ok:
                    cur_atr = atr_arr[i]
                    position = {
                        "entry_price": close[i],
                        "entry_bar": i,
                        "stop": close[i] - p.atr_sl_mult * cur_atr,
                        "target": close[i] + p.atr_tp_mult * cur_atr,
                    }

        equity_curve[i] = equity

    if position is not None:
        pnl = (close[i_end] - position["entry_price"]) / position["entry_price"] * 100
        trades.append(Trade(
            entry_bar=position["entry_bar"], exit_bar=i_end,
            entry_price=position["entry_price"], exit_price=close[i_end],
            pnl_pct=pnl, exit_reason="end",
            stop_loss=position.get("stop"), take_profit=position.get("target"),
        ))
        equity *= 1 + pnl / 100
        equity_curve[i_end] = equity

    return _compute_metrics(trades, equity, equity_curve, i_start, i_end, close,
                            symbol, "ma_crossover", interval)


def _backtest_regime_fusion(open_time, open_, high, low, close, volume, n,
                             symbol, interval, start_date, end_date):
    from vn_stock.strategies.regime import RegimeClassifier, RegimeInputs
    from vn_stock.strategies.rules import get_rules_for_regime
    from vn_stock.strategies.technical import (
        order_blocks, fair_value_gaps, supply_demand_zones,
        price_at_ob, price_at_fvg, price_at_zone, OBType,
    )
    from vn_stock.strategies.volume import volume_confirmation
    from vn_stock.strategies.fusion import get_signal, Signal

    lookback = 50
    if n < lookback:
        return None

    i_start, i_end = _get_bar_range(open_time, n, lookback, start_date, end_date)
    if i_start > i_end:
        return None

    classifier = RegimeClassifier()
    trades: List[Trade] = []
    equity = 1.0
    equity_curve = np.ones(n)
    position = None

    for i in range(i_start, i_end + 1):
        o = open_[:i + 1]
        h = high[:i + 1]
        l_ = low[:i + 1]
        c = close[:i + 1]
        v = volume[:i + 1]

        if position is not None:
            exit_price, exit_reason = _exit_position(position, i, high[i], low[i], close[i])
            if exit_price is not None:
                pnl = (exit_price - position["entry_price"]) / position["entry_price"] * 100
                trades.append(Trade(
                    entry_bar=position["entry_bar"], exit_bar=i,
                    entry_price=position["entry_price"], exit_price=exit_price,
                    pnl_pct=pnl, exit_reason=exit_reason,
                    stop_loss=position["stop"], take_profit=position["target"],
                ))
                equity *= 1 + pnl / 100
                position = None

        if position is None:
            res = get_signal(
                o, h, l_, c, v,
                regime_classifier=classifier,
                require_volume_confirmation=False,
                ob_lookback=min(50, i),
                fvg_lookback=min(30, i),
                zone_lookback=min(50, i),
            )
            if res.signal == Signal.LONG:
                rules = get_rules_for_regime(res.regime)
                stop_pct = rules.stop_pct or 0.02
                tp_pct = rules.take_profit_pct
                stop = res.stop_below if res.stop_below is not None else close[i] * (1 - stop_pct)
                target = close[i] * (1 + tp_pct) if tp_pct is not None else None
                position = {
                    "entry_price": close[i],
                    "entry_bar": i,
                    "stop": stop,
                    "target": target,
                }

        equity_curve[i] = equity

    if position is not None:
        pnl = (close[i_end] - position["entry_price"]) / position["entry_price"] * 100
        trades.append(Trade(
            entry_bar=position["entry_bar"], exit_bar=i_end,
            entry_price=position["entry_price"], exit_price=close[i_end],
            pnl_pct=pnl, exit_reason="end",
            stop_loss=position.get("stop"), take_profit=position.get("target"),
        ))
        equity *= 1 + pnl / 100
        equity_curve[i_end] = equity

    return _compute_metrics(trades, equity, equity_curve, i_start, i_end, close,
                            symbol, "regime_fusion", interval)
