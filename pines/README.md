# Pine Script — so khớp backtest `vn_stock`

Các file `.pine` dùng trên **TradingView** (Strategy Tester) để đối chiếu tín hiệu với Python.

| File | Strategy Python | Ghi chú |
|------|------------------|--------|
| `macd_rsi_vn.pine` | `macd_rsi.py` | Histogram MACD cắt lên 0 + RSI &lt; 70; SL/TP ATR 1.5× / 2.5×; exit khi hist cắt xuống 0. |
| `ma_crossover_vn.pine` | `ma_crossover.py` | SMA 20/50 (mặc định), giá &gt; MA chậm, volume &gt; SMA(volume,20); SL/TP ATR 2× / 3×. |
| `regime_fusion_approx_vn.pine` | `regime_fusion.py` | **Chỉ xấp xỉ:** cùng regime (`regime.py`) + FVG bull + demand zone như `technical.py`. **Không** có bull order block. |

## Cách dùng

1. TradingView → **Pine Editor** → dán nội dung file → **Add to chart**.
2. Mở **Strategy Tester** để xem P&amp;L (phí mặc định 0.1% — chỉnh trong code).
3. `process_orders_on_close=true` giống hành vi “đóng nến” (thường hợp khung ngày).

## Khác biệt so với Python (bình thường)

- **RSI / ATR / MACD:** TradingView dùng bộ lọc Wilder chuẩn; Python dùng EMA/RMA tự viết — có thể lệch nhẹ vài điểm hoặc 1 bar.
- **Dữ liệu & giờ giao dịch:** HOSE/HNX trên TV có thể khác nguồn CSV trong repo → số lệnh có thể không trùng 100%.
- **Regime fusion:** Pine bỏ **order block**; vòng lặp FVG/zone là bản rút gọn — dùng để **so hướng**, không kỳ vọng khớp từng lệnh với `run_backtest`.

## Tham số mặc định

Đồng bộ với `MACDRSIParams`, `MACrossParams`, và lookback mặc định trong `regime_fusion_signal(...)` (50/30/50).
