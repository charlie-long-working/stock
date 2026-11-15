"""Mua/bán chủ động (active buy/sell) từ dữ liệu khớp lệnh trong phiên.

Mỗi lệnh khớp có cả người mua lẫn người bán; KBS gắn nhãn bên chủ động (buy = người mua
khớp vào giá chào bán, sell = người bán khớp vào giá chào mua; ato/atc = khớp định kỳ, không phân bên).
Chỉ có dữ liệu phiên gần nhất → phải thu thập mỗi ngày để có lịch sử (collect.py).
"""
