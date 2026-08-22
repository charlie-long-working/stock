"""
Financial statement loader using vnstock (primary) and VietFin (fallback).

Fetches balance sheet, income statement, cash flow, and financial ratios.
vnstock VCI source provides comprehensive data including P/E, ROE, ROA, EPS, BVPS, D/E.
"""

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from vn_stock import DATA_DIR

FUNDAMENTALS_DIR = DATA_DIR / "fundamentals"


def get_fundamentals_dir(data_root: Optional[Path] = None) -> Path:
    """Default DATA_DIR/fundamentals; sector bundle: data_root/fundamentals."""
    if data_root is None:
        return FUNDAMENTALS_DIR
    return Path(data_root) / "fundamentals"


def _get_finance(symbol: str):
    from vnstock import Vnstock
    return Vnstock().stock(symbol=symbol, source="VCI").finance


def fetch_fundamentals(
    symbol: str,
    period: str = "annual",
    save: bool = True,
    data_root: Optional[Path] = None,
) -> Dict[str, Optional[pd.DataFrame]]:
    """
    Fetch balance sheet, income statement, cash flow, and ratios for a symbol.
    Uses vnstock VCI source (primary) with VietFin fallback.
    """
    result = {
        "balance_sheet": None,
        "income_statement": None,
        "cash_flow": None,
        "ratios": None,
    }

    import time as _time
    try:
        finance = _get_finance(symbol)
        for key, method in [
            ("balance_sheet", "balance_sheet"),
            ("income_statement", "income_statement"),
            ("cash_flow", "cash_flow"),
            ("ratios", "ratio"),
        ]:
            try:
                result[key] = getattr(finance, method)(period=period)
                _time.sleep(2)
            except SystemExit:
                print(f"[fundamentals] Rate limited on {symbol}/{key}, waiting 45s...")
                _time.sleep(45)
                try:
                    result[key] = getattr(finance, method)(period=period)
                except (SystemExit, Exception):
                    pass
            except Exception as e:
                print(f"[fundamentals] Error {symbol}/{key}: {e}")
    except (SystemExit, Exception) as e:
        print(f"[fundamentals] vnstock error for {symbol}: {e}")
        result = _fetch_vietfin_fallback(symbol, period)

    if save:
        suffix = "_quarter" if period == "quarter" else ""
        save_fundamentals(symbol, result, data_root=data_root, filename_suffix=suffix)

    return result


def _fetch_vietfin_fallback(
    symbol: str,
    period: str = "annual",
) -> Dict[str, Optional[pd.DataFrame]]:
    """Fallback to VietFin when vnstock fails."""
    result = {
        "balance_sheet": None,
        "income_statement": None,
        "cash_flow": None,
        "ratios": None,
    }
    try:
        from vietfin import vf
        try:
            result["balance_sheet"] = vf.equity.fundamental.balance(
                symbol=symbol.lower(), period=period, provider="ssi"
            ).to_df()
        except Exception:
            pass
        try:
            result["income_statement"] = vf.equity.fundamental.income(
                symbol=symbol.lower(), period=period, provider="ssi"
            ).to_df()
        except Exception:
            pass
        try:
            result["cash_flow"] = vf.equity.fundamental.cash(
                symbol=symbol.lower(), period=period, provider="ssi"
            ).to_df()
        except Exception:
            pass
    except ImportError:
        pass
    return result


def save_fundamentals(
    symbol: str,
    data: Dict[str, Optional[pd.DataFrame]],
    data_root: Optional[Path] = None,
    filename_suffix: str = "",
):
    """
    Save financial statements to CSV files.

    filename_suffix: e.g. '_quarter' for quarterly reports so annual files are not overwritten.
    """
    out_dir = get_fundamentals_dir(data_root) / symbol.upper()
    out_dir.mkdir(parents=True, exist_ok=True)

    suf = filename_suffix or ""
    file_map = {
        "balance_sheet": f"balance_sheet{suf}.csv",
        "income_statement": f"income_statement{suf}.csv",
        "cash_flow": f"cash_flow{suf}.csv",
        "ratios": f"ratios{suf}.csv",
    }
    for key, filename in file_map.items():
        df = data.get(key)
        if df is not None and len(df) > 0:
            df_save = df.copy()
            if isinstance(df_save.columns, pd.MultiIndex):
                df_save.columns = [
                    col[-1] if isinstance(col, tuple) and col[-1] != "" else
                    (col[0] if isinstance(col, tuple) else col)
                    for col in df_save.columns
                ]
            df_save.to_csv(out_dir / filename, index=False)


