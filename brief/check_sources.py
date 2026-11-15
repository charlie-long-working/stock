"""Mốc 0.5 – kiểm chứng nguồn: chỉ GET từng URL trong config/sources.toml và báo cáo.

Không ghi DB, không lưu nội dung bài, không gửi gì. Chỉ ghi thống kê (và giá công khai
của VCB/SJC) vào docs/source_check.md khi có --write.
"""

from __future__ import annotations

import html
import re
import sys
import tomllib
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

from brief.http import USER_AGENT, FetchResult, fetch

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "sources.toml"
DOC = ROOT / "docs" / "source_check.md"
TZ = ZoneInfo("Asia/Ho_Chi_Minh")
STALE_HOURS = 48
MIN_SUMMARY_CHARS = 20

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


# ---------------------------------------------------------------- helpers
def strip_html(text: Optional[str]) -> str:
    if not text:
        return ""
    return _WS_RE.sub(" ", html.unescape(_TAG_RE.sub(" ", text))).strip()


def local(tag: str) -> str:
    """Bỏ namespace: '{http://www.w3.org/2005/Atom}entry' -> 'entry'."""
    return tag.rsplit("}", 1)[-1].lower()


def parse_date(text: Optional[str]) -> Optional[datetime]:
    if not text:
        return None
    text = _WS_RE.sub(" ", text.replace(" ", " ").replace("\xa0", " ")).strip()
    try:
        dt = parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError):
        dt = None
    if dt is None:
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            dt = None
    if dt is None:
        # Báo Chính phủ / Tuổi Trẻ: "11/14/2026 4:32:00 PM" (kiểu Mỹ, không múi giờ)
        for fmt in ("%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %H:%M:%S", "%d/%m/%Y %H:%M:%S"):
            try:
                dt = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
    if dt is None:
        return None
    if dt.tzinfo is None:
        # Không có tz -> không đoán; coi là giờ VN và đánh dấu ở báo cáo qua 'naive_dates'.
        dt = dt.replace(tzinfo=TZ)
    return dt


def looks_like_html(res: FetchResult) -> bool:
    head = res.body[:2048].lstrip().lower()
    return "text/html" in res.content_type.lower() or head.startswith(b"<!doctype html") or head.startswith(b"<html")


# ---------------------------------------------------------------- result model
@dataclass
class Check:
    id: str
    name: str
    kind: str
    tier: str
    url: str
    status: str = "error"  # ok | stale | empty | blocked | not_found | not_feed | error
    http: Optional[int] = None
    elapsed_s: float = 0.0
    n_items: int = 0
    n_summary: int = 0
    avg_summary: int = 0
    full_text: bool = False
    newest: Optional[datetime] = None
    naive_dates: bool = False
    note: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def age_hours(self, now: datetime) -> Optional[float]:
        if self.newest is None:
            return None
        return round((now - self.newest).total_seconds() / 3600, 1)


# ---------------------------------------------------------------- parsers
def parse_feed(body: bytes) -> dict[str, Any]:
    """RSS 2.0 hoặc Atom. Trả về thống kê, không giữ nội dung bài."""
    root = ET.fromstring(body)
    items = [el for el in root.iter() if local(el.tag) in ("item", "entry")]
    n_summary = 0
    total_len = 0
    full_text = False
    newest: Optional[datetime] = None
    naive = False
    for it in items:
        summary = ""
        date_txt = None
        for ch in it:
            t = local(ch.tag)
            if t in ("description", "summary") and not summary:
                summary = strip_html(ch.text)
            elif t == "encoded" or (t == "content" and len(strip_html(ch.text)) > 500):
                full_text = True
            elif t in ("pubdate", "published", "updated", "date") and date_txt is None:
                date_txt = ch.text
        if len(summary) >= MIN_SUMMARY_CHARS:
            n_summary += 1
            total_len += len(summary)
        if date_txt:
            raw = date_txt.strip()
            dt = parse_date(raw)
            if dt is not None:
                if not re.search(r"([+-]\d{2}:?\d{2}|Z|GMT|UTC|[A-Z]{3})\s*$", raw):
                    naive = True
                if newest is None or dt > newest:
                    newest = dt
    return {
        "n_items": len(items),
        "n_summary": n_summary,
        "avg_summary": int(total_len / n_summary) if n_summary else 0,
        "full_text": full_text,
        "newest": newest,
        "naive_dates": naive,
    }


