"""
Tải OHLCV crypto / tài sản Yahoo (BTC-USD, ETH-USD, …) về đúng format vn_stock CSV.
"""

from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from vn_stock import DATA_DIR
from vn_stock.data_loaders.vn_ohlcv import VALID_INTERVALS, get_ohlcv_dir, _save_ohlcv


def _yahoo_interval(interval: str) -> str:
    u = interval.upper()
    m = {"1D": "1d", "1W": "1wk", "1H": "1h"}
    if u not in m:
        raise ValueError(f"interval phải thuộc {VALID_INTERVALS}")
    return m[u]


def fetch_yahoo_ohlcv(
    ticker: str,
    interval: str = "1D",
    start: str = "2015-01-01",
    end: Optional[str] = None,
) -> Optional[pd.DataFrame]:
    """
    Trả về DataFrame: time, open, high, low, close, volume.
    """
    try:
        import yfinance as yf
    except ImportError as e:
        raise ImportError("Cài yfinance: pip install yfinance") from e

    if interval.upper() not in VALID_INTERVALS:
        raise ValueError(f"interval phải thuộc {VALID_INTERVALS}")

    t = yf.Ticker(ticker)
    df = t.history(
        start=start,
        end=end or datetime.now().strftime("%Y-%m-%d"),
        interval=_yahoo_interval(interval),
        auto_adjust=False,
        prepost=False,
    )
    if df is None or len(df) == 0:
        return None

    df = df.reset_index()
    # Cột thời gian: Date hoặc Datetime
    time_col = None
    for c in df.columns:
        cl = str(c).lower()
        if "date" in cl or c == "Datetime":
            time_col = c
            break
    if time_col is None:
        time_col = df.columns[0]

    out = pd.DataFrame()
    out["time"] = pd.to_datetime(df[time_col])
    if hasattr(out["time"].dtype, "tz") and out["time"].dt.tz is not None:
        out["time"] = out["time"].dt.tz_convert("UTC").dt.tz_localize(None)

    cmap = {"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"}
    for old, new in cmap.items():
        if old in df.columns:
            out[new] = pd.to_numeric(df[old], errors="coerce")

    out = out.dropna(subset=["open", "high", "low", "close"])
    out["volume"] = out["volume"].fillna(0.0)
    out = out.sort_values("time").reset_index(drop=True)
    return out


def fetch_and_save_yahoo(
    ticker: str,
    interval: str = "1D",
    start: str = "2015-01-01",
    end: Optional[str] = None,
    data_root: Optional[Path] = None,
) -> Optional[Path]:
    """Tải Yahoo và lưu vào {data_root or DATA_DIR}/ohlcv/{TICKER}/{interval}.csv"""
    sym = ticker.strip().upper()
    df = fetch_yahoo_ohlcv(sym, interval=interval, start=start, end=end)
    if df is None or len(df) == 0:
        return None
    return _save_ohlcv(sym, interval.upper(), df, data_root=data_root)


def default_crypto_data_root() -> Path:
    """Thư mục bundle crypto (tách khỏi cổ phiếu VN)."""
    return DATA_DIR / "crypto"
