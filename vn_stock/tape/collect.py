"""
Thu thập khớp lệnh trong phiên (KBS qua vnstock) → tổng hợp mua/bán chủ động theo ngày.

- Mọi lệnh gọi API đi qua `api_call` (giãn cách 3,6 s, bắt sys.exit khi vượt 20 req/phút của vnstock bản khách;
  cùng tham số với Stock Intelligence nhưng không import code của nó — chỉ đọc file dữ liệu).
- Lưu: `data/tape/daily.csv` (1 dòng/mã/phiên, upsert theo (date, symbol)),
       `data/tape/raw/<date>.csv.gz` (tick thô, giữ RAW_KEEP_DAYS ngày để tính lại khi cần),
       `data/tape/status.json` (kết quả lần chạy gần nhất).
- Chỉ nhận dữ liệu khi ngày của tick = phiên mong đợi và phiên đã kết thúc (tick cuối ≥ 14:45).
- Đối chiếu tổng khối lượng tick với khối lượng ngày trong kho giá điều chỉnh (`reconciled`).
"""

from __future__ import annotations

import contextlib
import io
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple

import pandas as pd

from vn_stock import DATA_DIR

TZ = timezone(timedelta(hours=7))
TAPE_DIR = DATA_DIR / "tape"
DAILY = TAPE_DIR / "daily.csv"
RAW_DIR = TAPE_DIR / "raw"
STATUS = TAPE_DIR / "status.json"
PAGE_SIZE = 10000
MAX_PAGES = 10
RAW_KEEP_DAYS = 180
SESSION_END = "14:45:00"
RECONCILE_TOL = 0.005
ADJ_DIR = DATA_DIR / "intel" / "ohlcv_adj"
MIN_INTERVAL_S = 3.6
RATE_LIMIT_WAIT_S = 65
_last_call = [0.0]

COLUMNS = [
    "date", "symbol", "buy_vol", "sell_vol", "ato_vol", "atc_vol", "other_vol", "total_vol",
    "buy_value_bn", "sell_value_bn", "vwap", "nar", "large_thr_bn", "large_buy_vol", "large_sell_vol",
    "large_buy_value_bn", "large_sell_value_bn", "n_ticks", "first_tick", "last_tick", "complete",
    "pages", "ref_volume", "reconciled", "fetched_at",
]


def now_vn() -> datetime:
    return datetime.now(TZ)


def expected_session(now: Optional[datetime] = None) -> str:
    """Phiên gần nhất đã kết thúc (T2–T6; trước 15:00 là phiên trước). Ngày lễ xử lý ở bước kiểm tra ngày tick."""
    now = (now or now_vn()).astimezone(TZ)
    d = pd.Timestamp(now.date())
    if now.hour < 15:
        d -= pd.Timedelta(days=1)
    while d.weekday() >= 5:
        d -= pd.Timedelta(days=1)
    return d.strftime("%Y-%m-%d")


def large_threshold_bn(value_avg20_bn: Optional[float]) -> float:
    """Ngưỡng 'lô lớn' theo thanh khoản mã: 0,1% GTGD TB20, kẹp trong [0,3; 3] tỷ."""
    if not value_avg20_bn or value_avg20_bn != value_avg20_bn:
        return 1.0
    return float(min(3.0, max(0.3, 0.001 * value_avg20_bn)))


# ---------------------------------------------------------------- fetch

def api_call(fn: Callable[[], object], label: str = "", min_interval: float = MIN_INTERVAL_S,
             wait_on_limit: float = RATE_LIMIT_WAIT_S):
    """Gọi vnstock có giãn cách; vnstock gọi sys.exit khi vượt giới hạn → chờ rồi thử lại 1 lần."""
    for attempt in range(2):
        wait = min_interval - (time.monotonic() - _last_call[0])
        if wait > 0:
            time.sleep(wait)
        _last_call[0] = time.monotonic()
        try:
            buf = io.StringIO()
            logging.disable(logging.ERROR)
            try:
                with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                    return fn()
            finally:
                logging.disable(logging.NOTSET)
        except SystemExit:
            time.sleep(wait_on_limit)
        except Exception:
            if attempt == 1:
                raise
            time.sleep(3)
    raise RuntimeError(f"rate limit kéo dài: {label}")


def _kbs_page(sym: str, page: int, page_size: int) -> pd.DataFrame:
    from vnstock.explorer.kbs.quote import Quote

    return Quote(sym).intraday(page_size=page_size, page=page)


