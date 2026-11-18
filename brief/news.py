"""Thu thập RSS -> SQLite, lọc trùng, phân mục, xếp hạng (xác định, không AI)."""

from __future__ import annotations

import re
import unicodedata
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from brief import db
from brief.check_sources import load_sources, local, looks_like_html, parse_date, strip_html
from brief.config import DB_PATH
from brief.http import fetch

# Mục mặc định theo nguồn; từ khoá có thể chuyển mục sang stock/gold.
SECTION_BY_SOURCE = {
    "vnexpress_thoisu": "vn_politics", "baochinhphu": "vn_politics", "tuoitre_thoisu": "vn_politics",
    "vnexpress_kinhdoanh": "vn_economy", "vneconomy_tinmoi": "vn_economy", "vneconomy_taichinh": "vn_economy",
    "tuoitre_kinhdoanh": "vn_economy", "vietstock_vimo": "vn_economy",
    "vneconomy_chungkhoan": "stock", "vietstock_cophieu": "stock", "vietstock_nhandinh": "stock",
    "cafef_chungkhoan": "stock", "tnck_chungkhoan": "stock", "cafef_doanhnghiep": "stock",
    "cafef_taichinh": "vn_economy",
    "vnexpress_noibat": "vn_politics", "vnexpress_batdongsan": "vn_economy",
    "cafef_vimo": "vn_economy", "cafef_batdongsan": "vn_economy", "cafef_quocte": "world",
    "gnews_vietstock": "vn_economy", "vietstock_vang": "gold",
    "vnexpress_thegioi": "world", "vneconomy_kinhtethegioi": "world", "gnews_reuters": "world",
    "gnews_apnews": "world", "bbc_world": "world", "bbc_business": "world", "bbc_vietnamese": "world",
    "ft_home": "world", "bloomberg_markets": "world",
}
SECTION_TITLES = {
    "vn_politics": "🇻🇳 Thời sự – Chính trị Việt Nam",
    "vn_economy": "💼 Kinh tế Việt Nam",
    "world": "🌍 Quốc tế",
    "stock": "📈 Chứng khoán",
    "gold": "🥇 Vàng – Tỷ giá",
}
SECTION_ORDER = ["vn_politics", "vn_economy", "world", "stock", "gold"]
SOURCE_PRIORITY = {"official": 3.0, "press": 2.0, "aggregator": 1.0}

GOLD_KW = ["gia vang", "vang mieng", "vang nhan", "sjc", "ty gia", "usd/vnd", "gold price"]
STOCK_KW = ["vn-index", "vnindex", "chung khoan", "co phieu", "hose", "hnx", "khoi ngoai", "thanh khoan"]
TOPIC_KW = [
    "chinh phu", "quoc hoi", "thu tuong", "nghi dinh", "nghi quyet", "luat", "bo chinh tri", "tong bi thu",
    "ngan hang nha nuoc", "nhnn", "lai suat", "ty gia", "lam phat", "cpi", "gdp", "xuat khau", "fdi",
    "dau tu cong", "thue", "trai phieu", "fed", "tariff", "thue quan", "inflation", "interest rate",
    "trump", "china", "trung quoc", "oil", "dau tho", "gia vang", "chung khoan", "vn-index",
]


def publisher(source_id: str) -> str:
    """Nhiều feed cùng một toà soạn -> 1 nhà xuất bản (để đếm 'N nguồn' đúng)."""
    return {"gnews_reuters": "reuters", "gnews_apnews": "ap", "gnews_vietstock": "vietstock"}.get(
        source_id, source_id.split("_")[0])


def has_kw(plain: str, kws: Iterable[str]) -> int:
    """Đếm từ khoá khớp NGUYÊN TỪ trên văn bản đã bỏ dấu (tránh 'hose' khớp trong từ khác)."""
    return sum(1 for k in kws if re.search(r"(?<![a-z0-9])" + re.escape(k.strip()) + r"(?![a-z0-9])", plain))


def strip_accents(s: str) -> str:
    s = unicodedata.normalize("NFD", s.replace("đ", "d").replace("Đ", "D"))
    return "".join(c for c in s if unicodedata.category(c) != "Mn").lower()


def canonical_url(url: str) -> str:
    try:
        p = urlsplit(url.strip())
    except ValueError:
        return url.strip()
    q = [(k, v) for k, v in parse_qsl(p.query) if not k.lower().startswith(("utm_", "fbclid", "gclid"))]
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/"), urlencode(q), ""))


def title_tokens(title: str) -> set[str]:
    t = re.sub(r"[^a-z0-9 ]+", " ", strip_accents(title))
    return {w for w in t.split() if len(w) > 1}


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def same_event(a: set[str], b: set[str], jaccard_min: float = 0.5) -> bool:
    """Cùng sự kiện nếu Jaccard đủ cao, hoặc tiêu đề ngắn hơn phần lớn nằm trong tiêu đề kia (≥5 từ chung)."""
    if not a or not b:
        return False
    inter = len(a & b)
    return jaccard(a, b) >= jaccard_min or (inter >= 5 and inter / min(len(a), len(b)) >= 0.6)


