"""
Backtest các setup trên kho giá điều chỉnh (100 mã Stock Intelligence, 2012 → nay).

Quy ước (giống Stock Intelligence, nhưng engine riêng):
- Tín hiệu tại đóng cửa t → vào mở cửa t+1 × (1 + trượt giá). Bỏ nếu mở cửa t+1 ≥ close t × 1,06 (gần trần, khó khớp).
- Thoát qua `setups.exits.step` (T+2, SL/TP/trailing/cấu trúc) → giá thoát × (1 − trượt giá).
- Phí mua 0,15%, phí bán 0,15%, thuế bán 0,1%, trượt giá 0,1% mỗi chiều (đọc data/intel/config nếu có).
- Mỗi mã tối đa 1 vị thế. Bỏ lệnh có biến động > 16% trong 1 phiên (sự kiện doanh nghiệp).
- Giai đoạn: train < 2022, validate 2022–2023, ngoài mẫu (OOS) ≥ 2024 (theo ngày tín hiệu).
- Lớp danh mục: tối đa 5 vị thế cùng lúc, trùng ngày ưu tiên rvol cao; tỷ trọng = min(20%, 1% / rủi ro).
Lưu ý: chọn 100 mã của HÔM NAY áp cho quá khứ → thiên lệch sống sót (ghi trong báo cáo).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from vn_stock import DATA_DIR
from vn_stock.setups import base_breakout as B
from vn_stock.setups import divergence as V
from vn_stock.setups import features as F
from vn_stock.setups.exits import ExitParams, Position, init_target, step
from vn_stock.setups.sizing import CAP_PER_NAME, MAX_POSITIONS, RISK_PER_TRADE
from vn_stock.strategies.macd_rsi import MACDRSIParams, precompute_macd_rsi

DEFAULT_COSTS = {"fee_buy": 0.0015, "fee_sell": 0.0015, "tax_sell": 0.001, "slippage": 0.001}
TRAIN_END = "2022-01-01"
OOS_START = "2024-01-01"
CHASE_MAX = 1.06
CA_JUMP = 0.16


def load_costs() -> Dict[str, float]:
    p = DATA_DIR.parent / "intel" / "config.json"
    try:
        bt = json.loads(p.read_text(encoding="utf-8")).get("backtest", {})
        return {k: float(bt.get(k, v)) for k, v in DEFAULT_COSTS.items()}
    except (OSError, ValueError):
        return dict(DEFAULT_COSTS)


@dataclass(frozen=True)
class Config:
    setup: str                      # base_breakout | div_bull | macd_rsi_atr
    params: Tuple[Tuple[str, object], ...]
    exit: ExitParams
    regime_filter: bool = False

    @property
    def id(self) -> str:
        raw = json.dumps([self.setup, list(self.params), self.exit.to_dict(), self.regime_filter], sort_keys=True,
                         default=str)
        return f"{self.setup}-{hashlib.sha1(raw.encode()).hexdigest()[:8]}"

    def to_dict(self) -> Dict:
        return {"id": self.id, "setup": self.setup, "params": dict(self.params), "exit": self.exit.to_dict(),
                "regime_filter": self.regime_filter}


def config_from_dict(d: Dict) -> Config:
    return Config(d["setup"], tuple(sorted(d["params"].items())), ExitParams(**d["exit"]), d.get("regime_filter", False))


# ---------------------------------------------------------------- signals

def signals(cfg: Config, df: pd.DataFrame, feats: pd.DataFrame) -> pd.DataFrame:
    """entry (bool), stop (float tuyệt đối), rvol, base_low, bear_div, signal_exit — tất cả biết tại đóng cửa t."""
    prm = dict(cfg.params)
    n = len(df)
    out = pd.DataFrame(index=df.index)
    out["base_low"] = np.nan
    out["bear_div"] = False
    out["signal_exit"] = False
    if cfg.setup == "base_breakout":
        b = B.detect(df, B.BaseParams(**prm), feats=feats)
        out["entry"], out["stop"], out["rvol"], out["base_low"] = b["breakout"], b["stop"], b["rvol50"], b["base_low"]
    elif cfg.setup == "div_bull":
        v = V.detect(df, V.DivSetupParams(**prm), feats=feats)
        out["entry"], out["stop"], out["rvol"], out["bear_div"] = v["entry"], v["stop"], v["rvol50"], v["bear_div"]
    elif cfg.setup == "macd_rsi_atr":
        hi, lo, cl = (df[c].to_numpy(float) for c in ("high", "low", "close"))
        mp = MACDRSIParams(**prm) if prm else MACDRSIParams()
        hist, rsi_arr, atr_arr = precompute_macd_rsi(hi, lo, cl, mp)
        prev = np.r_[np.nan, hist[:-1]]
        ent = (prev <= 0) & (hist > 0) & (rsi_arr < mp.rsi_overbought)
        ent &= (feats["value_avg20_bn"] >= 10).fillna(False).to_numpy()
        ent[: min(260, n)] = False
        out["entry"] = ent
        out["stop"] = cl - mp.atr_sl_mult * atr_arr
        out["rvol"] = feats["rvol50"]
        out["signal_exit"] = (prev >= 0) & (hist < 0)
    else:
        raise ValueError(cfg.setup)
    out["entry"] = out["entry"].fillna(False).astype(bool)
    return out


# ---------------------------------------------------------------- simulate

def _net_ret(entry_px: float, exit_px: float, costs: Dict[str, float]) -> float:
    return exit_px * (1 - costs["fee_sell"] - costs["tax_sell"]) / (entry_px * (1 + costs["fee_buy"])) - 1


def simulate_symbol(sym: str, df: pd.DataFrame, sig: pd.DataFrame, cfg: Config, costs: Dict[str, float],
                    bearish: Optional[pd.Series] = None, idx_close: Optional[pd.Series] = None) -> List[Dict]:
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    t_arr = df["time"].to_numpy()
    n = len(df)
    entry = sig["entry"].to_numpy()
    stop_arr, rvol = sig["stop"].to_numpy(float), sig["rvol"].to_numpy(float)
    base_low, bear, sx = sig["base_low"].to_numpy(float), sig["bear_div"].to_numpy(bool), sig["signal_exit"].to_numpy(bool)
    atr = F.atr(df).to_numpy(float)
    prev_c = np.r_[np.nan, c[:-1]]
    jump = (np.abs(c / prev_c - 1) > CA_JUMP) | (np.abs(o / prev_c - 1) > CA_JUMP)
    bear_dates = None
    if cfg.regime_filter and bearish is not None:
        bear_dates = bearish.reindex(pd.to_datetime(df["time"])).fillna(False).to_numpy(bool)
    slip = costs["slippage"]
    trades: List[Dict] = []
    t = 0
    cand = np.nonzero(entry)[0]
    ci = 0
    while ci < len(cand):
        t = cand[ci]
        ci += 1
        if t + 1 >= n:
            break
        if bear_dates is not None and bear_dates[t]:
            continue
        if o[t + 1] >= c[t] * CHASE_MAX:
            continue
        entry_px = o[t + 1] * (1 + slip)
        stop = stop_arr[t]
        if not np.isfinite(stop) or stop >= entry_px:
            continue
        pos = init_target(Position(sym, cfg.setup, t + 1, entry_px, float(stop), float(atr[t])), cfg.exit)
        ev = None
        for i in range(t + 1, n):
            flags = {"breakdown": bool(np.isfinite(base_low[t]) and c[i] < base_low[t] * 0.995),
                     "bear_div": bool(bear[i]), "signal_exit": bool(sx[i])}
            ev = step(pos, i, o[i], h[i], l[i], c[i], cfg.exit, flags)
            if ev:
                break
        if ev is None:  # còn mở đến hết dữ liệu → không tính
            break
        exit_px = ev.px * (1 - slip)
        ca = bool(jump[t + 1: ev.i + 1].any())
        ret = _net_ret(entry_px, exit_px, costs)
        ir = None
        if idx_close is not None:
            a = idx_close.asof(pd.Timestamp(t_arr[t + 1]))
            b = idx_close.asof(pd.Timestamp(t_arr[ev.i]))
            ir = float(b / a - 1) if a and b and np.isfinite(a) and np.isfinite(b) else None
        if not ca:
            trades.append({
                "symbol": sym, "setup": cfg.setup, "config": cfg.id,
                "date": pd.Timestamp(t_arr[t]).strftime("%Y-%m-%d"),
                "entry_date": pd.Timestamp(t_arr[t + 1]).strftime("%Y-%m-%d"),
                "exit_date": pd.Timestamp(t_arr[ev.i]).strftime("%Y-%m-%d"),
                "entry_px": round(entry_px, 4), "exit_px": round(exit_px, 4), "ret": ret,
                "r_mult": (exit_px - entry_px) / pos.r, "exit": ev.reason, "bars": ev.i - (t + 1) + 1,
                "rvol": float(rvol[t]) if np.isfinite(rvol[t]) else 0.0,
                "risk": (entry_px - pos.initial_stop) / entry_px, "idx_ret": ir,
            })
        # vị thế tiếp theo chỉ sau khi đã thoát
        while ci < len(cand) and cand[ci] <= ev.i:
            ci += 1
    return trades


# ---------------------------------------------------------------- stats

def period(date: str) -> str:
    return "train" if date < TRAIN_END else ("validate" if date < OOS_START else "oos")


def stats(tr: pd.DataFrame) -> Dict:
    if tr is None or len(tr) == 0:
        return {"n": 0}
    r = tr["ret"].to_numpy(float)
    gains, losses = r[r > 0].sum(), -r[r < 0].sum()
    sd = r.std(ddof=1) if len(r) > 1 else 0.0
    return {
        "n": int(len(r)), "win": round(float((r > 0).mean()), 4), "mean": round(float(r.mean()), 5),
        "median": round(float(np.median(r)), 5), "pf": round(float(gains / losses), 3) if losses > 0 else None,
        "t": round(float(r.mean() / sd * np.sqrt(len(r))), 2) if sd > 0 else None,
        "avg_r": round(float(tr["r_mult"].mean()), 3), "avg_bars": round(float(tr["bars"].mean()), 1),
        "symbols": int(tr["symbol"].nunique()),
    }


def portfolio(tr: pd.DataFrame, max_pos: int = MAX_POSITIONS) -> Tuple[pd.DataFrame, Dict]:
    """Nhận lệnh khi < max_pos đang mở (theo ngày vào/ra); tỷ trọng min(20%, 1%/rủi ro); vốn ghép lãi theo ngày ra."""
    if len(tr) == 0:
        return tr, {"n": 0}
    t = tr.sort_values(["entry_date", "rvol"], ascending=[True, False])
    open_exits: List[str] = []
    keep = []
    for idx, row in t.iterrows():
        open_exits = [e for e in open_exits if e >= row["entry_date"]]
        if len(open_exits) < max_pos:
            keep.append(idx)
            open_exits.append(row["exit_date"])
    acc = t.loc[keep].copy()
    acc["w"] = np.minimum(CAP_PER_NAME, RISK_PER_TRADE / acc["risk"].clip(lower=1e-6))
    eq = (1 + (acc.sort_values("exit_date")["w"] * acc.sort_values("exit_date")["ret"])).cumprod()
    dd = float((eq / eq.cummax() - 1).min()) if len(eq) else 0.0
    years = max((pd.Timestamp(acc["exit_date"].max()) - pd.Timestamp(acc["entry_date"].min())).days / 365.25, 0.25)
    cagr = float(eq.iloc[-1] ** (1 / years) - 1) if len(eq) else 0.0
    return acc, {"n": int(len(acc)), "final_equity": round(float(eq.iloc[-1]), 4), "cagr": round(cagr, 4),
                 "max_dd": round(dd, 4), "years": round(years, 2)}


def block_bootstrap_lb(rets: np.ndarray, block: int = 20, n_iter: int = 10000, q: float = 0.025, seed: int = 11) -> Optional[float]:
    r = np.asarray(rets, float)
    if len(r) < 10:
        return None
    rng = np.random.default_rng(seed)
    nb = int(np.ceil(len(r) / block))
    starts_max = max(len(r) - block, 0)
    means = np.empty(n_iter)
    for k in range(n_iter):
        st = rng.integers(0, starts_max + 1, nb)
        sample = np.concatenate([r[s:s + block] for s in st])[: len(r)]
        means[k] = sample.mean()
    return float(np.quantile(means, q))


def random_baseline(tr: pd.DataFrame, data: Dict[str, pd.DataFrame], costs: Dict[str, float],
                    n_iter: int = 500, seed: int = 7) -> np.ndarray:
    """Cùng mã, cùng năm, cùng số phiên giữ; vào mở cửa ngẫu nhiên, ra đóng cửa sau đúng số phiên đó."""
    rng = np.random.default_rng(seed)
    if len(tr) == 0:
        return np.array([])
    prepared = []
    for _, row in tr.iterrows():
        df = data[row["symbol"]]
        yr = pd.to_datetime(df["time"]).dt.year.to_numpy()
        idx = np.nonzero(yr == int(row["entry_date"][:4]))[0]
        hold = int(row["bars"])
        idx = idx[idx + hold - 1 < len(df)]
        if len(idx) == 0:
            continue
        prepared.append((df["open"].to_numpy(float), df["close"].to_numpy(float), idx, hold))
    slip = costs["slippage"]
    means = np.empty(n_iter)
    for k in range(n_iter):
        rs = []
        for o, c, idx, hold in prepared:
            e = idx[rng.integers(0, len(idx))]
            rs.append(_net_ret(o[e] * (1 + slip), c[e + hold - 1] * (1 - slip), costs))
        means[k] = np.mean(rs) if rs else np.nan
    return means


def concentration(tr: pd.DataFrame) -> Dict:
    if len(tr) == 0:
        return {"top_share": None, "pf_ex_top3": None}
    by = tr.groupby("symbol")["ret"].sum().sort_values(ascending=False)
    net = float(tr["ret"].sum())
    top_share = float(by.iloc[0] / net) if net > 0 else None
    rest = tr[~tr["symbol"].isin(by.index[:3])]
    return {"top_share": None if top_share is None else round(top_share, 3), "pf_ex_top3": stats(rest).get("pf"),
            "top3": by.index[:3].tolist()}


# ---------------------------------------------------------------- gates

GATES = {
    "min_trades": 60, "min_accepted": 40, "pf": 1.2, "beat_random_pct": 90, "pf_ex_top3": 1.0,
    "max_symbol_share": 0.25, "validate_pf": 1.0, "oos_years_positive": 2, "max_dd": -0.20, "pf_2x_costs": 1.05,
}


def evaluate_gates(oos: pd.DataFrame, val: pd.DataFrame, oos_2x: pd.DataFrame, rand_means: np.ndarray,
                   port: Dict) -> Dict:
    s = stats(oos)
    conc = concentration(oos)
    lb = block_bootstrap_lb(oos.sort_values("entry_date")["ret"].to_numpy()) if len(oos) else None
    rp = float(np.nanpercentile(rand_means, GATES["beat_random_pct"])) if len(rand_means) else None
    yrs = oos.assign(y=oos["entry_date"].str[:4]).groupby("y")["ret"].mean() if len(oos) else pd.Series(dtype=float)
    checks = {
        "trades>=60": s.get("n", 0) >= GATES["min_trades"],
        "accepted>=40": port.get("n", 0) >= GATES["min_accepted"],
        "pf>=1.2": (s.get("pf") or 0) >= GATES["pf"],
        "bootstrap_lb>0": lb is not None and lb > 0,
        "beats_random_p90": rp is not None and s.get("mean", -1) > rp,
        "pf_ex_top3>=1": (conc["pf_ex_top3"] or 0) >= GATES["pf_ex_top3"],
        "symbol_share<=25%": conc["top_share"] is not None and conc["top_share"] <= GATES["max_symbol_share"],
        "validate_pf>=1": (stats(val).get("pf") or 0) >= GATES["validate_pf"],
        "oos_years_positive>=2": int((yrs > 0).sum()) >= GATES["oos_years_positive"],
        "portfolio_dd<=20%": port.get("max_dd", -1) >= GATES["max_dd"],
        "pf_2x_costs>=1.05": (stats(oos_2x).get("pf") or 0) >= GATES["pf_2x_costs"],
    }
    if all(checks.values()):
        verdict = "ship"
    elif (s.get("pf") or 0) >= 1.0 and s.get("mean", 0) > 0:
        verdict = "watch"
    else:
        verdict = "off"
    return {"verdict": verdict, "checks": checks, "oos": s, "bootstrap_lb": lb, "random_p90": rp,
            "concentration": conc, "oos_by_year": {k: round(float(v), 5) for k, v in yrs.items()}, "portfolio": port}


# ---------------------------------------------------------------- grid

BASE_STRICT = {}
BASE_RELAXED = {"bbw_rank_max": 0.6, "dryup_max": 1.0, "drift_frac": 1.0, "height_atr_k": 1.8,
                "max_height": ((20, 0.18), (40, 0.22), (60, 0.27))}
EXIT_A = ExitParams(mode="A", tp_r=2.0, time_stop=20)
EXIT_B = ExitParams(mode="B", time_stop=40)


def grid() -> List[Config]:
    cfgs: List[Config] = []
    for prof in (BASE_STRICT, BASE_RELAXED):
        for rv in (1.5, 2.0):
            for ex in (EXIT_A, EXIT_B):
                for reg in (False, True):
                    prm = dict(prof, rvol_min=rv)
                    cfgs.append(Config("base_breakout", tuple(sorted(prm.items())), ex, reg))
    for trig in ("immediate", "confirm"):
        for s200 in (True, False):
            for ex in (ExitParams(mode="A", tp_r=2.0, time_stop=15, use_bear_div=True),
                       ExitParams(mode="B", time_stop=40, use_bear_div=True)):
                cfgs.append(Config("div_bull", (("require_sma200", s200), ("trigger", trig)), ex, False))
    return cfgs


BENCHMARK = Config("macd_rsi_atr", (), ExitParams(mode="A", tp_r=2.5 / 1.5, time_stop=60, use_breakdown=False,
                                                   use_signal_exit=True), False)


def run_config(cfg: Config, data: Dict[str, pd.DataFrame], feats: Dict[str, pd.DataFrame], costs: Dict[str, float],
               bearish: Optional[pd.Series], idx_close: Optional[pd.Series]) -> pd.DataFrame:
    rows: List[Dict] = []
    for sym, df in data.items():
        sig = signals(cfg, df, feats[sym])
        rows += simulate_symbol(sym, df, sig, cfg, costs, bearish, idx_close)
    tr = pd.DataFrame(rows)
    if len(tr):
        tr["period"] = tr["date"].map(period)
    return tr


def select(results: Dict[str, Dict], configs: Dict[str, Config], setup: str, min_train: int = 80) -> Optional[str]:
    """Chọn trên train/validate (không nhìn OOS): kỳ vọng train cao nhất trong các cấu hình đủ ≥ min_train lệnh,
    validate PF ≥ 1,05 và trung vị validate PF của các cấu hình lân cận (khác 1 chiều) ≥ 1,05."""
    cands = [k for k, c in configs.items() if c.setup == setup and results[k]["train"].get("n", 0) >= min_train]
    ok = []
    for k in cands:
        if (results[k]["validate"].get("pf") or 0) < 1.05:
            continue
        neigh = [results[j]["validate"].get("pf") or 0 for j in configs
                 if j != k and configs[j].setup == setup and _differs_by_one(configs[k], configs[j])]
        if neigh and float(np.median(neigh)) < 1.05:
            continue
        ok.append(k)
    if not ok:
        return None
    return max(ok, key=lambda k: results[k]["train"].get("mean", -1))


def _differs_by_one(a: Config, b: Config) -> bool:
    da = {**dict(a.params), **{f"exit_{k}": v for k, v in a.exit.to_dict().items()}, "regime": a.regime_filter}
    db = {**dict(b.params), **{f"exit_{k}": v for k, v in b.exit.to_dict().items()}, "regime": b.regime_filter}
    keys = set(da) | set(db)
    return sum(1 for k in keys if da.get(k) != db.get(k)) <= 2  # exit A↔B đổi 2 trường (mode, time_stop)