def parse_vcb(body: bytes) -> dict[str, Any]:
    root = ET.fromstring(body)
    out: dict[str, Any] = {"n_items": 0}
    for el in root.iter():
        t = local(el.tag)
        if t == "datetime" and el.text:
            out["datetime"] = el.text.strip()
        elif t == "exrate":
            out["n_items"] += 1
            if (el.get("CurrencyCode") or "").upper() == "USD":
                out["usd"] = {k: el.get(k) for k in ("Buy", "Transfer", "Sell")}
        elif t == "source" and el.text:
            out["source"] = el.text.strip()
    return out


def parse_sjc(body: bytes) -> dict[str, Any]:
    """Định dạng XML SJC không có tài liệu chính thức: quét mọi phần tử có thuộc tính buy/sell."""
    root = ET.fromstring(body)
    types: list[str] = []
    n = 0
    meta: dict[str, str] = {}
    for el in root.iter():
        attrs = {k.lower(): v for k, v in el.attrib.items()}
        if "updated" in attrs:
            meta["updated"] = attrs["updated"]
        if "unit" in attrs:
            meta["unit"] = attrs["unit"]
        if "buy" in attrs and "sell" in attrs:
            n += 1
            ty = attrs.get("type") or attrs.get("name") or ""
            if ty and ty not in types:
                types.append(ty)
    return {"n_items": n, "types": types, **meta}


# ---------------------------------------------------------------- runner
def classify_http(res: FetchResult) -> Optional[str]:
    if res.status in (401, 403, 429, 451):
        return "blocked"
    if res.status in (404, 410):
        return "not_found"
    if res.error:
        return "error"
    return None


def check_one(src: dict[str, Any], now: datetime) -> Check:
    c = Check(id=src["id"], name=src["name"], kind=src["kind"], tier=src["tier"], url=src["url"])
    res = fetch(src["url"])
    c.http, c.elapsed_s = res.status, res.elapsed_s
    bad = classify_http(res)
    if bad:
        c.status = bad
        c.note = res.error or ""
        if bad == "blocked" and looks_like_html(res):
            c.note += " (trang HTML – có thể là bot-challenge; không vượt)"
        return c
    if looks_like_html(res):
        c.status = "not_feed"
        c.note = "Trả về HTML thay vì XML (có thể challenge hoặc URL sai)"
        return c
    if res.truncated:
        c.note = "Phản hồi > 2 MB, đã cắt"
    fmt = src["format"]
    try:
        if fmt == "rss":
            st = parse_feed(res.body)
            c.n_items, c.n_summary, c.avg_summary = st["n_items"], st["n_summary"], st["avg_summary"]
            c.full_text, c.newest, c.naive_dates = st["full_text"], st["newest"], st["naive_dates"]
        elif fmt == "vcb_xml":
            c.extra = parse_vcb(res.body)
            c.n_items = c.extra.get("n_items", 0)
        elif fmt == "sjc_xml":
            c.extra = parse_sjc(res.body)
            c.n_items = c.extra.get("n_items", 0)
        else:
            c.status, c.note = "error", f"format không hỗ trợ: {fmt}"
            return c
    except ET.ParseError as e:
        c.status, c.note = "error", f"XML lỗi: {e}"[:200]
        return c
    if c.n_items == 0:
        c.status = "empty"
    else:
        age = c.age_hours(now)
        c.status = "stale" if (fmt == "rss" and age is not None and age > STALE_HOURS) else "ok"
    return c


def load_sources(path: Path = CONFIG) -> list[dict[str, Any]]:
    with path.open("rb") as f:
        data = tomllib.load(f)
    return data.get("source", [])


def fmt_dt(dt: Optional[datetime]) -> str:
    return dt.astimezone(TZ).strftime("%Y-%m-%d %H:%M") if dt else "—"


