# Dữ liệu ngành Bất động sản

Thư mục này tách biệt với `data/ohlcv` và `data/fundamentals` mặc định.

- `ohlcv/` — nến 1H, 1D, 1W theo từng mã
- `fundamentals/` — BCTC đã tải (CSV)
- `analysis/` — kết quả phân tích (JSON, CSV, Markdown)

Chạy cập nhật:

```bash
cd stock
PYTHONPATH=. python -m vn_stock.scripts.crawl_bat_dong_san
```