# ---------------------------------------------------------------- collect
def parse_items(body: bytes) -> list[dict[str, Any]]:
    root = ET.fromstring(body)
    out = []
    for it in (el for el in root.iter() if local(el.tag) in ("item", "entry")):
        rec: dict[str, Any] = {"title": "", "url": "", "summary": "", "published": None}
        for ch in it:
            t = local(ch.tag)
            if t == "title":
                rec["title"] = strip_html(ch.text)
            elif t == "link":
                rec["url"] = (ch.text or ch.get("href") or "").strip() or rec["url"]
            elif t in ("description", "summary") and not rec["summary"]:
                rec["summary"] = strip_html(ch.text)
            elif t in ("pubdate", "published", "updated", "date") and rec["published"] is None:
                rec["published"] = parse_date(ch.text)
        if rec["title"] and rec["url"]:
            out.append(rec)
    return out


def _fetch_source(src: dict[str, Any]) -> dict[str, Any]:
    res = fetch(src["url"])
    out: dict[str, Any] = {"src": src, "http": res.status, "elapsed": res.elapsed_s, "items": [], "error": None}
    if res.status in (401, 403, 429, 451):
        out["status"], out["error"] = "blocked", f"HTTP {res.status}"
    elif res.status in (404, 410):
        out["status"], out["error"] = "not_found", f"HTTP {res.status}"
    elif res.error:
        out["status"], out["error"] = "error", res.error
    elif looks_like_html(res):
        out["status"], out["error"] = "not_feed", "HTML thay vì RSS"
    else:
        try:
            out["items"] = parse_items(res.body)
            out["status"] = "ok" if out["items"] else "empty"
        except ET.ParseError as e:
            out["status"], out["error"] = "error", f"XML lỗi: {e}"[:200]
    return out


def collect(
    sources: Optional[list[dict[str, Any]]] = None,
    path: Path = DB_PATH,
    fetcher=_fetch_source,
    max_workers: int = 8,
) -> dict[str, dict[str, Any]]:
    """GET song song các nguồn RSS bật; lưu item mới; ghi fetch_log. Một nguồn lỗi không làm hỏng cả lượt."""
    sources = [s for s in (sources or load_sources()) if s.get("format") == "rss" and s.get("enabled", True)]
    started = db.now_utc()
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        results = list(ex.map(fetcher, sources))
    summary: dict[str, dict[str, Any]] = {}
    with db.connect(path) as con:
        for r in results:
            sid = r["src"]["id"]
            n_new = 0
            for it in r["items"][:200]:
                if sid.startswith("gnews_") and " - " in it["title"]:
                    it["title"] = it["title"].rsplit(" - ", 1)[0]  # bỏ hậu tố " - AP News"
                cur = con.execute(
                    "INSERT OR IGNORE INTO items(source_id, canonical_url, url, title, summary, published_at, fetched_at)"
                    " VALUES(?,?,?,?,?,?,?)",
                    (sid, canonical_url(it["url"]), it["url"], it["title"][:300], it["summary"][:1000],
                     db.iso(it["published"]), db.iso(started)),
                )
                n_new += cur.rowcount
            con.execute(
                "INSERT INTO fetch_log(source_id, started_at, status, http, n_items, n_new, elapsed_s, error)"
                " VALUES(?,?,?,?,?,?,?,?)",
                (sid, db.iso(started), r["status"], r["http"], len(r["items"]), n_new, r["elapsed"], r["error"]),
            )
            summary[sid] = {"status": r["status"], "n": len(r["items"]), "new": n_new, "error": r["error"]}
    db.kv_set("news_last_collect", db.iso(started), path)
    return summary


# ---------------------------------------------------------------- select
@dataclass
class Cluster:
    title: str
    summary: str
    url: str
    canonical_urls: list[str]
    sources: list[str]  # source ids
    kinds: list[str]
    published: Optional[datetime]
    section: str
    score: float = 0.0
    tokens: set[str] = field(default_factory=set)
    title_only_head: bool = False  # tiêu đề hiện tại lấy từ aggregator
    relevant: bool = True

    @property
    def publishers(self) -> list[str]:
        return list(dict.fromkeys(publisher(s) for s in self.sources))

    @property
    def title_only(self) -> bool:
        return all(k == "aggregator" for k in self.kinds)


def watchlist_hits(title: str, watchlist: Iterable[str]) -> set[str]:
    """Mã watchlist xuất hiện nguyên dạng IN HOA trong tiêu đề gốc."""
    # loại "TP.HCM", "USD/VND": mã phải đứng riêng, không dính dấu . / -
    return {w.upper() for w in watchlist} & set(re.findall(r"(?<![\w./-])([A-Z]{3})(?![\w/-])", title))


