"""
Tin tức cổ phiếu VN — không cần đăng nhập / token, không vượt chặn bot.

Nguồn:
  1. KBS stockinfo (qua vnstock): tin mới nhất của mã, bài gốc trên vietstock.vn.
  2. Google News RSS `site:vietstock.vn`: tiêu đề + link (Vietstock RSS trực tiếp trả 403).
  3. RSS công khai của báo tài chính (PRESS_FEEDS): CafeF, Tin nhanh chứng khoán, VnEconomy.
     Mỗi feed tải 1 lần / tiến trình (cache), User-Agent ghi rõ là bot đọc tin cá nhân.

Tin theo mã: tiêu đề phải chứa mã (biên từ). Nhận định thị trường: tiêu đề khớp MARKET_VIEW_PATTERNS.
"""

from __future__ import annotations

import html
import re
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Dict, Iterable, List, Optional

import requests

UA = "vn_stock-news-digest/1.0 (personal news reader)"
VIETSTOCK_BASE = "https://vietstock.vn"
GNEWS_RSS = "https://news.google.com/rss/search"
TZ_VN = timezone(timedelta(hours=7))

# Bài nhận định / phân tích thị trường (match tiêu đề, không phân biệt hoa thường)
MARKET_VIEW_PATTERNS = (
    "nhận định",
    "góc nhìn",
    "nhịp đập thị trường",
    "phân tích kỹ thuật",
    "xu hướng",
    "vn-index",
    "cổ phiếu cần quan tâm",
    "khối ngoại",
)

# RSS công khai, kiểm tra 15/11/2026 (HTTP 200, 50 item). Thêm nguồn: 1 dòng (source_id, tên, url).
PRESS_FEEDS = (
    ("cafef", "CafeF", "https://cafef.vn/thi-truong-chung-khoan.rss"),
    ("cafef", "CafeF", "https://cafef.vn/doanh-nghiep.rss"),
    ("cafef", "CafeF", "https://cafef.vn/tai-chinh-ngan-hang.rss"),
    ("tnck", "Tin nhanh CK", "https://www.tinnhanhchungkhoan.vn/rss/chung-khoan-1.rss"),
    ("vneconomy", "VnEconomy", "https://vneconomy.vn/chung-khoan.rss"),
)

SOURCE_NAMES = {"kbs": "Vietstock", "gnews": "Vietstock", "cafef": "CafeF", "tnck": "Tin nhanh CK",
                "vneconomy": "VnEconomy"}


@dataclass
class NewsItem:
    title: str
    url: str
    published: Optional[datetime]
    source: str  # kbs | gnews | cafef | tnck | vneconomy
    symbol: Optional[str] = None

    @property
    def key(self) -> str:
        return _norm_title(self.title)

    @property
    def source_name(self) -> str:
        return SOURCE_NAMES.get(self.source, self.source)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["published"] = self.published.isoformat() if self.published else None
        return d


def _norm_title(title: str) -> str:
    t = re.sub(r"\s+-\s+Vietstock(Finance)?\s*$", "", title.strip(), flags=re.I)
    return re.sub(r"\W+", " ", t.lower()).strip()


def _clean_gnews_title(title: str) -> str:
    return re.sub(r"\s+-\s+Vietstock(Finance)?\s*$", "", html.unescape(title).strip(), flags=re.I)


# Báo thường viết tên công ty thay vì mã. Khớp phân biệt hoa thường, theo biên từ.
ALIASES = {
    "VCB": ["Vietcombank"], "BID": ["BIDV"], "CTG": ["VietinBank", "Vietinbank"],
    "TCB": ["Techcombank"], "MBB": ["MBBank", "MB Bank", "Ngân hàng Quân đội"], "VPB": ["VPBank"],
    "ACB": ["Ngân hàng Á Châu"], "HDB": ["HDBank"], "STB": ["Sacombank"], "SHB": ["Ngân hàng SHB"],
    "FPT": ["Tập đoàn FPT"], "HPG": ["Hòa Phát", "Hoà Phát"], "MWG": ["Thế Giới Di Động", "Thế giới Di động"],
    "MSN": ["Masan"], "GAS": ["PV Gas", "PV GAS"], "VHM": ["Vinhomes"], "VIC": ["Vingroup"],
    "VNM": ["Vinamilk"], "SSI": ["Chứng khoán SSI"], "VRE": ["Vincom Retail"], "PLX": ["Petrolimex"],
    "VJC": ["Vietjet"], "SAB": ["Sabeco"], "GVR": ["Cao su Việt Nam"], "POW": ["PV Power"],
}