def normalize(ticks: pd.DataFrame) -> pd.DataFrame:
    if ticks is None or len(ticks) == 0:
        return pd.DataFrame(columns=["time", "price", "volume", "match_type"])
    t = ticks.copy()
    t["time"] = pd.to_datetime(t["time"])
    if getattr(t["time"].dt, "tz", None) is not None:
        t["time"] = t["time"].dt.tz_convert(TZ).dt.tz_localize(None)
    t["price"] = pd.to_numeric(t["price"], errors="coerce")
    t["volume"] = pd.to_numeric(t["volume"], errors="coerce").fillna(0).astype("int64")
    t["match_type"] = t["match_type"].astype(str).str.strip().str.lower()
    # KHÔNG dedupe theo id: id của KBS = thời gian+giá+KL nên hai lệnh khớp thật giống nhau trùng id
    # (VCB 13/11: bỏ trùng làm mất 17 lệnh, tổng lệch KL ngày 0,14%). Các trang không chồng lấn.
    return t.dropna(subset=["price"]).sort_values("time", kind="stable").reset_index(drop=True)


def fetch_ticks(sym: str, cfg: Optional[dict] = None, page_size: int = PAGE_SIZE, max_pages: int = MAX_PAGES,
                page_fn: Optional[Callable[[str, int, int], pd.DataFrame]] = None) -> Tuple[pd.DataFrame, int]:
    """Tất cả tick của phiên gần nhất. Trả (ticks, số trang đã gọi)."""
    page_fn = page_fn or _kbs_page
    parts: List[pd.DataFrame] = []
    pages = 0
    for p in range(1, max_pages + 1):
        df = api_call(lambda: page_fn(sym, p, page_size), label=f"tape {sym} p{p}")
        pages += 1
        if df is None or len(df) == 0:
            break
        parts.append(df)
        if len(df) < page_size:
            break
    return normalize(pd.concat(parts, ignore_index=True) if parts else None), pages


# ---------------------------------------------------------------- aggregate

def aggregate(ticks: pd.DataFrame, sym: str, ref_volume: Optional[float] = None,
              large_thr_bn: float = 1.0, pages: int = 1) -> Dict:
    t = normalize(ticks)
    if len(t) == 0:
        raise ValueError("không có tick")
    val_bn = t["price"] * 1000 * t["volume"] / 1e9
    mt = t["match_type"]
    is_buy, is_sell = mt.eq("buy"), mt.eq("sell")
    is_ato, is_atc = mt.eq("ato"), mt.eq("atc")
    buy, sell = int(t.loc[is_buy, "volume"].sum()), int(t.loc[is_sell, "volume"].sum())
    total = int(t["volume"].sum())
    large = val_bn >= large_thr_bn
    last = t["time"].iloc[-1]
    row = {
        "date": last.strftime("%Y-%m-%d"),
        "symbol": sym.upper(),
        "buy_vol": buy,
        "sell_vol": sell,
        "ato_vol": int(t.loc[is_ato, "volume"].sum()),
        "atc_vol": int(t.loc[is_atc, "volume"].sum()),
        "other_vol": int(t.loc[~(is_buy | is_sell | is_ato | is_atc), "volume"].sum()),
        "total_vol": total,
        "buy_value_bn": round(float(val_bn[is_buy].sum()), 4),
        "sell_value_bn": round(float(val_bn[is_sell].sum()), 4),
        "vwap": round(float((t["price"] * t["volume"]).sum() / total), 4) if total else None,
        "nar": round((buy - sell) / (buy + sell), 4) if buy + sell else None,
        "large_thr_bn": round(large_thr_bn, 3),
        "large_buy_vol": int(t.loc[is_buy & large, "volume"].sum()),
        "large_sell_vol": int(t.loc[is_sell & large, "volume"].sum()),
        "large_buy_value_bn": round(float(val_bn[is_buy & large].sum()), 4),
        "large_sell_value_bn": round(float(val_bn[is_sell & large].sum()), 4),
        "n_ticks": int(len(t)),
        "first_tick": t["time"].iloc[0].strftime("%H:%M:%S"),
        "last_tick": last.strftime("%H:%M:%S"),
        "complete": bool(last.strftime("%H:%M:%S") >= SESSION_END),
        "pages": int(pages),
        "ref_volume": None if ref_volume is None else int(ref_volume),
        "reconciled": None,
        "fetched_at": now_vn().isoformat(timespec="seconds"),
    }
    if ref_volume:
        row["reconciled"] = bool(abs(total / float(ref_volume) - 1.0) <= RECONCILE_TOL)
    return row


# ---------------------------------------------------------------- store

def load_daily(path: Path = DAILY) -> pd.DataFrame:
    if not Path(path).exists():
        return pd.DataFrame(columns=COLUMNS)
    return pd.read_csv(path, dtype={"date": str, "symbol": str})


