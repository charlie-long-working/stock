"""
OHLCV data loader for Vietnamese stocks using vnstock.

Supports timeframes: 1H, 4H (resampled from 1H), 1D, 1W.
Data available from ~March 2012 (free tier).
H1 data may only be available for recent periods.
"""

import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
import pandas as pd

from vn_stock import DATA_DIR

OHLCV_DIR = DATA_DIR / "ohlcv"
# Native API intervals from vnstock; 4H is built by resampling 1H.
API_INTERVALS = ("1H", "1D", "1W")
VALID_INTERVALS = ("1H", "4H", "1D", "1W")
DATA_START = "2012-03-20"


RATE_LIMIT_DELAY = 4.0  # seconds between API calls to stay under 20 req/min


def get_ohlcv_dir(data_root: Optional[Path] = None) -> Path:
    """
    Root folder for OHLCV CSV trees.
    Default: DATA_DIR/ohlcv. If data_root is set: data_root/ohlcv (sector bundles).
    """
    if data_root is None:
        return OHLCV_DIR
    return Path(data_root) / "ohlcv"


def _get_quote(symbol: str, source: str = "VCI"):
    from vnstock import Quote
    return Quote(symbol=symbol, source=source)


def fetch_ohlcv(
    symbol: str,
    interval: str = "1D",
    start: str = DATA_START,
    end: Optional[str] = None,
    source: str = "VCI",
    save: bool = True,
    data_root: Optional[Path] = None,
) -> Optional[pd.DataFrame]:
    """
    Fetch OHLCV data from vnstock and optionally save to CSV.

    Returns DataFrame with columns: time, open, high, low, close, volume.
    For H1 data, vnstock may limit how far back data is available.
    """
    if interval not in VALID_INTERVALS:
        raise ValueError(f"interval must be one of {VALID_INTERVALS}")

    if interval == "4H":
        h1 = fetch_ohlcv(symbol, "1H", start=start, end=end, source=source, save=save, data_root=data_root)
        if h1 is None or len(h1) == 0:
            return None
        df4 = resample_ohlcv(h1, "4H")
        if save and df4 is not None and len(df4) > 0:
            _save_ohlcv(symbol, "4H", df4, data_root=data_root)
        return df4

    if end is None:
        end = datetime.now().strftime("%Y-%m-%d")

    max_retries = 3
    df = None
    for attempt in range(max_retries):
        try:
            src = source if attempt == 0 else "KBS"
            quote = _get_quote(symbol, source=src)
            df = quote.history(start=start, end=end, interval=interval)
            break
        except SystemExit:
            wait = 45
            print(f"[vnstock] Rate limited for {symbol}, waiting {wait}s...")
            time.sleep(wait)
            continue
        except Exception as e:
            err_str = str(e).lower()
            if "rate limit" in err_str or "429" in err_str:
                wait = 45
                print(f"[vnstock] Rate limited for {symbol}, waiting {wait}s...")
                time.sleep(wait)
                continue
            if attempt == 0 and source == "VCI":
                print(f"[vnstock] VCI error for {symbol} {interval}, trying KBS...")
                time.sleep(RATE_LIMIT_DELAY)
                continue
            print(f"[vnstock] Error fetching {symbol} {interval}: {e}")
            return None

    if df is None or len(df) == 0:
        return None

    df = df.rename(columns={"time": "time"})
    expected_cols = ["time", "open", "high", "low", "close", "volume"]
    for col in expected_cols:
        if col not in df.columns:
            print(f"[vnstock] Missing column '{col}' for {symbol}")
            return None

    df = df[expected_cols].copy()
    df["time"] = pd.to_datetime(df["time"])
    df = df.sort_values("time").reset_index(drop=True)

    if save:
        _save_ohlcv(symbol, interval, df, data_root=data_root)

    return df


def resample_ohlcv(df: pd.DataFrame, target: str = "4H") -> Optional[pd.DataFrame]:
    """Resample OHLCV (typically 1H → 4H)."""
    if df is None or len(df) == 0:
        return None
    rule = {"4H": "4h", "1D": "1D", "1W": "1W"}.get(target)
    if rule is None:
        raise ValueError(f"Unsupported resample target: {target}")

    work = df.copy()
    work["time"] = pd.to_datetime(work["time"])
    work = work.set_index("time").sort_index()
    out = work.resample(rule, label="left", closed="left").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }).dropna(subset=["open", "close"]).reset_index()
    return out


