"""Setup giao dịch nhân quả (không nhìn trước) cho cổ phiếu VN, dùng chung cho backtest và bot live.

- features.py      : chỉ báo (pandas/numpy thuần, không phụ thuộc code chưa commit)
- base_breakout.py : nền giá đi ngang + phá nền / gãy nền
- divergence.py    : phân kỳ MACD/RSI (bọc strategies/div_macd_rsi)
- exits.py         : một engine thoát lệnh (SL/TP/trailing/thời gian/cấu trúc, T+2) cho cả backtest và sổ lệnh
- sizing.py        : % vốn tối đa theo rủi ro
- config.json      : tham số đã khoá + kết luận ship/watch/off do backtest ghi (không chỉnh tay theo dữ liệu ngoài mẫu)
"""