def save_daily(rows: Iterable[Dict], path: Path = DAILY) -> int:
    rows = list(rows)
    if not rows:
        return 0
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    new = pd.DataFrame(rows).reindex(columns=COLUMNS)
    old = load_daily(path)
    allr = pd.concat([old, new], ignore_index=True) if len(old) else new
    allr = allr.drop_duplicates(["date", "symbol"], keep="last").sort_values(["date", "symbol"])
    tmp = path.with_suffix(".tmp")
    allr.to_csv(tmp, index=False)
    tmp.replace(path)
    return len(new)


def save_raw(session: str, frames: Dict[str, pd.DataFrame], raw_dir: Path = RAW_DIR) -> Optional[Path]:
    if not frames:
        return None
    raw_dir.mkdir(parents=True, exist_ok=True)
    p = raw_dir / f"{session}.csv.gz"
    df = pd.concat([f.assign(symbol=s) for s, f in frames.items()], ignore_index=True)
    if p.exists():
        df = pd.concat([pd.read_csv(p), df], ignore_index=True).drop_duplicates()
    df.to_csv(p, index=False, compression="gzip")
    cutoff = (pd.Timestamp(session) - pd.Timedelta(days=RAW_KEEP_DAYS)).strftime("%Y-%m-%d")
    for old in raw_dir.glob("*.csv.gz"):
        if old.name[:10] < cutoff:
            old.unlink()
    return p


# ---------------------------------------------------------------- orchestrate

def _ref_from_adjusted(sym: str, session: str) -> Tuple[Optional[float], Optional[float]]:
    """(khối lượng phiên, GTGD TB20 tỷ) từ kho giá điều chỉnh của Stock Intelligence (không gọi API)."""
    p = ADJ_DIR / f"{sym}.csv"
    if not p.exists():
        return None, None
    try:
        df = pd.read_csv(p)
    except (OSError, ValueError):
        return None, None
    if len(df) == 0:
        return None, None
    df = df.copy()
    df["d"] = pd.to_datetime(df["time"]).dt.strftime("%Y-%m-%d")
    ref = df.loc[df["d"] == session, "volume"]
    hist = df[df["d"] < session].tail(20)
    adv = float((hist["close"] * 1000 * hist["volume"]).mean() / 1e9) if len(hist) else None
    return (float(ref.iloc[0]) if len(ref) else None), adv


def collect(symbols: List[str], session: str, cfg: Optional[dict] = None, force: bool = False,
            page_fn: Optional[Callable] = None, ref_fn: Optional[Callable] = None,
            daily_path: Path = DAILY, keep_raw: bool = True, log: Callable[[str], None] = print
            ) -> Tuple[List[Dict], Dict[str, str]]:
    """Thu thập những mã chưa có dữ liệu cho `session` (force=True: lấy lại hết). Lỗi từng mã không dừng lượt."""
    ref_fn = ref_fn or _ref_from_adjusted
    have = set()
    if not force:
        d = load_daily(daily_path)
        have = set(d.loc[d["date"] == session, "symbol"]) if len(d) else set()
    rows: List[Dict] = []
    errors: Dict[str, str] = {}
    raw: Dict[str, pd.DataFrame] = {}
    todo = [s for s in symbols if s not in have]
    log(f"  tape {session}: {len(todo)} mã cần lấy ({len(have)} đã có)")
    for sym in todo:
        try:
            ticks, pages = fetch_ticks(sym, cfg, page_fn=page_fn)
            if len(ticks) == 0:
                errors[sym] = "không có tick"
                continue
            day = ticks["time"].iloc[-1].strftime("%Y-%m-%d")
            if day != session:
                errors[sym] = f"tick phiên {day} ≠ {session}"
                continue
            ref, adv = ref_fn(sym, session)
            row = aggregate(ticks, sym, ref_volume=ref, large_thr_bn=large_threshold_bn(adv), pages=pages)
            if not row["complete"]:
                errors[sym] = f"phiên chưa kết thúc (tick cuối {row['last_tick']})"
                continue
            rows.append(row)
            raw[sym] = ticks
        except Exception as e:  # noqa: BLE001 — một mã lỗi không làm hỏng cả lượt
            errors[sym] = f"{type(e).__name__}: {str(e)[:120]}"
    if rows:
        save_daily(rows, daily_path)
        if keep_raw:
            save_raw(session, raw, daily_path.parent / "raw")
    status = {
        "session": session, "run_at": now_vn().isoformat(timespec="seconds"),
        "requested": len(symbols), "already": len(have), "collected": len(rows),
        "reconciled": sum(1 for r in rows if r.get("reconciled")), "errors": errors,
    }
    try:
        daily_path.parent.mkdir(parents=True, exist_ok=True)
        (daily_path.parent / "status.json").write_text(json.dumps(status, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass
    log(f"  tape {session}: lấy {len(rows)} · khớp KL ngày {status['reconciled']} · lỗi {len(errors)}")
    return rows, errors