def render_markdown(checks: list[Check], now: datetime) -> str:
    lines = [
        "# Kiểm chứng nguồn (Mốc 0.5)",
        "",
        f"- Thời điểm chạy: **{now.astimezone(TZ).strftime('%Y-%m-%d %H:%M:%S')}** (Asia/Ho_Chi_Minh)",
        f"- Máy: Mac local, Python {sys.version.split()[0]}, thư viện chuẩn `urllib`",
        f"- User-Agent: `{USER_AGENT}` (không giả lập trình duyệt)",
        "- Mỗi URL: 1 GET, timeout 10 s, tối đa 1 lần retry cho lỗi mạng/5xx, giới hạn 2 MB.",
        "- Không lưu nội dung bài. Chỉ ghi thống kê. Kết quả là ảnh chụp một thời điểm, không phải SLA.",
        "",
        "Trạng thái: `ok` · `stale` (bài mới nhất > 48 h) · `empty` · `blocked` (401/403/429/451) · "
        "`not_found` · `not_feed` (trả HTML) · `error`.",
        "",
        "## Nguồn tin (RSS)",
        "",
        "| Nguồn | Loại | Tier | Trạng thái | HTTP | Số item | Có tóm tắt | Độ dài TB | Toàn văn | Bài mới nhất | Tuổi (h) | Ghi chú |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for c in checks:
        if c.id in ("vcb_fx", "sjc_xml"):
            continue
        note = c.note
        if c.kind == "aggregator" and c.status in ("ok", "stale"):
            note = (note + "; " if note else "") + "description chỉ là link + tên báo → coi như chỉ có tiêu đề"
        if c.naive_dates:
            note = (note + "; " if note else "") + "ngày không có múi giờ (giả định giờ VN)"
        lines.append(
            f"| {c.name} | {c.kind} | {c.tier} | `{c.status}` | {c.http or '—'} | {c.n_items} | "
            f"{c.n_summary}/{c.n_items} | {c.avg_summary} | {'có' if c.full_text else 'không'} | "
            f"{fmt_dt(c.newest)} | {c.age_hours(now) if c.newest else '—'} | {note} |"
        )
    lines += ["", "## Dữ liệu thị trường", ""]
    for c in checks:
        if c.id == "vcb_fx":
            usd = c.extra.get("usd") or {}
            lines += [
                f"### {c.name}",
                f"- Trạng thái: `{c.status}` · HTTP {c.http or '—'} · {c.elapsed_s}s · {c.note}",
                f"- `DateTime` trong XML: {c.extra.get('datetime', '—')} · số ngoại tệ: {c.n_items}",
                f"- USD: Mua {usd.get('Buy', '—')} / Chuyển khoản {usd.get('Transfer', '—')} / Bán {usd.get('Sell', '—')} (VND, giá niêm yết của VCB)",
                "",
            ]
        elif c.id == "sjc_xml":
            types = c.extra.get("types") or []
            lines += [
                f"### {c.name}",
                f"- Trạng thái: `{c.status}` · HTTP {c.http or '—'} · {c.elapsed_s}s · {c.note}",
                f"- Số dòng có buy/sell: {c.n_items} · updated: {c.extra.get('updated', '—')} · unit: {c.extra.get('unit', '—')}",
                f"- Loại vàng xuất hiện: {', '.join(types[:12]) if types else '—'}",
                f"- Có dòng vàng nhẫn: {'có' if any('nhẫn' in t.lower() or 'nhan' in t.lower() for t in types) else 'không thấy'}",
                "",
            ]
    return "\n".join(lines) + "\n"


def run(write: bool = False, tier: Optional[str] = None) -> list[Check]:
    now = datetime.now(timezone.utc)
    checks: list[Check] = []
    for src in load_sources():
        if tier and src.get("tier") != tier:
            continue
        c = check_one(src, now)
        checks.append(c)
        print(
            f"{c.status:10} http={str(c.http):4} items={c.n_items:3} "
            f"sum={c.n_summary:3} newest={fmt_dt(c.newest)}  {c.id}"
            + (f"  [{c.note}]" if c.note else ""),
            flush=True,
        )
    if write:
        DOC.parent.mkdir(parents=True, exist_ok=True)
        DOC.write_text(render_markdown(checks, now), encoding="utf-8")
        print(f"\nĐã ghi {DOC}")
    return checks