# Cụm chứa mã nhưng là doanh nghiệp khác (vd "FPT Retail" = FRT, "Masan Consumer" = MCH)
EXCLUDE = {
    "FPT": re.compile(r"FPT\s+(Retail|Shop|Long Châu|Telecom)", re.I),
    "MSN": re.compile(r"Masan\s+(Consumer|MEATLife|High-Tech|Hi-Tech)", re.I),
    "VIC": re.compile(r"Vingroup\s+Ventures", re.I),
}


def _mentions_symbol(title: str, symbol: str) -> bool:
    sym = symbol.upper()
    if sym in EXCLUDE:
        title = EXCLUDE[sym].sub(" ", title)
    if re.search(rf"(?<![A-Z0-9]){re.escape(sym)}(?![A-Z0-9])", title):
        return True
    return any(re.search(rf"(?<!\w){re.escape(a)}(?!\w)", title) for a in ALIASES.get(sym, ()))


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


# ---------------------------------------------------------------- RSS báo tài chính

def parse_rss(content: bytes, source: str) -> List[NewsItem]:
    """RSS 2.0 → NewsItem. Tiêu đề được html.unescape (Thanh Niên/CafeF có entity kép)."""
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return []
    out: List[NewsItem] = []
    for it in root.findall(".//item"):
        title = html.unescape(html.unescape((it.findtext("title") or "").strip()))
        link = (it.findtext("link") or "").strip()
        if not title or not link:
            continue
        pub = None
        raw = it.findtext("pubDate")
        if raw:
            try:
                pub = parsedate_to_datetime(raw)
                if pub.tzinfo is None:
                    pub = pub.replace(tzinfo=TZ_VN)
            except (TypeError, ValueError):
                pass
        out.append(NewsItem(title, link, pub, source))
    return out


_FEED_CACHE: Dict[str, List[NewsItem]] = {}


def fetch_press(timeout: int = 15) -> List[NewsItem]:
    """Tất cả PRESS_FEEDS (cache theo tiến trình). Feed lỗi → bỏ qua, không làm hỏng digest."""
    out: List[NewsItem] = []
    for source, _name, url in PRESS_FEEDS:
        if url not in _FEED_CACHE:
            try:
                r = requests.get(url, headers={"User-Agent": UA}, timeout=timeout)
                r.raise_for_status()
                _FEED_CACHE[url] = parse_rss(r.content, source)
            except Exception:
                _FEED_CACHE[url] = []
        out.extend(NewsItem(i.title, i.url, i.published, i.source) for i in _FEED_CACHE[url])
    return out


def fetch_symbol_news(symbol: str, days: int = 3, limit: int = 5) -> List[NewsItem]:
    """Tin của một mã: KBS + Google News Vietstock + báo tài chính (tiêu đề phải chứa mã)."""
    sym = symbol.upper()
    since = datetime.now(timezone.utc) - timedelta(days=days)
    items = fetch_kbs_news(sym)
    for it in fetch_gnews(f'"{sym}" site:vietstock.vn when:{days}d') + fetch_press():
        if _mentions_symbol(it.title, sym):
            it.symbol = sym
            items.append(it)
    items = [
        it for it in items
        if (it.published is None or it.published >= since) and not _is_noise(it.title)
    ]
    return _sort_newest(dedupe(items))[:limit]


def is_market_view(title: str) -> bool:
    t = title.lower()
    return any(p in t for p in MARKET_VIEW_PATTERNS)


def fetch_market_views(days: int = 1, limit: int = 10) -> List[NewsItem]:
    """Bài nhận định / PTKT thị trường chung: Vietstock (Google News) + báo tài chính."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    items = fetch_gnews(f"site:vietstock.vn when:{days}d") + fetch_press()
    items = [it for it in items if is_market_view(it.title) and (it.published is None or it.published >= since)]
    return _sort_newest(dedupe(items))[:limit]
