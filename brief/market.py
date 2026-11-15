"""Dữ liệu thị trường bằng code xác định. Tái sử dụng loader của repo stock / precious-metals.

- Chứng khoán: vn_stock.data_loaders.vn_ohlcv.fetch_ohlcv(save=False) (vnstock, nguồn VCI)
  + vnstock Trading(source="VCI").price_board cho watchlist (một request).
- Vàng: Yahoo GC=F (precious.universe), tỷ giá Vietcombank XML, Yahoo VND=X,
  hằng số quy đổi precious.universe.LUONG_TO_TROY_OZ.
Không tính tín hiệu mua/bán.
"""

from __future__ import annotations

import contextlib
import io
import json
import warnings
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from brief import db
from brief.check_sources import parse_vcb
from brief.config import DB_PATH, ROOT, TZ, load_settings
from brief.http import fetch

VCB_URL = "https://portal.vietcombank.com.vn/Usercontrols/TVPortal.TyGia/pXML.aspx"
WEEKDAYS = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]


@contextlib.contextmanager
def _quiet():
    """vnstock/yfinance in quảng cáo/cảnh báo ra stdout; không để lẫn vào log bot."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            yield


def load_watchlist(settings: Optional[dict[str, Any]] = None) -> tuple[list[str], str]:
    settings = settings or load_settings()
    wl = settings["watchlist"]
    p = (ROOT / wl["file"]).resolve()
    try:
        syms = [s.strip().upper() for s in json.loads(p.read_text())["symbols"] if s.strip()]
    except Exception:
        syms = []
    return syms, wl["label"]


def _cached(key: str, max_age_min: float, builder, path: Path = DB_PATH, force: bool = False) -> dict[str, Any]:
    if not force:
        hit = db.kv_get(key, path)
        if hit and hit.get("fetched_at"):
            age = (db.now_utc() - db.parse_iso(hit["fetched_at"])).total_seconds() / 60
            if age <= max_age_min:
                hit["cache_age_min"] = round(age, 1)
                return hit
    data = builder()
    data["fetched_at"] = db.iso(db.now_utc())
    db.kv_set(key, data, path)
    data["cache_age_min"] = 0.0
    return data


# ---------------------------------------------------------------- VN stocks
def session_state(now_local: datetime, last_bar: Optional[date]) -> str:
    """Mô tả trạng thái phiên, dựa trên dữ liệu (không đoán lịch nghỉ lễ)."""
    today = now_local.date()
    wd = now_local.weekday()
    hm = now_local.hour * 60 + now_local.minute
    if last_bar == today:
        return "intraday" if hm < 15 * 60 else "closed_today"
    if wd >= 5:
        return "weekend"
    if hm < 9 * 60 + 15:
        return "pre_open"
    return "no_data_today"  # ngày thường nhưng chưa có nến hôm nay: nghỉ lễ hoặc nguồn trễ (chưa xác minh)


def _build_vn(settings: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"indices": [], "watchlist": [], "errors": []}
    start = (datetime.now(TZ).date() - timedelta(days=21)).isoformat()
    with _quiet():
        from vn_stock.data_loaders.vn_ohlcv import fetch_ohlcv
    for sym in settings["market"]["indices"]:
        try:
            with _quiet():
                df = fetch_ohlcv(sym, "1D", start=start, save=False)
            if df is None or len(df) < 2:
                out["errors"].append(f"{sym}: không có dữ liệu")
                continue
            last, prev = df.iloc[-1], df.iloc[-2]
            out["indices"].append({
                "symbol": sym, "date": str(last["time"].date()), "close": float(last["close"]),
                "prev_close": float(prev["close"]), "prev_date": str(prev["time"].date()),
                "volume": float(last["volume"]),
            })
        except Exception as e:
            out["errors"].append(f"{sym}: {type(e).__name__}: {str(e)[:120]}")
    syms, label = load_watchlist(settings)
    out["watchlist_label"] = label
    if syms:
        try:
            with _quiet():
                from vnstock import Trading
                pb = Trading(source="VCI").price_board(syms)
            for _, row in pb.iterrows():
                g = lambda a, b: row.get((a, b))  # noqa: E731
                price, ref = g("match", "match_price"), g("match", "reference_price") or g("listing", "ref_price")
                if not price or not ref:
                    continue
                out["watchlist"].append({
                    "symbol": str(g("listing", "symbol")),
                    "price": float(price), "ref": float(ref),
                    "pct": round((float(price) / float(ref) - 1) * 100, 2),
                    "volume": float(g("match", "accumulated_volume") or 0),
                    "value_bn": round(float(g("match", "accumulated_value") or 0) / 1000, 1),
                    "foreign_net_bn": round((float(g("match", "foreign_buy_value") or 0)
                                             - float(g("match", "foreign_sell_value") or 0)) / 1e9, 1),
                    "trading_date": str(g("listing", "trading_date") or ""),
                    "sending_time": str(g("match", "sending_time") or ""),
                })
        except Exception as e:
            out["errors"].append(f"price_board: {type(e).__name__}: {str(e)[:120]}")
    else:
        out["errors"].append("watchlist rỗng hoặc không đọc được file")
    return out


def vn_market(force: bool = False, path: Path = DB_PATH) -> dict[str, Any]:
    s = load_settings()
    data = _cached("market_vn", s["market"]["cache_min"], lambda: _build_vn(s), path, force)
    last = data["indices"][0]["date"] if data.get("indices") else None
    data["session"] = session_state(datetime.now(TZ), date.fromisoformat(last) if last else None)
    return data


# ---------------------------------------------------------------- gold & FX
def parse_vcb_datetime(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    for fmt in ("%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %H:%M:%S"):
        try:
            return datetime.strptime(s.strip(), fmt).replace(tzinfo=TZ)
        except ValueError:
            continue
    return None


def _num(s: Optional[str]) -> Optional[float]:
    try:
        return float(str(s).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _build_gold() -> dict[str, Any]:
    out: dict[str, Any] = {"errors": []}
    with _quiet():
        import yfinance as yf
        from precious.universe import INSTRUMENTS, LUONG_TO_TROY_OZ
    out["luong_to_oz"] = LUONG_TO_TROY_OZ
    gc_ticker = INSTRUMENTS["GOLD"]["yahoo"]
    try:
        with _quiet():
            h = yf.Ticker(gc_ticker).history(period="5d", interval="1h")
            d = yf.Ticker(gc_ticker).history(period="15d", interval="1d")
        if h.empty or d.empty:
            raise ValueError("Yahoo trả về rỗng")
        last_ts = h.index[-1]
        last_ny_date = last_ts.date()
        daily = d[d.index.date < last_ny_date] if d.index[-1].date() == last_ny_date else d
        prev_close = float(daily["Close"].iloc[-1])
        out["gc"] = {
            "ticker": gc_ticker, "price": round(float(h["Close"].iloc[-1]), 2),
            "bar_time": last_ts.to_pydatetime().astimezone(timezone.utc).isoformat(),
            "prev_close": round(prev_close, 2), "prev_date": str(daily.index[-1].date()),
        }
    except Exception as e:
        out["errors"].append(f"GC=F: {type(e).__name__}: {str(e)[:120]}")
    try:
        with _quiet():
            h = yf.Ticker("VND=X").history(period="5d", interval="1h")
        if not h.empty:
            out["vnd_yahoo"] = {"rate": round(float(h["Close"].iloc[-1]), 1),
                                "bar_time": h.index[-1].to_pydatetime().astimezone(timezone.utc).isoformat()}
    except Exception as e:
        out["errors"].append(f"VND=X: {type(e).__name__}: {str(e)[:120]}")
    res = fetch(VCB_URL)
    if res.ok:
        try:
            v = parse_vcb(res.body)
            usd = v.get("usd") or {}
            dt = parse_vcb_datetime(v.get("datetime"))
            out["vcb"] = {"buy": _num(usd.get("Buy")), "transfer": _num(usd.get("Transfer")),
                          "sell": _num(usd.get("Sell")), "as_of": dt.isoformat() if dt else None}
        except Exception as e:
            out["errors"].append(f"VCB: {type(e).__name__}: {str(e)[:120]}")
    else:
        out["errors"].append(f"VCB: {res.error or res.status}")
    if out.get("gc") and out.get("vcb", {}).get("sell"):
        out["implied_vnd_luong"] = round(out["gc"]["price"] * out["vcb"]["sell"] * LUONG_TO_TROY_OZ)
    out["domestic"] = {
        "status": "no_source",
        "reason": "sjc.com.vn chặn truy cập tự động (Cloudflare, HTTP 403) và XML cũ trả 404; "
                  "không vượt chặn. Chưa có nguồn công khai hợp lệ khác cho SJC/vàng nhẫn.",
    }
    return out


def gold_market(force: bool = False, path: Path = DB_PATH) -> dict[str, Any]:
    s = load_settings()
    return _cached("market_gold", s["market"]["cache_min"], _build_gold, path, force)
