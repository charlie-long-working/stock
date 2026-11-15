#!/usr/bin/env python3
"""
Digest tin Vietstock + chỉ số cơ bản cho watchlist VN → Telegram.

  - Tin theo mã: KBS stockinfo + Google News `site:vietstock.vn` (xem data_loaders/vn_news.py)
  - Nhận định thị trường: bài PTKT / nhận định (Vietstock, CafeF, Tin nhanh CK, VnEconomy) trong N ngày
  - Cơ bản: P/E, P/B, ROE từ cache vn_stock/data/fundamentals (ghi rõ ngày cache)

Không cần token Vietstock. Chỉ gửi tin chưa gửi (cache hash tiêu đề).

Chạy từ stock/:
  PYTHONPATH=".:../Trading-bot" .venv/bin/python -m vn_stock.scripts.run_vn_news_digest --dry-run
  ... --symbols VCB,FPT --days 3
  ... --no-dedupe          # in lại cả tin đã gửi
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set
from zoneinfo import ZoneInfo

STOCK_ROOT = Path(__file__).resolve().parents[2]
if str(STOCK_ROOT) not in sys.path:
    sys.path.insert(0, str(STOCK_ROOT))

from vn_stock import DATA_DIR
from vn_stock.data_loaders.vn_fundamentals import compute_ratios, get_fundamentals_dir
from vn_stock.data_loaders.vn_news import NewsItem, fetch_market_views, fetch_symbol_news

TZ = ZoneInfo("Asia/Ho_Chi_Minh")
DEFAULT_SYMBOLS = [
    "VCB", "BID", "TCB", "CTG", "MBB", "FPT", "HPG", "MWG",
    "MSN", "GAS", "VHM", "VNM", "SSI", "ACB", "VPB",
]
OUT_DIR = DATA_DIR / "screening"
SNAPSHOT_PATH = OUT_DIR / "vn_news_snapshot.json"
SENT_CACHE = OUT_DIR / "vn_news_sent.json"
TG_LIMIT = 3900  # Telegram tối đa 4096 ký tự / tin


def _hash(item: NewsItem) -> str:
    return hashlib.sha1(item.key.encode("utf-8")).hexdigest()[:16]


def _load_sent() -> Set[str]:
    try:
        return set(json.loads(SENT_CACHE.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return set()


def _save_sent(keys: Set[str], max_keys: int = 2000) -> None:
    SENT_CACHE.parent.mkdir(parents=True, exist_ok=True)
    SENT_CACHE.write_text(json.dumps(sorted(keys)[-max_keys:]), encoding="utf-8")


def _fundamentals_line(symbol: str) -> Optional[str]:
    ratios_csv = get_fundamentals_dir() / symbol / "ratios.csv"
    if not ratios_csv.exists():
        return None
    r = compute_ratios(symbol)
    parts = []
    if r.get("pe") is not None:
        parts.append(f"P/E {r['pe']:.1f}")
    if r.get("pb") is not None:
        parts.append(f"P/B {r['pb']:.2f}")
    if r.get("roe") is not None:
        parts.append(f"ROE {r['roe'] * 100:.1f}%")
    if not parts:
        return None
    return f"{' · '.join(parts)} <i>(BCTC {_latest_period(ratios_csv)})</i>"


def _latest_period(ratios_csv: Path) -> str:
    """Kỳ báo cáo mới nhất trong cache (vd Q4/2025). Không dùng mtime: trên CI mtime = lúc checkout."""
    import pandas as pd

    try:
        df = pd.read_csv(ratios_csv, usecols=["yearReport", "lengthReport"])
        y, q = df.sort_values(["yearReport", "lengthReport"]).iloc[-1]
        return f"Q{int(q)}/{int(y)}" if int(q) in (1, 2, 3, 4) else str(int(y))
    except (ValueError, KeyError, IndexError):
        return "cache"


def _fmt_item(it: NewsItem) -> str:
    when = it.published.astimezone(TZ).strftime("%d/%m %H:%M") if it.published else "—"
    return (f"• {when} <a href=\"{html.escape(it.url, quote=True)}\">{html.escape(it.title)}</a>"
            f" <i>[{html.escape(it.source_name)}]</i>")


def build_messages(
    per_symbol: Dict[str, List[NewsItem]],
    market: List[NewsItem],
    fundamentals: Dict[str, Optional[str]],
) -> List[str]:
    blocks: List[str] = []
    if market:
        blocks.append("<b>📊 Nhận định thị trường</b>\n" + "\n".join(_fmt_item(i) for i in market))
    for sym, items in per_symbol.items():
        if not items:
            continue
        head = f"<b>{sym}</b>"
        if fundamentals.get(sym):
            head += f" — {fundamentals[sym]}"
        blocks.append(head + "\n" + "\n".join(_fmt_item(i) for i in items))
    if not blocks:
        return []

    title = f"📰 <b>Tin VN</b> {datetime.now(TZ).strftime('%d/%m/%Y %H:%M')}"
    msgs, cur = [], title
    for b in blocks:
        # một khối quá dài (nhiều tin / tiêu đề dài) → tách theo dòng, mỗi dòng là một tin trọn vẹn
        pieces, buf = [], ""
        for line in b.split("\n"):
            if buf and len(buf) + len(line) + 1 > TG_LIMIT:
                pieces.append(buf)
                buf = line
            else:
                buf = f"{buf}\n{line}" if buf else line
        pieces.append(buf)
        for p in pieces:
            if len(cur) + len(p) + 2 > TG_LIMIT:
                msgs.append(cur)
                cur = p
            else:
                cur += "\n\n" + p
    msgs.append(cur)
    return msgs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbols", help="VCB,FPT,... (mặc định watchlist hourly)")
    ap.add_argument("--days", type=int, default=2, help="cửa sổ tin theo mã (ngày)")
    ap.add_argument("--market-days", type=int, default=1, help="cửa sổ bài nhận định (ngày)")
    ap.add_argument("--per-symbol", type=int, default=3, help="số tin tối đa mỗi mã")
    ap.add_argument("--dry-run", action="store_true", help="in ra, không gửi Telegram, không ghi cache tin đã gửi (vẫn ghi snapshot)")
    ap.add_argument("--no-dedupe", action="store_true", help="bỏ qua cache tin đã gửi")
    args = ap.parse_args()

    symbols = [s.strip().upper() for s in (args.symbols or ",".join(DEFAULT_SYMBOLS)).split(",") if s.strip()]
    sent = set() if args.no_dedupe else _load_sent()

    def fresh(items: List[NewsItem]) -> List[NewsItem]:
        return [i for i in items if _hash(i) not in sent]

    market = fresh(fetch_market_views(days=args.market_days))
    per_symbol: Dict[str, List[NewsItem]] = {}
    for sym in symbols:
        per_symbol[sym] = fresh(fetch_symbol_news(sym, days=args.days, limit=args.per_symbol))
        print(f"  {sym}: {len(per_symbol[sym])} tin mới", file=sys.stderr)
    fundamentals = {s: _fundamentals_line(s) for s in symbols if per_symbol[s]}

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(json.dumps({
        "generated_at": datetime.now(TZ).isoformat(),
        "market": [i.to_dict() for i in market],
        "symbols": {s: [i.to_dict() for i in v] for s, v in per_symbol.items()},
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    msgs = build_messages(per_symbol, market, fundamentals)
    if not msgs:
        print("Không có tin mới.")
        return 0
    if args.dry_run:
        print("\n\n-----\n\n".join(msgs))
        return 0

    from vn_stock.notify.telegram import send_message

    for m in msgs:
        ok, err = send_message(m)
        if not ok:
            print(f"Gửi Telegram lỗi: {err}", file=sys.stderr)
            return 1
    all_items = market + [i for v in per_symbol.values() for i in v]
    _save_sent(sent | {_hash(i) for i in all_items})
    print(f"Đã gửi {len(msgs)} tin Telegram ({len(all_items)} bài).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