def _section_for(source_id: str, text_plain: str, title: str, watchlist: Iterable[str]) -> str:
    sec = SECTION_BY_SOURCE.get(source_id, "vn_economy")
    if has_kw(text_plain, GOLD_KW):
        return "gold"
    if has_kw(text_plain, STOCK_KW):
        return "stock"
    if sec == "vn_economy" and watchlist_hits(title, watchlist):
        return "stock"
    return sec


def select(
    window_start: datetime,
    window_end: datetime,
    exclude_urls: set[str],
    watchlist: list[str],
    caps: dict[str, int],
    max_items: int,
    jaccard_min: float = 0.5,
    path: Path = DB_PATH,
) -> list[Cluster]:
    kinds = {s["id"]: s["kind"] for s in load_sources()}
    names_rows = []
    with db.connect(path) as con:
        names_rows = con.execute(
            "SELECT source_id, canonical_url, url, title, summary, published_at FROM items "
            "WHERE published_at >= ? AND published_at <= ? ORDER BY published_at DESC",
            (db.iso(window_start), db.iso(window_end + timedelta(minutes=5))),
        ).fetchall()
    clusters: list[Cluster] = []
    for r in names_rows:
        if r["canonical_url"] in exclude_urls:
            continue
        toks = title_tokens(r["title"])
        target = next((c for c in clusters if r["canonical_url"] in c.canonical_urls), None) or next(
            (c for c in clusters if same_event(c.tokens, toks, jaccard_min)), None)
        kind = kinds.get(r["source_id"], "press")
        if target:
            if r["source_id"] not in target.sources:
                target.sources.append(r["source_id"])
                target.kinds.append(kind)
            if r["canonical_url"] not in target.canonical_urls:
                target.canonical_urls.append(r["canonical_url"])
            # ưu tiên bản có tóm tắt từ báo (không phải aggregator)
            if target.kinds[0] == "aggregator" and kind != "aggregator" and target.title_only_head:
                target.title, target.summary, target.url = r["title"], r["summary"], r["url"]
                target.section = _section_for(r["source_id"], strip_accents(r["title"] + " " + (r["summary"] or "")),
                                              r["title"], watchlist)
                target.title_only_head = False
            continue
        plain = strip_accents(r["title"] + " " + (r["summary"] or ""))
        clusters.append(Cluster(
            title=r["title"], summary=r["summary"] or "", url=r["url"],
            canonical_urls=[r["canonical_url"]], sources=[r["source_id"]], kinds=[kind],
            published=db.parse_iso(r["published_at"]),
            section=_section_for(r["source_id"], plain, r["title"], watchlist), tokens=toks,
            title_only_head=(kind == "aggregator"),
        ))
    for c in clusters:
        plain = strip_accents(c.title + " " + c.summary)
        score = max(SOURCE_PRIORITY.get(k, 1.0) for k in c.kinds)
        score += 1.5 * (len(c.publishers) - 1)
        score += 0.6 * has_kw(plain, TOPIC_KW)
        if watchlist_hits(c.title, watchlist):
            score += 2.0
        if c.published:
            age_h = (window_end - c.published).total_seconds() / 3600
            score += max(0.0, 2.0 - age_h / 6)
        c.score = round(score, 2)
        # Ngưỡng liên quan: không lấp đầy bằng tin vặt. Cần ít nhất một trong: nguồn chính thức,
        # ≥2 toà soạn cùng đưa, khớp chủ đề kinh tế/chính sách/thị trường, hoặc nhắc mã watchlist.
        c.relevant = ("official" in c.kinds or len(c.publishers) >= 2 or has_kw(plain, TOPIC_KW) > 0
                      or bool(watchlist_hits(c.title, watchlist)) or c.section in ("stock", "gold"))
    clusters = [c for c in clusters if c.relevant]
    picked: list[Cluster] = []
    for sec in SECTION_ORDER:
        sec_items = sorted((c for c in clusters if c.section == sec), key=lambda c: -c.score)
        picked.extend(sec_items[: caps.get(sec, 2)])
    picked = sorted(picked, key=lambda c: -c.score)[:max_items]
    return sorted(picked, key=lambda c: (SECTION_ORDER.index(c.section), -c.score))


def latest_gold_press(hours: int = 36, path: Path = DB_PATH) -> Optional[dict[str, Any]]:
    """Bài báo VN mới nhất có giá vàng trong nước (tham chiếu, chưa xác minh từ SJC)."""
    cut = db.iso(db.now_utc() - timedelta(hours=hours))
    with db.connect(path) as con:
        rows = con.execute(
            "SELECT source_id, url, title, summary, published_at FROM items WHERE published_at >= ? "
            "AND source_id NOT LIKE 'gnews_%' AND source_id NOT LIKE 'bbc_%' AND source_id NOT IN ('ft_home','bloomberg_markets') "
            "ORDER BY published_at DESC",
            (cut,),
        ).fetchall()
    for r in rows:
        plain = strip_accents(r["title"] + " " + (r["summary"] or ""))
        if "gia vang" in plain and ("sjc" in plain or "vang mieng" in plain or "vang nhan" in plain):
            return dict(r)
    return None
