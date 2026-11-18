"""Lấy đoạn mở đầu bài báo (sapo + vài đoạn đầu) cho các tin đã chọn, để AI tóm tắt sát nội dung hơn RSS.

Tiết kiệm:
- Chỉ lấy cho tin ĐÃ ĐƯỢC CHỌN vào bản tin (≤ max_items), chỉ từ các báo trong [ai] article_hosts
  (mặc định vnexpress.net, cafef.vn); mỗi bài cắt ≤ article_chars ký tự.
- Mỗi URL chỉ tải MỘT lần: lưu bảng `articles` (SQLite), lần sau đọc lại; lỗi cũng được nhớ để không tải lại.
- Không vượt chặn: UA trung thực (brief/http.py), 403/429 → ghi 'blocked', bỏ qua; tải tuần tự 3 luồng, timeout ngắn.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import urlsplit

from brief import db
from brief.check_sources import strip_html
from brief.config import DB_PATH
from brief.http import fetch

DEFAULT_HOSTS = ("vnexpress.net", "cafef.vn")
_SAPO_RE = re.compile(
    r'<(p|h2|div|span)\b[^>]*?(?:class="[^"]*\b(?:description|sapo)\b[^"]*"|data-role="sapo")[^>]*>(.*?)</\1>',
    re.S | re.I)
_BODY_RE = re.compile(r'class="[^"]*\b(?:fck_detail|detail-content|article-content|content-detail)\b|data-role="content"', re.I)
_P_RE = re.compile(r"<p\b([^>]*)>(.*?)</p>", re.S | re.I)
_SKIP_P = re.compile(r'class="[^"]*\b(?:Image|author|caption|expEdit|link-source|PhotoCMS_Caption)\b', re.I)
_OG_RE = re.compile(r'<meta[^>]+property="og:description"[^>]+content="([^"]*)"', re.I)


def host_ok(url: str, hosts: Iterable[str]) -> bool:
    h = urlsplit(url).netloc.lower()
    return any(h == x or h.endswith("." + x) for x in hosts)


def extract(html_text: str, max_chars: int = 900) -> str:
    """Sapo + các đoạn đầu thân bài, cắt ở ranh giới câu/từ. Rỗng nếu không nhận ra cấu trúc."""
    parts: list[str] = []
    m = _SAPO_RE.search(html_text)
    if m:
        parts.append(strip_html(m.group(2)))
    elif (og := _OG_RE.search(html_text)):
        parts.append(strip_html(og.group(1)))
    b = _BODY_RE.search(html_text)
    if b:
        chunk = html_text[b.start(): b.start() + 120_000]
        for attrs, inner in _P_RE.findall(chunk):
            if _SKIP_P.search(attrs):
                continue
            t = strip_html(inner)
            if len(t) >= 40 and t not in parts:
                parts.append(t)
            if sum(len(x) for x in parts) >= max_chars:
                break
    text = " ".join(p for p in parts if p)
    if len(text) > max_chars:
        cut = text[:max_chars]
        dot = cut.rfind(". ")
        text = cut[: dot + 1] if dot > max_chars * 0.6 else cut.rsplit(" ", 1)[0] + "…"
    return text


def _get(url: str, max_chars: int) -> tuple[str, Optional[int], str]:
    r = fetch(url, timeout=8.0, max_bytes=1_500_000, retries=0)
    if r.status in (401, 403, 429, 451):
        return "blocked", r.status, ""
    if not r.ok:
        return "error", r.status, ""
    text = extract(r.body.decode("utf-8", "ignore"), max_chars)
    return ("ok" if text else "empty"), r.status, text


def pick_urls(clusters, hosts: Iterable[str] = DEFAULT_HOSTS) -> list[tuple[str, str]]:
    """Mỗi cụm tin → một (canonical_url, url) thuộc báo cho phép (cụm gộp nhiều báo: lấy bản CafeF/VnExpress)."""
    out = []
    for c in clusters:
        cu = next((u for u in c.canonical_urls if host_ok(u, hosts)), None)
        if cu:
            out.append((cu, c.url if host_ok(c.url, hosts) and cu == c.canonical_urls[0] else cu))
    return out


def leads(items: list[tuple[str, str]], hosts: Iterable[str] = DEFAULT_HOSTS, max_chars: int = 900,
          path: Path = DB_PATH, getter=_get) -> dict[str, str]:
    """items = [(canonical_url, url)] → {canonical_url: đoạn mở đầu}. Dùng cache; chỉ tải URL chưa có."""
    hosts = tuple(hosts)
    want = [(c, u) for c, u in items if u and host_ok(u, hosts)]
    if not want:
        return {}
    with db.connect(path) as con:
        rows = {r["canonical_url"]: r for r in con.execute(
            f"SELECT canonical_url, status, text FROM articles WHERE canonical_url IN ({','.join('?' * len(want))})",
            [c for c, _ in want])}
    todo = [(c, u) for c, u in want if c not in rows]
    if todo:
        with ThreadPoolExecutor(max_workers=3) as ex:
            got = list(ex.map(lambda cu: getter(cu[1], max_chars), todo))
        now = db.iso(db.now_utc())
        with db.connect(path) as con:
            con.executemany(
                "INSERT OR REPLACE INTO articles(canonical_url, url, fetched_at, status, http, text) VALUES(?,?,?,?,?,?)",
                [(c, u, now, st, http, text) for (c, u), (st, http, text) in zip(todo, got)])
        for (c, _), (st, _, text) in zip(todo, got):
            rows[c] = {"status": st, "text": text}
    return {c: rows[c]["text"] for c, _ in want if rows.get(c) and rows[c]["status"] == "ok" and rows[c]["text"]}
