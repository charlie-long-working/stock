"""
Screener: Top 100 vốn hóa, Top 10 hàng ngày, lọc theo ngành.

Dùng vnstock Listing + Screener API.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from vn_stock import DATA_DIR

TOP100_DIR = DATA_DIR / "top100"

def _listing_to_dataframe(obj) -> pd.DataFrame:
    """
    vnstock 3.x: `listing.symbols_by_group('VN30'|'VN100')` có thể trả **Series** (cột symbol),
    không phải DataFrame — chuẩn hóa để code cũ dùng `.columns` / lọc vẫn chạy.
    """
    if obj is None:
        return pd.DataFrame()
    if isinstance(obj, pd.Series):
        col = obj.name if obj.name else "symbol"
        return pd.DataFrame({col: obj.values})
    if isinstance(obj, pd.DataFrame):
        return obj
    return pd.DataFrame(obj)


SECTOR_MAP = {
    "ngan_hang": "Banks",
    "chung_khoan": "Financial Services",
    "bao_hiem": "Insurance",
    "dau_khi": "Oil & Gas",
    "phan_bon": "Chemicals",
    "bat_dong_san": "Real Estate",
    "cang_bien": "Industrial Goods & Services",
    "thep": "Basic Resources",
    "xay_dung": "Construction & Materials",
    "thuc_pham": "Food & Beverage",
    "cong_nghe": "Technology",
    "dien": "Utilities",
    "ban_le": "Retail",
    "duoc_pham": "Health Care",
    "vien_thong": "Telecommunications",
}


def _get_stock_instance():
    from vnstock import Vnstock
    return Vnstock()


def get_all_symbols(exchange: str = "HOSE") -> pd.DataFrame:
    """Get all listed symbols from an exchange."""
    try:
        stock = _get_stock_instance()
        df = stock.stock(symbol="ACB", source="VCI").listing.symbols_by_exchange(exchange)
        return df
    except Exception as e:
        print(f"[screener] Error getting symbols for {exchange}: {e}")
        return pd.DataFrame()


def get_industry_list() -> pd.DataFrame:
    """Get ICB industry classification list."""
    try:
        stock = _get_stock_instance()
        df = stock.stock(symbol="ACB", source="VCI").listing.industries_icb()
        return df
    except Exception as e:
        print(f"[screener] Error getting industries: {e}")
        return pd.DataFrame()


def get_symbols_by_sector(sector_key: str = None) -> pd.DataFrame:
    """
    Get symbols filtered by sector.
    sector_key: key from SECTOR_MAP (e.g., 'ngan_hang', 'bat_dong_san')
    If None, returns all with industry info.
    """
    try:
        stock = _get_stock_instance()
        df = stock.stock(symbol="ACB", source="VCI").listing.symbols_by_industries()
        if sector_key and sector_key in SECTOR_MAP:
            industry_name = SECTOR_MAP[sector_key]
            if "industry" in df.columns:
                df = df[df["industry"].str.contains(industry_name, case=False, na=False)]
            elif "icbName" in df.columns:
                df = df[df["icbName"].str.contains(industry_name, case=False, na=False)]
        return df
    except Exception as e:
        print(f"[screener] Error getting symbols by sector: {e}")
        return pd.DataFrame()


def get_top100(save: bool = True) -> pd.DataFrame:
    """
    Get top 100 companies by market cap.
    Uses VN100 index components or screener sorted by market cap.
    """
    try:
        stock = _get_stock_instance()
        try:
            raw = stock.stock(symbol="ACB", source="VCI").listing.symbols_by_group("VN100")
            df = _listing_to_dataframe(raw)
            if df is not None and len(df) >= 50:
                if save:
                    _save_top_list(df, "top100")
                return df
        except Exception:
            pass

        from vnstock import Quote
        try:
            df = stock.stock(symbol="ACB", source="VCI").listing.symbols_by_exchange("HOSE")
            if df is not None and len(df) > 0:
                if save:
                    _save_top_list(df.head(100), "top100")
                return df.head(100)
        except Exception:
            pass

    except Exception as e:
        print(f"[screener] Error getting top 100: {e}")

    cached = _load_top_list("top100")
    if cached is not None:
        return cached

    return pd.DataFrame()


def get_vn30(save: bool = True) -> pd.DataFrame:
    """
    Danh sách VN30 (blue chip chỉ số). Thử API `symbols_by_group('VN30')`, không được thì fallback.
    """
    try:
        stock = _get_stock_instance()
        raw = stock.stock(symbol="ACB", source="VCI").listing.symbols_by_group("VN30")
        df = _listing_to_dataframe(raw)
        if df is not None and len(df) >= 20:
            if save:
                _save_top_list(df, "vn30")
            return df
    except Exception as e:
        print(f"[screener] VN30 API: {e}")

    cached = _load_top_list("vn30")
    if cached is not None and len(cached) > 0:
        return cached

    # Fallback: 30 mã vốn hóa lớn điển hình (cập nhật theo thời điểm khi API lỗi)
    return pd.DataFrame(
        {
            "symbol": [
                "ACB", "BCM", "BID", "BVH", "CTG", "FPT", "GAS", "GVR", "HDB", "HPG",
                "KDH", "MSN", "MWG", "NVL", "PDR", "PLX", "POW", "REE", "SAB", "SSI",
                "STB", "TCB", "TPB", "VCB", "VHM", "VIC", "VJC", "VNM", "VPB", "VRE",
            ]
        }
    )


def get_top10(save: bool = True) -> pd.DataFrame:
    """Get top 10 companies by market cap from top 100."""
    top100 = get_top100(save=False)
    if top100 is None or len(top100) == 0:
        return pd.DataFrame()

    top10 = top100.head(10)
    if save:
        _save_top_list(top10, "top10")
    return top10


def get_financial_sector_symbols() -> List[str]:
    """
    Get all financial sector symbols (banks, securities, insurance)
    from top 100 by market cap.
    """
    top100 = get_top100(save=False)
    if top100 is None or len(top100) == 0:
        return _fallback_financial_symbols()

    try:
        industry_df = get_symbols_by_sector()
        if industry_df is not None and len(industry_df) > 0:
            financial_industries = ["Banks", "Financial Services", "Insurance"]
            symbol_col = "symbol" if "symbol" in industry_df.columns else "ticker"
            industry_col = None
            for col in ["industry", "icbName", "industryName"]:
                if col in industry_df.columns:
                    industry_col = col
                    break

            if industry_col and symbol_col in industry_df.columns:
                mask = industry_df[industry_col].str.contains(
                    "|".join(financial_industries), case=False, na=False
                )
                financial_symbols = industry_df.loc[mask, symbol_col].tolist()

                top100_col = "symbol" if "symbol" in top100.columns else "ticker"
                if top100_col in top100.columns:
                    top100_symbols = set(top100[top100_col].tolist())
                    return [s for s in financial_symbols if s in top100_symbols]
    except Exception as e:
        print(f"[screener] Error filtering financial symbols: {e}")

    return _fallback_financial_symbols()


def _fallback_financial_symbols() -> List[str]:
    """Hardcoded list of major financial symbols when API fails."""
    return [
        "VCB", "BID", "CTG", "TCB", "MBB", "ACB", "VPB", "STB",
        "HDB", "TPB", "LPB", "MSB", "OCB", "EIB", "SHB",
        "SSI", "VCI", "HCM", "VND", "MBS", "BSI",
        "BVH", "BMI", "PVI", "MIG", "BIC",
    ]


def get_multi_sector_symbols() -> Dict[str, List[str]]:
    """
    Get symbols for all tracked sectors from top 100 market cap.
    Returns dict[sector_key] -> list of symbols.
    """
    result = {}
    for sector_key in SECTOR_MAP:
        try:
            df = get_symbols_by_sector(sector_key)
            if df is not None and len(df) > 0:
                col = "symbol" if "symbol" in df.columns else "ticker"
                if col in df.columns:
                    result[sector_key] = df[col].tolist()
                    continue
        except Exception:
            pass
        result[sector_key] = []

    if not any(result.values()):
        result = _fallback_multi_sector()
    return result


def _fallback_multi_sector() -> Dict[str, List[str]]:
    """Hardcoded sector lists when API is unavailable."""
    return {
        "ngan_hang": ["VCB", "BID", "CTG", "TCB", "MBB", "ACB", "VPB", "STB", "HDB", "TPB"],
        "chung_khoan": ["SSI", "VCI", "HCM", "VND", "MBS"],
        "bao_hiem": ["BVH", "BMI", "PVI", "MIG", "BIC"],
        "dau_khi": ["GAS", "PLX", "PVD", "PVS", "OIL", "BSR"],
        "phan_bon": ["DPM", "DCM", "LAS", "BFC"],
        "bat_dong_san": ["VHM", "VIC", "NVL", "KDH", "DXG", "NLG", "HDG", "DIG", "PDR", "BCM"],
        "cang_bien": ["GMD", "VSC", "PHP", "DVP", "SGP"],
        "thep": ["HPG", "HSG", "NKG", "TLH", "POM"],
        "xay_dung": ["CTD", "HBC", "VCG", "ROS"],
        "thuc_pham": ["VNM", "MSN", "SAB", "QNS", "MCH"],
        "cong_nghe": ["FPT", "CMG"],
        "dien": ["POW", "REE", "GEG", "PC1", "NT2"],
    }


def _save_top_list(df: pd.DataFrame, name: str):
    TOP100_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    path = TOP100_DIR / f"{name}_{today}.json"
    df.to_json(path, orient="records", force_ascii=False, indent=2)
    return path


def _load_top_list(name: str) -> Optional[pd.DataFrame]:
    """Load the most recent saved top list."""
    if not TOP100_DIR.exists():
        return None
    files = sorted(TOP100_DIR.glob(f"{name}_*.json"), reverse=True)
    if not files:
        return None
    return pd.read_json(files[0])
