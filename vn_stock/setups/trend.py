"""
Bộ lọc xu hướng khung ngày/tuần: EMA 25/50/200 ngày + dải hỗ trợ tuần (SMA 20 tuần, EMA 21 tuần).

Nhân quả: giá trị tại nến t chỉ dùng dữ liệu ≤ t.
- EMA ngày tính trên giá đóng cửa đã điều chỉnh.
- Dải tuần dùng tuần T2–T6 ĐÃ ĐÓNG (nhãn W-FRI). Tuần có nhãn F áp từ ngày F trở đi; nếu thứ 6 nghỉ lễ
  thì áp từ phiên sau đó (thận trọng, không bao giờ sớm hơn).

Chế độ lọc (`mode`) cho tín hiệu MUA tại nến t:
  none   : không lọc
  ema200 : close > EMA200 và EMA50 > EMA200
  band   : close > cạnh trên của dải tuần
  full   : close > EMA50, close > EMA200 và close > cạnh trên dải tuần
Trạng thái mô tả: up (đạt full), down (dưới EMA200 và dưới cạnh dưới dải), mixed (còn lại).
"""

from __future__ import annotations

from typing import Dict, Optional

import numpy as np
import pandas as pd

MODES = ("none", "ema200", "band", "full")
LABEL = {"up": "✅ thuận xu hướng", "mixed": "➖ xu hướng lẫn lộn", "down": "⚠️ ngược xu hướng"}


def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def weekly_band(df: pd.DataFrame, sma_w: int = 20, ema_w: int = 21) -> pd.DataFrame:
    """SMA/EMA tuần của các tuần đã đóng, căn về từng phiên ngày (index như df)."""
    t = pd.to_datetime(df["time"])
    c = pd.Series(df["close"].to_numpy(float), index=t)
    w = c.resample("W-FRI").last().dropna()
    band = pd.DataFrame({"sma20w": w.rolling(sma_w, min_periods=sma_w).mean(),
                         "ema21w": w.ewm(span=ema_w, adjust=False, min_periods=ema_w).mean()})
    # tuần nhãn F (thứ 6) dùng được từ phiên có ngày ≥ F
    out = band.reindex(t, method="ffill")
    out.index = df.index
    return out


def trend_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Cột: ema25, ema50, ema200, sma20w, ema21w, band_lo, band_hi, ema200_ok, band_ok, full_ok, state."""
    c = df["close"].astype(float)
    out = pd.DataFrame(index=df.index)
    out["close"] = c
    out["ema25"], out["ema50"], out["ema200"] = _ema(c, 25), _ema(c, 50), _ema(c, 200)
    out = out.join(weekly_band(df))
    out["band_lo"] = out[["sma20w", "ema21w"]].min(axis=1, skipna=False)
    out["band_hi"] = out[["sma20w", "ema21w"]].max(axis=1, skipna=False)
    out["ema200_ok"] = ((c > out["ema200"]) & (out["ema50"] > out["ema200"])).fillna(False)
    out["band_ok"] = (c > out["band_hi"]).fillna(False)
    out["full_ok"] = ((c > out["ema50"]) & (c > out["ema200"]) & out["band_ok"]).fillna(False)
    down = ((c < out["ema200"]) & (c < out["band_lo"])).fillna(False)
    out["state"] = np.where(out["full_ok"], "up", np.where(down, "down", "mixed"))
    return out


def passes(tf: pd.DataFrame, mode: str) -> pd.Series:
    """Cờ cho phép MUA theo chế độ lọc (Series bool, index như tf)."""
    if mode in (None, "", "none"):
        return pd.Series(True, index=tf.index)
    if mode not in MODES:
        raise ValueError(f"trend mode không hợp lệ: {mode}")
    return tf[f"{mode}_ok"].astype(bool)


def snapshot(df: pd.DataFrame, tf: Optional[pd.DataFrame] = None) -> Dict:
    """Trạng thái ở nến cuối (để in vào thông báo)."""
    tf = tf if tf is not None else trend_frame(df)
    r = tf.iloc[-1]
    f = lambda v: None if pd.isna(v) else float(v)  # noqa: E731
    return {"state": str(r["state"]), "close": float(r["close"]), "ema25": f(r["ema25"]), "ema50": f(r["ema50"]),
            "ema200": f(r["ema200"]), "sma20w": f(r["sma20w"]), "ema21w": f(r["ema21w"]),
            "full_ok": bool(r["full_ok"]), "ema200_ok": bool(r["ema200_ok"]), "band_ok": bool(r["band_ok"])}


def describe(s: Dict) -> str:
    """Một dòng: nhãn + vị trí giá so với từng đường."""
    def rel(name: str, v: Optional[float]) -> str:
        if v is None:
            return f"{name} –"
        return f"{name} {v:,.2f} {'↑' if s['close'] > v else '↓'}"

    band = (f"dải tuần {min(s['sma20w'], s['ema21w']):,.2f}–{max(s['sma20w'], s['ema21w']):,.2f}"
            f" {'↑' if s['band_ok'] else ('↓' if s['close'] < min(s['sma20w'], s['ema21w']) else '↔')}"
            if s["sma20w"] is not None and s["ema21w"] is not None else "dải tuần –")
    return (f"Xu hướng: {LABEL.get(s['state'], s['state'])} · {rel('EMA25', s['ema25'])} · {rel('EMA50', s['ema50'])}"
            f" · {rel('EMA200', s['ema200'])} · {band} (↑ giá trên, ↓ giá dưới)")