def load_fundamentals(symbol: str, data_root: Optional[Path] = None) -> Dict[str, Optional[pd.DataFrame]]:
    """Load saved financial statements from CSV."""
    out_dir = get_fundamentals_dir(data_root) / symbol.upper()
    result = {}
    for key, filename in [
        ("balance_sheet", "balance_sheet.csv"),
        ("income_statement", "income_statement.csv"),
        ("cash_flow", "cash_flow.csv"),
        ("ratios", "ratios.csv"),
    ]:
        path = out_dir / filename
        if path.exists():
            result[key] = pd.read_csv(path)
        else:
            result[key] = None
    return result


def compute_ratios(
    symbol: str,
    current_price: Optional[float] = None,
    data_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Compute fundamental ratios from saved financial statements.

    vnstock ratios DataFrame already contains:
      P/E, ROE, ROA, EPS, BVPS, D/E, Net Profit Margin, ROIC, Dividend Yield, etc.

    Also extracts from balance_sheet and income_statement:
      revenue growth, profit growth, total equity, total assets, operating cashflow, etc.
    """
    data = load_fundamentals(symbol, data_root=data_root)
    ratios_result: Dict[str, Any] = {"symbol": symbol}

    ratio_df = data.get("ratios")
    if ratio_df is not None and len(ratio_df) > 0:
        ratios_result.update(_extract_from_ratio_df(ratio_df, current_price))

    inc = data.get("income_statement")
    if inc is not None and len(inc) > 0:
        ratios_result.update(_extract_income_metrics(inc))

    bs = data.get("balance_sheet")
    if bs is not None and len(bs) > 0:
        ratios_result.update(_extract_balance_metrics(bs))

    cf = data.get("cash_flow")
    if cf is not None and len(cf) > 0:
        ratios_result.update(_extract_cashflow_metrics(cf))

    return ratios_result


def _flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Flatten MultiIndex columns if present."""
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [
            col[-1] if col[-1] != "" else col[0]
            for col in df.columns
        ]
    return df


def _find_col(df: pd.DataFrame, patterns: List[str]) -> Optional[str]:
    """Find a column matching any of the patterns (case-insensitive)."""
    for col in df.columns:
        col_str = str(col).lower()
        for pattern in patterns:
            if pattern.lower() in col_str:
                return col
    return None


def _get_latest_annual(df: pd.DataFrame) -> Optional[pd.Series]:
    """Get the most recent annual row from a financial DataFrame."""
    df = _flatten_columns(df.copy())
    year_col = _find_col(df, ["yearReport", "year", "fiscal_year", "fiscal_period"])
    length_col = _find_col(df, ["lengthReport", "length", "quarter"])

    if year_col is None:
        return df.iloc[0] if len(df) > 0 else None

    if length_col is not None:
        annual = df[df[length_col].astype(str).isin(["4", "0", "annual", "5"])]
        if len(annual) > 0:
            return annual.sort_values(year_col, ascending=False).iloc[0]

    return df.sort_values(year_col, ascending=False).iloc[0]


def _get_annual_series(df: pd.DataFrame, col_name: str) -> Optional[pd.Series]:
    """Get time series of a column across annual periods."""
    df = _flatten_columns(df.copy())
    year_col = _find_col(df, ["yearReport", "year", "fiscal_year"])
    length_col = _find_col(df, ["lengthReport", "length", "quarter"])
    target_col = _find_col(df, [col_name])

    if target_col is None or year_col is None:
        return None

    if length_col is not None:
        df = df[df[length_col].astype(str).isin(["4", "0", "annual", "5"])]

    if len(df) < 2:
        return None

    return df.sort_values(year_col)[[year_col, target_col]].set_index(year_col)[target_col].dropna()


def _extract_from_ratio_df(df: pd.DataFrame, current_price: Optional[float]) -> Dict[str, Any]:
    """Extract key ratios from vnstock ratio DataFrame."""
    r: Dict[str, Any] = {}
    df = _flatten_columns(df.copy())

    latest = _get_latest_annual(df)
    if latest is None:
        return r

    ratio_map = {
        "roe": ["ROE (%)", "ROE", "roe"],
        "roa": ["ROA (%)", "ROA", "roa"],
        "net_margin": ["Net Profit Margin (%)", "Net Profit Margin", "net_margin"],
        "debt_to_equity": ["Debt/Equity", "D/E", "debt_equity"],
        "pe": ["P/E", "PE", "pe"],
        "eps": ["EPS (VND)", "EPS", "eps"],
        "bvps": ["BVPS (VND)", "BVPS", "bvps"],
        "roic": ["ROIC (%)", "ROIC", "roic"],
        "dividend_yield": ["Dividend yield (%)", "Dividend Yield", "dividend"],
        "market_cap": ["Market Capital (Bn. VND)", "Market Capital", "market_cap"],
        "outstanding_shares": ["Outstanding Share (Mil. Shares)", "Outstanding Share"],
    }

    for key, patterns in ratio_map.items():
        col = _find_col(pd.DataFrame([latest]), patterns)
        if col is not None and pd.notna(latest.get(col)):
            val = float(latest[col])
            if key in ("roe", "roa", "net_margin", "roic", "dividend_yield"):
                if abs(val) > 1:
                    val = val / 100
            r[key] = val

    pb_col = _find_col(pd.DataFrame([latest]), ["P/B", "PB"])
    if pb_col and pd.notna(latest.get(pb_col)):
        r["pb"] = float(latest[pb_col])

    return r


def _extract_income_metrics(inc: pd.DataFrame) -> Dict[str, Any]:
    """Extract revenue and profit growth from income statement."""
    r: Dict[str, Any] = {}
    inc = _flatten_columns(inc.copy())

    rev_col = _find_col(inc, ["Revenue (Bn. VND)", "Revenue", "Doanh thu"])
    rev_yoy = _find_col(inc, ["Revenue YoY (%)", "Revenue YoY"])
    profit_col = _find_col(inc, [
        "Attribute to parent company (Bn. VND)",
        "Attribute to parent company",
        "Net Income",
        "Lợi nhuận sau thuế",
    ])
    profit_yoy = _find_col(inc, [
        "Attribute to parent company YoY (%)",
        "Attribute to parent company YoY",
    ])

    latest = _get_latest_annual(inc)
    if latest is None:
        return r

    if rev_col and pd.notna(latest.get(rev_col)):
        r["revenue_latest"] = float(latest[rev_col])
    if profit_col and pd.notna(latest.get(profit_col)):
        r["net_income_latest"] = float(latest[profit_col])
    if rev_yoy and pd.notna(latest.get(rev_yoy)):
        val = float(latest[rev_yoy])
        r["revenue_growth"] = val / 100 if abs(val) > 1 else val
    if profit_yoy and pd.notna(latest.get(profit_yoy)):
        val = float(latest[profit_yoy])
        r["profit_growth"] = val / 100 if abs(val) > 1 else val

    if "revenue_growth" not in r:
        series = _get_annual_series(inc, "Revenue")
        if series is not None and len(series) >= 2:
            vals = series.values
            if vals[-2] != 0:
                r["revenue_growth"] = (vals[-1] - vals[-2]) / abs(vals[-2])

    return r


def _extract_balance_metrics(bs: pd.DataFrame) -> Dict[str, Any]:
    """Extract key balance sheet metrics."""
    r: Dict[str, Any] = {}
    bs = _flatten_columns(bs.copy())

    latest = _get_latest_annual(bs)
    if latest is None:
        return r

    for key, patterns in [
        ("total_assets", ["TOTAL ASSETS", "Tổng tài sản"]),
        ("total_equity", ["OWNER'S EQUITY", "Vốn chủ sở hữu", "Total Equity"]),
        ("total_liabilities", ["LIABILITIES", "Tổng nợ"]),
    ]:
        col = _find_col(pd.DataFrame([latest]), patterns)
        if col and pd.notna(latest.get(col)):
            r[key] = float(latest[col])

    return r


def _extract_cashflow_metrics(cf: pd.DataFrame) -> Dict[str, Any]:
    """Extract key cash flow metrics."""
    r: Dict[str, Any] = {}
    cf = _flatten_columns(cf.copy())

    latest = _get_latest_annual(cf)
    if latest is None:
        return r

    ocf_col = _find_col(pd.DataFrame([latest]), [
        "Net cash flows from operating",
        "Operating",
        "Hoạt động kinh doanh",
    ])
    if ocf_col and pd.notna(latest.get(ocf_col)):
        r["operating_cashflow"] = float(latest[ocf_col])

    invest_col = _find_col(pd.DataFrame([latest]), [
        "Net cash flows from investing",
        "Investing",
        "Đầu tư",
    ])
    if invest_col and pd.notna(latest.get(invest_col)):
        ocf = r.get("operating_cashflow", 0)
        inv = float(latest[invest_col])
        r["free_cashflow"] = ocf + inv

    return r


def batch_fetch_fundamentals(
    symbols: List[str],
    period: str = "annual",
    delay: float = 4.0,
    data_root: Optional[Path] = None,
) -> Dict[str, Dict[str, Optional[pd.DataFrame]]]:
    """Fetch fundamentals for multiple symbols."""
    results = {}
    for i, symbol in enumerate(symbols):
        print(f"[{i+1}/{len(symbols)}] Fetching fundamentals for {symbol}...")
        try:
            results[symbol] = fetch_fundamentals(symbol, period=period, save=True, data_root=data_root)
        except Exception as e:
            print(f"  Error: {e}")
            results[symbol] = {}
        time.sleep(delay)
    return results
