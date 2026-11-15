"""
Chỉ số từ lịch sử mua/bán chủ động (data/tape/daily.csv).

nar  = (mua CĐ − bán CĐ) / (mua CĐ + bán CĐ)  — ATO/ATC không tính (không phân bên).
nar_N tính trên TỔNG khối lượng N phiên (không trung bình các tỷ lệ).
Chỉ là bối cảnh: chưa có lịch sử để backtest; dùng làm bộ lọc chỉ sau khi kiểm chứng forward (≥ 120 phiên).
"""

from __future__ import annotations

import html
from typing import Dict, List, Optional, Tuple

import pandas as pd


def _usable(daily: pd.DataFrame) -> pd.DataFrame:
    if daily is None or len(daily) == 0:
        return pd.DataFrame()
    d = daily.copy()
    # dòng lệch KL ngày (reconciled == False) không dùng làm tín hiệu
    if "reconciled" in d.columns:
        d = d[d["reconciled"].astype(str).str.lower() != "false"]
    return d


def tape_features(daily: pd.DataFrame, sym: str, asof: Optional[str] = None) -> Dict:
    d = _usable(daily)
    if len(d) == 0:
        return {"n_days": 0}
    s = d[d["symbol"] == sym.upper()]
    if asof:
        s = s[s["date"] <= asof]
    s = s.sort_values("date")
    out: Dict = {"n_days": int(len(s))}
    for n in (1, 5, 20):
        w = s.tail(n)
        if len(w) < n:
            out[f"nar_{n}"] = None
            continue
        b, se = float(w["buy_vol"].sum()), float(w["sell_vol"].sum())
        out[f"nar_{n}"] = round((b - se) / (b + se), 4) if b + se else None
        out[f"large_net_bn_{n}"] = round(float((w["large_buy_value_bn"] - w["large_sell_value_bn"]).sum()), 2)
    return out


def tape_note(f: Dict) -> Optional[str]:
    """Một dòng cho tin MUA; None khi chưa có dữ liệu."""
    if not f or not f.get("n_days"):
        return None
    parts = []
    for n in (1, 5, 20):
        v = f.get(f"nar_{n}")
        if v is not None:
            parts.append(f"{n}p {v * 100:+.0f}%")
    if not parts:
        return None
    lg = f.get("large_net_bn_5")
    lg_txt = f" · lô lớn 5p {lg:+.1f} tỷ" if lg is not None else ""
    return f"Mua chủ động ròng: {' · '.join(parts)}{lg_txt} (tham khảo, {f['n_days']} phiên dữ liệu)"


def daily_leaders(daily: pd.DataFrame, date: str, k: int = 10, min_value_bn: float = 10.0
                  ) -> Tuple[List[Dict], List[Dict]]:
    d = _usable(daily)
    if len(d) == 0:
        return [], []
    d = d[d["date"] == date].copy()
    if len(d) == 0:
        return [], []
    d["net_bn"] = d["buy_value_bn"] - d["sell_value_bn"]
    d["active_bn"] = d["buy_value_bn"] + d["sell_value_bn"]
    d = d[d["active_bn"] >= min_value_bn]
    cols = ["symbol", "net_bn", "nar", "active_bn"]
    top_buy = d[d["net_bn"] > 0].sort_values("net_bn", ascending=False).head(k)[cols].to_dict("records")
    top_sell = d[d["net_bn"] < 0].sort_values("net_bn").head(k)[cols].to_dict("records")
    return top_buy, top_sell


def format_leaders(date: str, top_buy: List[Dict], top_sell: List[Dict], coverage: Optional[str] = None) -> Optional[str]:
    if not top_buy and not top_sell:
        return None

    def line(r: Dict) -> str:
        nar = f"{r['nar'] * 100:+.0f}%" if r.get("nar") is not None else "—"
        return f"{html.escape(str(r['symbol']))} {r['net_bn']:+,.1f} tỷ ({nar})"

    lines = [f"💹 <b>Dòng tiền chủ động {html.escape(date)}</b>",
             "<b>Mua chủ động ròng:</b> " + (", ".join(line(r) for r in top_buy) or "—"),
             "<b>Bán chủ động ròng:</b> " + (", ".join(line(r) for r in top_sell) or "—")]
    if coverage:
        lines.append(f"<i>{html.escape(coverage)}</i>")
    lines.append("<i>Mua/bán chủ động = bên chủ động khớp lệnh (không tính ATO/ATC). Tham khảo, chưa kiểm chứng như tín hiệu.</i>")
    return "\n".join(lines)