def build_h4_from_h1(symbol: str, data_root: Optional[Path] = None) -> Optional[pd.DataFrame]:
    """Build/save 4H bars from local 1H CSV."""
    h1 = load_ohlcv(symbol, "1H", data_root=data_root)
    if h1 is None or len(h1) == 0:
        return None
    df4 = resample_ohlcv(h1, "4H")
    if df4 is not None and len(df4) > 0:
        _save_ohlcv(symbol, "4H", df4, data_root=data_root)
    return df4


def _save_ohlcv(symbol: str, interval: str, df: pd.DataFrame, data_root: Optional[Path] = None) -> Path:
    out_dir = get_ohlcv_dir(data_root) / symbol.upper()
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{interval}.csv"
    df.to_csv(path, index=False)
    return path


def load_ohlcv(
    symbol: str,
    interval: str = "1D",
    data_root: Optional[Path] = None,
) -> Optional[pd.DataFrame]:
    """Load OHLCV from local CSV."""
    path = get_ohlcv_dir(data_root) / symbol.upper() / f"{interval}.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path, parse_dates=["time"])
    return df


def load_ohlcv_arrays(
    symbol: str,
    interval: str = "1D",
    data_root: Optional[Path] = None,
) -> Optional[Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]]:
    """Load OHLCV as numpy arrays: (time_ms, open, high, low, close, volume)."""
    df = load_ohlcv(symbol, interval, data_root=data_root)
    if df is None or len(df) == 0:
        return None

    time_ms = (df["time"].astype(np.int64) // 10**6).values
    return (
        time_ms,
        df["open"].values.astype(np.float64),
        df["high"].values.astype(np.float64),
        df["low"].values.astype(np.float64),
        df["close"].values.astype(np.float64),
        df["volume"].values.astype(np.float64),
    )


def update_ohlcv(
    symbol: str,
    interval: str = "1D",
    source: str = "VCI",
    data_root: Optional[Path] = None,
) -> Optional[pd.DataFrame]:
    """
    Incremental update: load existing CSV, fetch only new data, merge, save.
    For 4H: refresh 1H then resample.
    """
    if interval == "4H":
        update_ohlcv(symbol, "1H", source=source, data_root=data_root)
        return build_h4_from_h1(symbol, data_root=data_root)

    if interval not in API_INTERVALS:
        raise ValueError(f"interval must be one of {VALID_INTERVALS}")

    existing = load_ohlcv(symbol, interval, data_root=data_root)

    if existing is not None and len(existing) > 0:
        last_date = existing["time"].max()
        start = (last_date + timedelta(days=1)).strftime("%Y-%m-%d")
        if start >= datetime.now().strftime("%Y-%m-%d"):
            return existing
    else:
        start = DATA_START

    new_data = fetch_ohlcv(symbol, interval, start=start, source=source, save=False, data_root=data_root)

    if new_data is None or len(new_data) == 0:
        return existing

    if existing is not None and len(existing) > 0:
        combined = pd.concat([existing, new_data], ignore_index=True)
        combined = combined.drop_duplicates(subset=["time"]).sort_values("time").reset_index(drop=True)
    else:
        combined = new_data

    _save_ohlcv(symbol, interval, combined, data_root=data_root)
    return combined


def batch_fetch_ohlcv(
    symbols: list,
    intervals: list = None,
    start: str = DATA_START,
    source: str = "VCI",
    delay: float = RATE_LIMIT_DELAY,
    data_root: Optional[Path] = None,
) -> dict:
    """
    Fetch OHLCV for multiple symbols and intervals.
    Returns dict[symbol][interval] = DataFrame.
    """
    if intervals is None:
        intervals = ["1D", "1W"]

    results = {}
    total = len(symbols) * len(intervals)
    done = 0

    for symbol in symbols:
        results[symbol] = {}
        for interval in intervals:
            done += 1
            print(f"[{done}/{total}] Fetching {symbol} {interval}...")
            df = fetch_ohlcv(symbol, interval, start=start, source=source, save=True, data_root=data_root)
            results[symbol][interval] = df
            time.sleep(delay)

    return results
