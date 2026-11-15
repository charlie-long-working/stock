"""Chỉ báo nhân quả: giá trị tại nến t chỉ dùng dữ liệu ≤ t."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from vn_stock import DATA_DIR

ADJ_DIR = DATA_DIR / "intel" / "ohlcv_adj"
INDICES = ("VNINDEX", "VN30", "HNXINDEX")


def load_adjusted(sym: str, adj_dir: Path = ADJ_DIR) -> Optional[pd.DataFrame]:
    """Kho giá đã điều chỉnh cổ tức (Stock Intelligence cập nhật). Giá: nghìn đồng."""
    p = Path(adj_dir) / f"{sym}.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p, parse_dates=["time"]).dropna(subset=["close"])
    df = df.sort_values("time").drop_duplicates("time", keep="last").reset_index(drop=True)
    return df[["time", "open", "high", "low", "close", "volume"]]


def universe(adj_dir: Path = ADJ_DIR) -> list[str]:
    return sorted(p.stem for p in Path(adj_dir).glob("*.csv") if p.stem not in INDICES)


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def wilder(s: pd.Series, n: int) -> pd.Series:
    x = s.to_numpy(float)
    out = np.full(len(x), np.nan)
    valid = np.where(~np.isnan(x))[0]
    if len(valid) < n:
        return pd.Series(out, index=s.index)
    start = valid[n - 1]
    out[start] = np.nanmean(x[valid[:n]])
    for i in range(start + 1, len(x)):
        out[i] = out[i - 1] + ((x[i] if not np.isnan(x[i]) else out[i - 1]) - out[i - 1]) / n
    return pd.Series(out, index=s.index)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    pc = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)
    return wilder(tr, n)


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    up, dn = wilder(d.clip(lower=0), n), wilder((-d).clip(lower=0), n)
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def bb_width(close: pd.Series, n: int = 20, k: float = 2.0) -> pd.Series:
    mid = sma(close, n)
    sd = close.rolling(n, min_periods=n).std(ddof=0)
    return (2 * k * sd) / mid


def rolling_pctrank(s: pd.Series, n: int) -> pd.Series:
    """Hạng phần trăm của giá trị hiện tại trong n giá trị gần nhất (gồm chính nó) — nhân quả."""
    def rank_last(w: np.ndarray) -> float:
        last = w[-1]
        return float(np.mean(w <= last))

    return s.rolling(n, min_periods=n).apply(rank_last, raw=True)


def add_common(df: pd.DataFrame) -> pd.DataFrame:
    """Cột dùng chung cho mọi setup."""
    d = df.copy()
    d["atr14"] = atr(d, 14)
    d["sma50"] = sma(d["close"], 50)
    d["sma200"] = sma(d["close"], 200)
    d["ema20"] = ema(d["close"], 20)
    d["rsi14"] = rsi(d["close"], 14)
    d["vol_sma50"] = sma(d["volume"], 50)
    d["rvol50"] = d["volume"] / d["vol_sma50"].shift(1)
    d["value_bn"] = d["close"] * 1000 * d["volume"] / 1e9
    d["value_avg20_bn"] = sma(d["value_bn"], 20)
    rng = (d["high"] - d["low"]).replace(0, np.nan)
    d["clv"] = ((d["close"] - d["low"]) / rng).fillna(0.5)
    d["bbw_rank250"] = rolling_pctrank(bb_width(d["close"]), 250)
    d["uptrend"] = (d["close"] > d["sma200"]) & (d["sma50"] > d["sma200"])
    return d


def index_bearish(idx: pd.DataFrame) -> pd.Series:
    """Thị trường giảm: VN-Index < SMA200 và SMA50 < SMA200 (theo ngày, nhân quả). Index = time."""
    c = idx.set_index("time")["close"]
    return (c < sma(c, 200)) & (sma(c, 50) < sma(c, 200))
