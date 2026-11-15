"""Gom dữ liệu cho trang tĩnh (site/index.html): tin tức, BTC/ETH, chứng khoán VN, vàng/bạc.

Nguồn (đều có thật, có thời điểm):
- Tin: SQLite của daily-brief (RSS) – cụm tin 24 giờ.
- Crypto: Trading-bot (nến Binance/Bybit, tín hiệu OI live I/K, funding, USDT.D) chạy bằng venv Trading-bot
  qua scripts/crypto_snapshot.py; chỉ báo + SMC + điểm kỹ thuật tính bằng vn_stock.intel.
- Chứng khoán VN: kết quả quét Stock Intelligence (stock/vn_stock/data/intel/latest.json) + OHLCV local.
- Vàng/bạc: Yahoo GC=F / SI=F (hợp đồng tương lai COMEX), tỷ giá Vietcombank, giá quy đổi VND/lượng.
Khuyến nghị crypto/kim loại chỉ có khung NGẮN HẠN theo kỹ thuật (không có dữ liệu cơ bản), ghi rõ.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from brief import compose, db, market, news
from brief.config import DB_PATH, TZ, WORKSPACE, load_settings

TB_ROOT = WORKSPACE / "Trading-bot"
STOCK_ROOT = WORKSPACE / "stock"
BARS = 250


def _r(x, nd=2):
    try:
        if x is None:
            return None
        v = float(x)
        return None if not np.isfinite(v) else round(v, nd)
    except (TypeError, ValueError):
        return None


def _series(ind: pd.DataFrame, n: int = BARS, nd: int = 2) -> Dict[str, Any]:
    """Cột cho biểu đồ: thời gian + OHLCV + đường chỉ báo (đã tính trên toàn lịch sử, cắt n phiên cuối)."""
    t = ind.iloc[-n:]
    col = lambda c: [_r(v, nd) for v in t[c]] if c in t else []  # noqa: E731
    return {"t": [str(pd.Timestamp(x).date()) for x in t["time"]], "o": col("open"), "h": col("high"),
            "l": col("low"), "c": col("close"), "v": [_r(v, 0) for v in t["volume"]],
            "ema20": col("ema20"), "sma50": col("sma50"), "sma200": col("sma200"),
            "span_a": col("span_a"), "span_b": col("span_b"), "rsi": col("rsi14"), "macd_hist": col("hist")}


def _analyze_ohlcv(df: pd.DataFrame, unit_mult: float, ccy: str, nd: int) -> Dict[str, Any]:
    from vn_stock.intel import flow as FL, indicators as I, scoring as SC, smc as SM
    from vn_stock.intel.data import load_config, to_py
    cfg = load_config()
    ind = I.compute_all(df)
    tech = I.interpret(ind)
    smc = SM.analyze(df)
    fl = FL.analyze(ind, None, "", use_foreign=False)
    price = float(df["close"].iloc[-1]) * unit_mult
    lv = SC.levels(price, tech, smc, {}, unit_mult=unit_mult, ccy=ccy, nd=nd)
    comp = {"technical": tech.get("score"), "smc": smc.get("score"), "flow": fl.get("score"),
            "fundamental": None, "valuation": None}
    rec = SC.recommend(comp, {k: 1.0 for k in comp}, "n/a", cfg,
                       {"tech": tech, "smc": smc, "levels": lv, "unit_mult": unit_mult, "ccy": ccy})
    c = df["close"].astype(float)
    chg = lambda n: _r((c.iloc[-1] / c.iloc[-1 - n] - 1) * 100) if len(c) > n else None  # noqa: E731
    return to_py({"price": price, "as_of": str(pd.Timestamp(df["time"].iloc[-1]).date()),
                  "chg": {"1d": chg(1), "7d": chg(7), "30d": chg(30), "90d": chg(90), "365d": chg(365)},
                  "tech": tech, "smc": _smc_brief(smc), "flow": fl, "levels": lv,
                  "short": rec["short"], "scores": comp, "chart": _series(ind, BARS, nd)})


def _smc_brief(s: Dict[str, Any]) -> Dict[str, Any]:
    if s.get("status") != "ok":
        return s
    return {"trend": s.get("trend"), "score": s.get("score"), "breaks": s.get("recent_breaks_30d", [])[-3:],
            "last_breaks": s.get("breaks", [])[-3:], "premium_discount": s.get("premium_discount"),
            "ob_bull": s.get("order_blocks_active", {}).get("bullish", [])[-2:],
            "ob_bear": s.get("order_blocks_active", {}).get("bearish", [])[-2:],
            "sweeps": s.get("liquidity_sweeps_20d", [])[-2:], "fvg_open": s.get("fvg_open", [])[-3:]}


def _norm(c: List[Optional[float]]) -> List[Optional[float]]:
    base = next((x for x in c if x), None)
    return [None if not x or not base else round(x / base * 100, 2) for x in c]


# ---------------------------------------------------------------- tin tức
def news_section(path: Path = DB_PATH, hours: int = 24) -> Dict[str, Any]:
    s = load_settings()
    summary = news.collect(path=path)
    end = db.now_utc()
    start = end - timedelta(hours=hours)
    from brief import market as M
    wl, _ = M.load_watchlist(s)
    caps = {k: v * 4 for k, v in s["brief"]["caps"].items()}
    cl = news.select(start, end, set(), wl, caps, 60, s["brief"]["dedup_jaccard"], path)
    items = []
    for c in cl:
        items.append({"title": c.title, "summary": "" if c.title_only else (c.summary or "")[:280], "url": c.url,
                      "section": c.section, "section_vi": news.SECTION_TITLES.get(c.section, c.section),
                      "sources": list(dict.fromkeys(compose.SOURCE_NAMES.get(x, x) for x in c.sources)),
                      "publishers": len(c.publishers), "published": db.iso(c.published),
                      "published_vn": compose.fmt_local(c.published), "title_only": c.title_only})
    by_sec: Dict[str, int] = {}
    by_src: Dict[str, int] = {}
    for it in items:
        by_sec[it["section_vi"]] = by_sec.get(it["section_vi"], 0) + 1
        for so in it["sources"]:
            by_src[so] = by_src.get(so, 0) + 1
    with db.connect(path) as con:
        n24 = con.execute("SELECT COUNT(*) FROM items WHERE published_at >= ?", (db.iso(start),)).fetchone()[0]
    return {"window": [compose.fmt_local(start), compose.fmt_local(end)], "items": items,
            "by_section": by_sec, "by_source": dict(sorted(by_src.items(), key=lambda x: -x[1])[:15]),
            "raw_items_24h": n24,
            "sources_status": {k: v["status"] for k, v in summary.items()},
            "note": "Cụm tin đã lọc trùng (URL + tiêu đề), xếp theo độ ưu tiên nguồn, số nguồn cùng đưa, từ khoá, độ mới"}


# ---------------------------------------------------------------- crypto
def _crypto_snapshot(timeout: int = 420) -> Dict[str, Any]:
    py = TB_ROOT / ".venv" / "bin" / "python"
    script = Path(__file__).resolve().parents[1] / "scripts" / "crypto_snapshot.py"
    if not py.exists():
        return {"errors": [f"không thấy venv Trading-bot: {py}"], "symbols": {}}
    env = {**os.environ, "PYTHONPATH": str(TB_ROOT)}
    p = subprocess.run([str(py), str(script)], cwd=str(TB_ROOT), env=env, capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        return {"errors": [f"crypto_snapshot rc={p.returncode}: {p.stderr[-300:]}"], "symbols": {}}
    return json.loads(p.stdout)


def crypto_section() -> Dict[str, Any]:
    snap = _crypto_snapshot()
    out: Dict[str, Any] = {"source": snap.get("source"), "generated_at": snap.get("generated_at"),
                           "errors": list(snap.get("errors", [])), "assets": {}, "usdt_d": snap.get("usdt_d")}
    today_utc = datetime.now(timezone.utc).date().isoformat()
    closes = {}
    for sym, d in snap.get("symbols", {}).items():
        rows = d.get("daily") or []
        if not rows:
            continue
        df = pd.DataFrame(rows, columns=["time", "open", "high", "low", "close", "volume"])
        forming = df["time"].iloc[-1] >= today_utc
        if forming:
            df = df.iloc[:-1]   # nến ngày UTC chưa đóng – không dùng để tính
        df["time"] = pd.to_datetime(df["time"])
        a = _analyze_ohlcv(df, 1.0, "USD", 2)
        a["symbol"] = sym
        a["name"] = {"BTCUSDT": "Bitcoin", "ETHUSDT": "Ethereum"}.get(sym, sym)
        a["last_trade"] = rows[-1][4] if forming else None
        a["oi"] = d.get("oi", {})
        a["source"] = "Binance spot/Bybit (Trading-bot fetch_klines_resilient), nến ngày UTC đã đóng"
        out["assets"][sym] = a
        closes[sym] = df.set_index("time")["close"]
    if len(closes) == 2:
        j = pd.concat(closes, axis=1).dropna().iloc[-365:]
        out["compare"] = {"t": [str(x.date()) for x in j.index],
                          "BTCUSDT": _norm(list(j["BTCUSDT"])), "ETHUSDT": _norm(list(j["ETHUSDT"])),
                          "eth_btc": [round(float(a / b), 5) for a, b in zip(j["ETHUSDT"], j["BTCUSDT"])],
                          "corr_90d": _r(j["BTCUSDT"].pct_change().iloc[-90:].corr(j["ETHUSDT"].pct_change().iloc[-90:]), 3)}
    return out


# ---------------------------------------------------------------- kim loại
def metals_section(path: Path = DB_PATH) -> Dict[str, Any]:
    import yfinance as yf
    out: Dict[str, Any] = {"assets": {}, "errors": []}
    closes = {}
    for key, tk, name in (("GOLD", "GC=F", "Vàng COMEX (GC=F)"), ("SILVER", "SI=F", "Bạc COMEX (SI=F)")):
        try:
            with market._quiet():
                h = yf.Ticker(tk).history(period="3y", interval="1d", auto_adjust=False)
            if h is None or len(h) < 260:
                out["errors"].append(f"{tk}: thiếu dữ liệu ({0 if h is None else len(h)} phiên)")
                continue
            df = pd.DataFrame({"time": h.index.tz_localize(None).normalize(), "open": h["Open"].values,
                               "high": h["High"].values, "low": h["Low"].values, "close": h["Close"].values,
                               "volume": h["Volume"].values}).dropna()
            a = _analyze_ohlcv(df, 1.0, "USD", 2)
            a.update(symbol=key, ticker=tk, name=name,
                     source="Yahoo Finance qua yfinance – hợp đồng tương lai COMEX, có thể trễ 10–15 phút")
            out["assets"][key] = a
            closes[key] = df.set_index("time")["close"]
        except Exception as e:
            out["errors"].append(f"{tk}: {type(e).__name__}: {str(e)[:150]}")
    if len(closes) == 2:
        j = pd.concat(closes, axis=1).dropna().iloc[-500:]
        ratio = (j["GOLD"] / j["SILVER"])
        out["compare"] = {"t": [str(x.date()) for x in j.index], "GOLD": _norm(list(j["GOLD"])),
                          "SILVER": _norm(list(j["SILVER"])), "ratio": [round(float(x), 2) for x in ratio],
                          "ratio_now": _r(ratio.iloc[-1]), "ratio_avg_2y": _r(ratio.mean()),
                          "ratio_pct_rank_2y": _r((ratio < ratio.iloc[-1]).mean() * 100, 1)}
    try:
        g = market.gold_market(path=path)
        out["vn"] = {"vcb": g.get("vcb"), "usdvnd_yahoo": g.get("usdvnd"), "implied_vnd_luong": g.get("implied_vnd_luong"),
                     "domestic": g.get("domestic"), "errors": g.get("errors"), "fetched_at": g.get("fetched_at")}
        out["vn"]["press"] = news.latest_gold_press(path=path)
        if out["assets"].get("SILVER") and g.get("vcb"):
            from precious.universe import LUONG_TO_TROY_OZ
            out["vn"]["implied_silver_vnd_luong"] = round(out["assets"]["SILVER"]["price"] * g["vcb"]["sell"] * LUONG_TO_TROY_OZ, -3)
    except Exception as e:
        out["errors"].append(f"vàng VN: {type(e).__name__}: {str(e)[:150]}")
    return out


# ---------------------------------------------------------------- chứng khoán VN
def vn_section() -> Dict[str, Any]:
    from vn_stock.intel.data import load_adjusted as load_ohlcv_adj
    from vn_stock.intel import indicators as I
    from vn_stock.intel.data import INTEL_DIR, load_json
    res = load_json(INTEL_DIR / "latest.json")
    if not res:
        return {"error": "chưa có kết quả quét Stock Intelligence – chạy run_intel_scan scan"}
    bt = load_json(INTEL_DIR / "backtest" / "summary_latest.json") or {}
    stocks = []
    for s in res["stocks"]:
        t, sm, fl = s.get("technical") or {}, s.get("smc") or {}, s.get("flow") or {}
        fa, val, lv, rec = s.get("fundamental") or {}, s.get("valuation") or {}, s.get("levels") or {}, s.get("recommendations") or {}
        m, sx = fa.get("metrics") or {}, fa.get("sector_metrics") or {}
        rb = sm.get("recent_breaks_30d") or []
        row = {
            "sym": s["symbol"], "name": s.get("organ_name"), "ex": s.get("exchange"), "sector": s.get("sector"),
            "sector_vi": s.get("sector_vi"), "cap": s.get("cap_bucket"), "mcap": s.get("market_cap_bn"),
            "price": s.get("price_vnd"), "date": (s.get("price_info") or {}).get("trading_date"),
            "chg1d": s.get("chg_1d_pct"), "ret20": (t.get("range") or {}).get("ret_20d_pct"),
            "ret60": (t.get("range") or {}).get("ret_60d_pct"), "dist52": (t.get("range") or {}).get("dist_from_high_pct"),
            "val20": (t.get("volume") or {}).get("value_avg20_bn"), "rvol": (t.get("volume") or {}).get("rvol"),
            "rsi": (t.get("rsi") or {}).get("value"), "macd_hist": (t.get("macd") or {}).get("hist"),
            "adx": (t.get("adx") or {}).get("adx"), "cloud": (t.get("ichimoku") or {}).get("price_vs_cloud"),
            "smc_trend": sm.get("trend"), "smc_last": f"{rb[-1]['type']} {rb[-1]['direction']} {rb[-1]['date']}" if rb else None,
            "flow_div": fl.get("price_volume_divergence"),
            "foreign_bn": ((s.get("board") or {}).get("foreign_net_bn")),
            "pe": m.get("pe_current"), "pb": m.get("pb_current"), "roe": m.get("roe_ttm"), "roa": m.get("roa_ttm"),
            "npg": m.get("np_growth_ttm"), "revg": m.get("revenue_growth_ttm"), "np_cagr3": m.get("np_cagr_3y"),
            "npq": m.get("np_growth_last_quarter_yoy"), "de": m.get("debt_to_equity"), "eps": m.get("eps_ttm_vnd"),
            "bvps": m.get("bvps_vnd"), "divy": m.get("div_yield_current"), "np_ttm": m.get("np_parent_ttm_bn"),
            "nim": sx.get("nim_approx"), "npl": sx.get("npl"), "llr": sx.get("llr_coverage"),
            "fa_period": fa.get("latest_period"), "fa_status": fa.get("status"),
            "fv": val.get("fair_value_vnd"), "upside": val.get("upside_base"), "mos": val.get("margin_of_safety"),
            "val_conf": val.get("confidence"), "val_models": list((val.get("models") or {}).keys()),
            "scores": s.get("scores"),
            "rec": {h: {k: (rec.get(h) or {}).get(k) for k in ("rating", "score", "confidence", "reasoning", "risks",
                                                              "change_conditions", "notes")} for h in ("short", "medium", "long")},
            "lv": {k: lv.get(k) for k in ("preferred_buy_zone", "preferred_basis", "secondary_buy_zone", "invalidation",
                                          "invalidation_basis", "target1", "target1_basis", "target2", "target2_basis",
                                          "risk_reward_t1", "risk_reward_t2", "downside_risk_pct")},
            "notes": [x for x in [m.get("shares_note")] + (s.get("errors") or []) if x],
        }
        df = load_ohlcv_adj(s["symbol"])
        if df is not None and len(df) > 60:
            ind = I.compute_all(df.sort_values("time").reset_index(drop=True))
            ch = _series(ind, BARS, 2)
            for k in ("rsi", "macd_hist"):      # giảm dung lượng: biểu đồ cổ phiếu không vẽ RSI/MACD
                ch.pop(k, None)
            row["chart"] = ch
        stocks.append(row)
    idx = {}
    for k in ("VNINDEX", "VN30", "HNXINDEX"):
        df = load_ohlcv_adj(k)
        if df is not None and len(df) > 60:
            ind = I.compute_all(df.sort_values("time").reset_index(drop=True))
            idx[k] = {**{kk: res["indices"].get(k, {}).get(kk) for kk in ("close", "chg_1d_pct", "ret_20d_pct", "ret_60d_pct",
                                                                         "rsi14", "adx", "as_of", "above_sma200",
                                                                         "dist_from_52w_high_pct", "volatility_20d_ann")},
                      "chart": _series(ind, BARS, 2)}
    bt_rows = []
    for hz, v in (bt.get("by_horizon") or {}).items():
        oos, base = v.get("out_of_sample") or {}, v.get("baseline_all_points") or {}
        bt_rows.append({"horizon": hz, "days": v.get("holding_days"), "oos_n": oos.get("n"), "oos_win": oos.get("win_rate"),
                        "oos_avg": oos.get("avg_ret"), "oos_pf": oos.get("profit_factor"),
                        "oos_excess": oos.get("avg_excess_vs_vnindex"), "baseline": base.get("avg_fwd_ret"),
                        "is_avg": (v.get("in_sample") or {}).get("avg_ret"), "is_pf": (v.get("in_sample") or {}).get("profit_factor")})
    return {"scan_id": res["scan_meta"]["scan_id"], "scan_mode": res["scan_meta"]["mode"],
            "regime": res.get("regime"), "breadth": res.get("breadth"), "sectors": res.get("sectors"),
            "indices": idx, "stocks": stocks, "backtest": bt_rows,
            "backtest_limits": bt.get("limitations"), "oi": res.get("open_interest"),
            "source": "Stock Intelligence (stock/vn_stock/intel): vnstock VCI giá/OHLCV, VNDirect finfo BCTC"}


def build_payload(path: Path = DB_PATH, parts: Optional[List[str]] = None) -> Dict[str, Any]:
    parts = parts or ["news", "crypto", "vn", "metals"]
    out: Dict[str, Any] = {"generated_at": compose.fmt_local(db.now_utc()), "generated_iso": db.iso(db.now_utc()),
                           "errors": {}}
    fns = {"news": lambda: news_section(path), "crypto": crypto_section, "vn": vn_section,
           "metals": lambda: metals_section(path)}
    for p in parts:
        try:
            out[p] = fns[p]()
        except Exception as e:
            out[p] = {"error": f"{type(e).__name__}: {str(e)[:300]}"}
            out["errors"][p] = out[p]["error"]
            db.log_event("WARN", "site", f"{p}: {out[p]['error']}", path)
    return out
