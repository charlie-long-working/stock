"""
Vietnam policy / deposit interest-rate helpers.

Primary CSV: Trading-bot/vre/data/vietnam/interest_rates.csv
(kept in sync for macro work; mirrored reader here for vn_stock scripts).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd

# Prefer workspace Trading-bot path; fallback if layout differs.
_CANDIDATES = [
    Path(__file__).resolve().parents[3] / "Trading-bot" / "vre" / "data" / "vietnam" / "interest_rates.csv",
    Path("/Users/namnguyen/Documents/Cursor/Trading-bot/vre/data/vietnam/interest_rates.csv"),
]


def interest_rates_path() -> Optional[Path]:
    for p in _CANDIDATES:
        if p.exists():
            return p
    return None


def load_vn_policy_rates() -> Optional[pd.DataFrame]:
    path = interest_rates_path()
    if path is None:
        return None
    df = pd.read_csv(path, parse_dates=["date"])
    return df.sort_values("date").reset_index(drop=True)


def rates_snapshot() -> dict:
    """Latest official-policy style snapshot for reports."""
    df = load_vn_policy_rates()
    if df is None or len(df) == 0:
        return {"error": "interest_rates.csv missing"}
    last = df.iloc[-1]
    out = {
        "as_of": str(last["date"].date()),
        "refinancing_rate_pct": float(last["refinancing_rate"]),
        "source": "SBV QĐ 1123/QĐ-NHNN (from 2023-06-19); deposit caps QĐ 2411/QĐ-NHNN",
    }
    for col, key in [
        ("rediscount_rate", "rediscount_rate_pct"),
        ("overnight_rate", "overnight_rate_pct"),
        ("deposit_cap_under_1m", "deposit_cap_under_1m_pct"),
        ("deposit_cap_1m_6m", "deposit_cap_1m_6m_pct"),
        ("deposit_rate", "deposit_rate_legacy_pct"),
    ]:
        if col in df.columns and pd.notna(last[col]):
            out[key] = float(last[col])
    out["notes"] = (
        "Policy rates unchanged since Jun-2023: refinancing 4.5%, rediscount 3.0%, overnight 5.0%. "
        "Deposit ceiling 1–<6m: 4.75% (banks); 5.25% for people's credit funds / microfinance. "
        "6m+ deposits: market-set by banks."
    )
    return out
