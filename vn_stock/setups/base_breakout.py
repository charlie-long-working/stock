"""
Nền giá đi ngang + phá nền (MUA) / gãy nền (thoát, tránh mua). Nhân quả:
nền xét trên cửa sổ W = [t−N, t−1] (đã đóng), phá nền xét tại đóng cửa t, vào lệnh mở cửa t+1.

Nền hợp lệ (thử N lớn → nhỏ, lấy N dài nhất hợp lệ):
  - biên độ (đỉnh/đáy − 1) ≤ max_height[N] và (đỉnh − đáy) ≤ height_atr_k·√N·ATR
  - không trôi: |close[t−1]/close[t−N] − 1| ≤ drift_frac · biên độ
  - co biến động: hạng BB-width 250 phiên ≤ bbw_rank_max
  - cạn volume: TB volume 10 phiên cuối nền / SMA50 volume ≤ dryup_max
  - (tuỳ chọn) xu hướng tăng: close > SMA200 và SMA50 > SMA200
Phá nền tại t: close ≥ đỉnh·(1+buffer), close ≤ đỉnh·(1+max_chase), rvol50 ≥ rvol_min, CLV ≥ clv_min,
GTGD phiên và TB20 ≥ min_value_bn, không có phá nền trong `fresh_bars` phiên trước.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Dict, Tuple

import numpy as np
import pandas as pd

from vn_stock.setups.features import add_common


@dataclass(frozen=True)
class BaseParams:
    windows: Tuple[int, ...] = (60, 40, 20)
    max_height: Tuple[Tuple[int, float], ...] = ((20, 0.12), (40, 0.15), (60, 0.18))
    height_atr_k: float = 1.2
    drift_frac: float = 0.5
    bbw_rank_max: float = 0.35
    dryup_max: float = 0.85
    require_uptrend: bool = True
    buffer: float = 0.005
    max_chase: float = 0.07
    rvol_min: float = 1.5
    clv_min: float = 0.6
    min_value_bn: float = 10.0
    fresh_bars: int = 5
    sl_atr: float = 1.0
    sl_floor: float = 0.92
    risk_min: float = 0.015
    risk_max: float = 0.10
    warmup: int = 260

    def to_dict(self) -> Dict:
        return asdict(self)


def _base_for_window(d: pd.DataFrame, n: int, max_h: float, p: BaseParams) -> pd.DataFrame:
    hh = d["high"].rolling(n, min_periods=n).max().shift(1)
    ll = d["low"].rolling(n, min_periods=n).min().shift(1)
    atr_prev = d["atr14"].shift(1)
    height = hh / ll - 1
    drift = (d["close"].shift(1) / d["close"].shift(n) - 1).abs()
    # cạn volume: TB 10 phiên cuối nền so với SMA50 volume TRƯỚC khi nền bắt đầu (nến t−N−1),
    # không so với SMA50 hiện tại (đã lẫn chính các phiên volume thấp trong nền → tỷ lệ luôn ≈ 1)
    dry = d["volume"].rolling(10, min_periods=10).mean().shift(1) / d["vol_sma50"].shift(n + 1)
    ok = (
        (height <= max_h)
        & ((hh - ll) <= p.height_atr_k * np.sqrt(n) * atr_prev)
        & (drift <= p.drift_frac * height)
        & (d["bbw_rank250"].shift(1) <= p.bbw_rank_max)
        & (dry <= p.dryup_max)
    )
    if p.require_uptrend:
        ok &= d["uptrend"].shift(1).fillna(False).astype(bool)
    return pd.DataFrame({"ok": ok.fillna(False), "hh": hh, "ll": ll, "height": height, "dry": dry})


def detect(df: pd.DataFrame, p: BaseParams = BaseParams(), feats: pd.DataFrame = None) -> pd.DataFrame:
    """Mỗi nến: base_ok, base_n, base_high, base_low, base_height, base_dry, breakout, breakdown, stop, risk."""
    d = feats if feats is not None else add_common(df)
    n_bars = len(d)
    out = pd.DataFrame(index=d.index)
    out["base_ok"] = False
    out["base_n"] = 0
    for c in ("base_high", "base_low", "base_height", "base_dry"):
        out[c] = np.nan
    mh = dict(p.max_height)
    for n in sorted(p.windows):  # nhỏ → lớn; N lớn hợp lệ ghi đè
        b = _base_for_window(d, n, mh[n], p)
        m = b["ok"].to_numpy()
        out.loc[m, "base_ok"] = True
        out.loc[m, "base_n"] = n
        out.loc[m, "base_high"] = b.loc[m, "hh"]
        out.loc[m, "base_low"] = b.loc[m, "ll"]
        out.loc[m, "base_height"] = b.loc[m, "height"]
        out.loc[m, "base_dry"] = b.loc[m, "dry"]

    c, hh, ll = d["close"], out["base_high"], out["base_low"]
    raw = (
        out["base_ok"]
        & (c >= hh * (1 + p.buffer))
        & (c <= hh * (1 + p.max_chase))
        & (d["rvol50"] >= p.rvol_min)
        & (d["clv"] >= p.clv_min)
        & (d["value_bn"] >= p.min_value_bn)
        & (d["value_avg20_bn"] >= p.min_value_bn)
    ).fillna(False)
    raw.iloc[: min(p.warmup, n_bars)] = False
    prior = raw.astype(int).rolling(p.fresh_bars, min_periods=1).sum().shift(1).fillna(0) > 0
    out["breakout"] = raw & ~prior
    out["breakdown"] = (out["base_ok"] & (c < ll * 0.995)).fillna(False)
    stop = np.maximum(hh - p.sl_atr * d["atr14"], c * p.sl_floor)
    out["stop"] = stop
    out["risk"] = (c - stop) / c
    ok_risk = (out["risk"] >= p.risk_min) & (out["risk"] <= p.risk_max)
    out["breakout"] &= ok_risk.fillna(False)
    out["rvol50"] = d["rvol50"]
    out["atr14"] = d["atr14"]
    return out
