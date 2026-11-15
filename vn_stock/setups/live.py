"""
Áp các setup đã khoá (setups/config.json) cho nến ngày gần nhất — dùng trong run_swing_vn.

verdict ship  → Signal MUA (entry tham chiếu = close, SL/TP theo cấu hình) + vào sổ lệnh giấy
verdict watch → mục "Theo dõi" (không có mức giá vào lệnh, không vào sổ)
verdict off   → bỏ qua
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from vn_stock.setups import base_breakout as B
from vn_stock.setups import divergence as V
from vn_stock.setups.exits import ExitParams
from vn_stock.setups.features import add_common
from vn_stock.strategies.macd_rsi import precompute_macd_rsi

CONFIG = Path(__file__).resolve().parent / "config.json"
NAMES = {"base_breakout": "Phá nền giá đi ngang", "div_bull": "Phân kỳ dương MACD/RSI"}
# Chiến lược cũ (đã chạy live trước khi có backtest); kết luận cũng đọc từ config.json
LEGACY_NAMES = {"macd_rsi_atr": "MACD+RSI (ATR)"}


def verdict(strategy: str, live_cfg: Dict) -> Optional[str]:
    return (live_cfg.get(strategy) or {}).get("verdict")


def display_name(strategy: str) -> str:
    return NAMES.get(strategy) or LEGACY_NAMES.get(strategy) or strategy


def load_live_config(path: Path = CONFIG) -> Dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8")).get("setups", {})
    except (OSError, ValueError):
        return {}


def exit_params(setup: str, live_cfg: Dict) -> Optional[ExitParams]:
    c = (live_cfg.get(setup) or {}).get("config")
    return ExitParams(**c["exit"]) if c else None


def evidence(setup: str, live_cfg: Dict) -> Optional[str]:
    return (live_cfg.get(setup) or {}).get("evidence")


def _params(cfg: Dict) -> Dict:
    p = dict(cfg.get("params", {}))
    if "max_height" in p:
        p["max_height"] = tuple(tuple(x) for x in p["max_height"])
    return p


def scan_setups(sym: str, df: pd.DataFrame, live_cfg: Dict, feats: Optional[pd.DataFrame] = None
                ) -> Tuple[List[Dict], List[Dict]]:
    """(ship, watch) cho nến cuối. Mỗi phần tử: setup, close, stop, target|None, base_low|None, note."""
    ship, watch = [], []
    if len(df) < 260 or not live_cfg:
        return ship, watch
    feats = feats if feats is not None else add_common(df)
    close = float(df["close"].iloc[-1])
    for setup, info in live_cfg.items():
        verdict = info.get("verdict")
        if setup not in NAMES or verdict not in ("ship", "watch"):
            continue
        cfg = info["config"]
        item = None
        if setup == "base_breakout":
            out = B.detect(df, B.BaseParams(**_params(cfg)), feats=feats)
            last = out.iloc[-1]
            if bool(last["breakout"]):
                item = {"setup": setup, "close": close, "stop": float(last["stop"]),
                        "base_low": float(last["base_low"]),
                        "note": (f"nền {int(last['base_n'])} phiên {last['base_low']:,.2f}–{last['base_high']:,.2f} "
                                 f"(biên độ {last['base_height'] * 100:.0f}%, volume nền {last['base_dry']:.2f}× trước nền)"
                                 f", phá nền với rvol {last['rvol50']:.1f}")}
        elif setup == "div_bull":
            out = V.detect(df, V.DivSetupParams(**_params(cfg)), feats=feats)
            last = out.iloc[-1]
            if bool(last["entry"]):
                item = {"setup": setup, "close": close, "stop": float(last["stop"]), "base_low": None,
                        "note": f"phân kỳ dương MACD/RSI (đáy xác nhận 5 phiên trước), rủi ro {last['risk'] * 100:.1f}%"}
        if item is None:
            continue
        ep = ExitParams(**cfg["exit"])
        item["target"] = item["close"] + ep.tp_r * (item["close"] - item["stop"]) if ep.mode == "A" else None
        (ship if verdict == "ship" else watch).append(item)
    return ship, watch


def flag_arrays(df: pd.DataFrame) -> Dict[str, np.ndarray]:
    """Cờ thoát theo cấu trúc cho sổ lệnh: phân kỳ âm, MACD hist cắt xuống 0."""
    hi, lo, cl = (df[c].to_numpy(float) for c in ("high", "low", "close"))
    out = {"bear_div": np.zeros(len(df), bool), "signal_exit": np.zeros(len(df), bool)}
    if len(df) < 60:
        return out
    hist, _, _ = precompute_macd_rsi(hi, lo, cl)
    prev = np.r_[np.nan, hist[:-1]]
    out["signal_exit"] = (prev >= 0) & (hist < 0)
    try:
        out["bear_div"] = V.detect(df, V.DivSetupParams(require_sma200=False))["bear_div"].to_numpy(bool)
    except Exception:  # noqa: BLE001 — thiếu dữ liệu cho phân kỳ thì không dùng cờ này
        pass
    return out
