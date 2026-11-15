"""% vốn tối đa cho một lệnh theo rủi ro cố định (không lưu số vốn của người dùng)."""

from __future__ import annotations

MAX_POSITIONS = 5
RISK_PER_TRADE = 0.01
CAP_PER_NAME = 0.20


def max_pct_capital(entry: float, stop: float, risk: float = RISK_PER_TRADE, cap: float = CAP_PER_NAME) -> float:
    """Tỷ trọng vốn sao cho chạm SL mất đúng `risk` vốn; kẹp ở `cap`. Trả về phân số (0.125 = 12,5%)."""
    if entry <= 0 or stop is None or stop >= entry:
        return 0.0
    dist = (entry - stop) / entry
    return float(min(cap, risk / dist))


def sizing_note(entry: float, stop: float) -> str:
    w = max_pct_capital(entry, stop)
    return (f"Tối đa ~{w * 100:.1f}% vốn (rủi ro {RISK_PER_TRADE * 100:.0f}% vốn nếu chạm SL; "
            f"trần {CAP_PER_NAME * 100:.0f}%/mã; tối đa {MAX_POSITIONS} mã)")
