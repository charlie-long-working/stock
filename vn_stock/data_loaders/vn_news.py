"""
Tin tức cổ phiếu VN từ Vietstock — không cần đăng nhập / token.

Hai nguồn, đều hợp lệ (không vượt chặn bot):
  1. KBS stockinfo (qua vnstock): tin mới nhất của mã, bài gốc trên vietstock.vn.
  2. Google News RSS `site:vietstock.vn`: tiêu đề + link, lọc theo mã.

Vietstock RSS trực tiếp trả 403 (bot-challenge) từ 2026-11 → không dùng.
"""

from __future__ import annotations

import html
import re
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Iterable, List, Optional

import requests

UA = "Mozilla/5.0 (vn_stock news digest)"
VIETSTOCK_BASE = "https://vietstock.vn"
GNEWS_RSS = "https://news.google.com/rss/search"
TZ_VN = timezone(timedelta(hours=7))

# Bài nhận định / phân tích thị trường của Vietstock (match tiêu đề, không phân biệt hoa thường)
MARKET_VIEW_PATTERNS = (
    "nhận định",
    "góc nhìn ptkt",
    "nhịp đập thị trường",
    "phân tích kỹ thuật",
    "xu hướng",
    "vn-index",
)


@dataclass
class NewsItem:
    title: str
    url: str
    published: Optional[datetime]
    source: str  # kbs | gnews
    symbol: Optional[str] = None

    @property
    def key(self) -> str:
        return _norm_title(self.title)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["published"] = self.published.isoformat() if self.published else None
        return d


def _norm_title(title: str) -> str:
    t = re.sub(r"\s+-\s+Vietstock(Finance)?\s*$", "", title.strip(), flags=re.I)
    return re.sub(r"\W+", " ", t.lower()).strip()


def _clean_gnews_title(title: str) -> str:
    return re.sub(r"\s+-\s+Vietstock(Finance)?\s*$", "", html.unescape(title).strip(), flags=re.I)


def _mentions_symbol(title: str, symbol: str) -> bool:
    return re.search(rf"(?<![A-Z0-9]){re.escape(symbol.upper())}(?![A-Z0-9])", title) is not None


# Tin nhiễu: chứng quyền phát hành mới, trang hồ sơ công ty (tiếng Anh) của Vietstock
_NOISE = re.compile(
    r"^(CW\.|Chứng quyền\b)"
    r"|^[A-Z0-9]{3}: .*\b(Joint Stock|Corporation|Company|Group|Bank)\b",
)


def _is_noise(title: str) -> bool:
    return _NOISE.search(title) is not None


def dedupe(items: Iterable[NewsItem]) -> List[NewsItem]:
    seen, out = set(), []
    for it in items:
        if it.key and it.key not in seen:
            seen.add(it.key)
            out.append(it)
    return out


def _sort_newest(items: List[NewsItem]) -> List[NewsItem]:
    floor = datetime.min.replace(tzinfo=timezone.utc)
    return sorted(items, key=lambda x: x.published or floor, reverse=True)


# ---------------------------------------------------------------- KBS (vnstock)

def fetch_kbs_news(symbol: str, page_size: int = 10) -> List[NewsItem]:
    try:
        from vnstock.explorer.kbs.company import Company
    except ImportError:
        return []
    try:
        df = Company(symbol.upper()).news(page_size=page_size)
    except Exception:
        return []
    if df is None or df.empty:
        return []
    out: List[NewsItem] = []
    for _, row in df.iterrows():
        url = str(row.get("url") or "")
        if url.startswith("/"):
            url = VIETSTOCK_BASE + url
        pub = None
        raw = row.get("publish_time")
        if raw:
            try:
                pub = datetime.fromisoformat(str(raw)).replace(tzinfo=TZ_VN)
            except ValueError:
                pass
        out.append(NewsItem(str(row.get("title") or "").strip(), url, pub, "kbs", symbol.upper()))
    return out


# ---------------------------------------------------------------- Google News RSS

def fetch_gnews(query: str, timeout: int = 20) -> List[NewsItem]:
    params = {"q": query, "hl": "vi", "gl": "VN", "ceid": "VN:vi"}
    url = f"{GNEWS_RSS}?{urllib.parse.urlencode(params)}"
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=timeout)
        r.raise_for_status()
        root = ET.fromstring(r.content)
    except Exception:
        return []
    out: List[NewsItem] = []
    for it in root.findall(".//item"):
        title = _clean_gnews_title(it.findtext("title") or "")
        pub = None
        if it.findtext("pubDate"):
            try:
                pub = parsedate_to_datetime(it.findtext("pubDate"))
            except (TypeError, ValueError):
                pass
        out.append(NewsItem(title, it.findtext("link") or "", pub, "gnews"))
    return out


def fetch_symbol_news(symbol: str, days: int = 3, limit: int = 5) -> List[NewsItem]:
    """Tin của một mã: KBS + Google News (tiêu đề phải chứa mã)."""
    sym = symbol.upper()
    since = datetime.now(timezone.utc) - timedelta(days=days)
    items = fetch_kbs_news(sym)
    for it in fetch_gnews(f'"{sym}" site:vietstock.vn when:{days}d'):
        if _mentions_symbol(it.title, sym):
            it.symbol = sym
            items.append(it)
    items = [
        it for it in items
        if (it.published is None or it.published >= since) and not _is_noise(it.title)
    ]
    return _sort_newest(dedupe(items))[:limit]


def fetch_market_views(days: int = 1, limit: int = 8) -> List[NewsItem]:
    """Bài nhận định / PTKT thị trường chung của Vietstock."""
    items = fetch_gnews(f"site:vietstock.vn when:{days}d")
    items = [it for it in items if any(p in it.title.lower() for p in MARKET_VIEW_PATTERNS)]
    return _sort_newest(dedupe(items))[:limit]
