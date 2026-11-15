"""
Phân kỳ MACD/RSI (bọc strategies/div_macd_rsi.precompute_div_signals; pivot 5/5 → tín hiệu biết sau 5 nến,
không nhìn trước).

- Phân kỳ dương (bull) → setup MUA. trigger="immediate": vào mở cửa t+1;
  trigger="confirm": chờ close > đỉnh 5 phiên trong ≤ 5 phiên sau tín hiệu.
  SL = đáy pivot − 0,5·ATR; bỏ nếu rủi ro ngoài [risk_min, risk_max].
- Phân kỳ âm (bear) → chỉ dùng làm tín hiệu thoát (không bán khống).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Dict

import numpy as np
import pandas as pd

from vn_stock.setups.features import add_common
from vn_stock.strategies.div_macd_rsi import DivMacdRsiParams, precompute_div_signals


@dataclass(frozen=True)
class DivSetupParams:
    pivot: int = 5
    trigger: str = "immediate"  # immediate | confirm
    confirm_bars: int = 5
    require_sma200: bool = True
    sl_atr: float = 0.5
    risk_min: float = 0.015
    risk_max: float = 0.10
    min_value_bn: float = 10.0
    warmup: int = 260

    def to_dict(self) -> Dict:
        return asdict(self)


def detect(df: pd.DataFrame, p: DivSetupParams = DivSetupParams(), feats: pd.DataFrame = None) -> pd.DataFrame:
    d = feats if feats is not None else add_common(df)
    hi, lo, cl = (d[c].to_numpy(float) for c in ("high", "low", "close"))
    dp = DivMacdRsiParams(pivot_left=p.pivot, pivot_right=p.pivot)
    bull_m, bull_r, bear_m, bear_r, _ = precompute_div_signals(hi, lo, cl, dp)
    n = len(cl)
    bull = pd.Series(bull_m | bull_r, index=d.index)
    bear = pd.Series(bear_m | bear_r, index=d.index)
    # đáy pivot (nến t − pivot) — đã biết tại t
    pivot_low = d["low"].shift(p.pivot)
    stop = pivot_low - p.sl_atr * d["atr14"]

    if p.trigger == "confirm":
        hi5 = d["high"].rolling(5, min_periods=5).max().shift(1)
        trig = np.zeros(n, dtype=bool)
        stop_t = np.full(n, np.nan)
        b = bull.to_numpy()
        for i in np.where(b)[0]:
            for j in range(i + 1, min(n, i + 1 + p.confirm_bars)):
                if cl[j] > hi5.iloc[j]:
                    trig[j] = True
                    stop_t[j] = stop.iloc[i]
                    break
        entry_sig = pd.Series(trig, index=d.index)
        stop = pd.Series(np.where(trig, stop_t, np.nan), index=d.index)
    else:
        entry_sig = bull.copy()

    if p.require_sma200:
        entry_sig &= (d["close"] > d["sma200"]).fillna(False)
    entry_sig &= (d["value_avg20_bn"] >= p.min_value_bn).fillna(False)
    risk = (d["close"] - stop) / d["close"]
    entry_sig &= ((risk >= p.risk_min) & (risk <= p.risk_max)).fillna(False)
    entry_sig.iloc[: min(p.warmup, n)] = False
    return pd.DataFrame({"bull_div": bull, "bear_div": bear, "entry": entry_sig, "stop": stop, "risk": risk,
                         "rvol50": d["rvol50"], "atr14": d["atr14"]}, index=d.index)
