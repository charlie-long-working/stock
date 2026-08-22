"""
Ngành Bất động sản — danh sách mã & thư mục dữ liệu riêng.

Dữ liệu lưu tại: vn_stock/data/sectors/bat_dong_san/
  ├── ohlcv/{MÃ}/1D.csv, 1W.csv, (1H.csv)
  ├── fundamentals/{MÃ}/*.csv
  └── analysis/  (báo cáo JSON/CSV/Markdown do script tạo)
"""

from pathlib import Path

from vn_stock import DATA_DIR

# Mã theo bảng giá ngành BĐS (có thể mở rộng)
BAT_DONG_SAN_SYMBOLS = [
    "DIG", "CEO", "VIC", "VHM", "L14", "HAG", "HQC", "DLG", "SCR", "LCG",
    "TCH", "DXG", "VRE", "NLG", "IJC", "CKG", "PDR", "NVL",
]


def bat_dong_san_data_root() -> Path:
    """Thư mục gốc bundle dữ liệu ngành BĐS."""
    return DATA_DIR / "sectors" / "bat_dong_san"
