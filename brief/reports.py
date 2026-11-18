"""Trang nghiên cứu tĩnh đi kèm bảng tin: tab "Nghiên cứu" nhúng chúng bằng iframe.

Cấu hình trong config/settings.toml:
  [[site.reports]]  key, title, date, src (đường dẫn HTML, tương đối thư mục daily-brief), note (tuỳ chọn)
      → trang reports/<key>/ trên Pages và trong site/ khi dựng local.
  [site] extra_pages = {"đường/dẫn" = "file.html"}  (kiểu cũ, chỉ chép trang, không hiện trong tab)

Mọi trang được bọc thành tài liệu HTML đầy đủ (nguồn kiểu artifact không có <!doctype>) và chèn một shim nhỏ:
khi nằm trong iframe, trang gửi chiều cao cho trang cha và nhận lệnh đổi giao diện sáng/tối.
"""

from __future__ import annotations

import hashlib
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Tuple

from brief.config import ROOT

MARK = b"data-brief-embed"
SHIM = (b'<script ' + MARK + b'>(function(){if(window.parent===window)return;'
        b'var de=document.documentElement,last=0;'
        b'function h(){var v=Math.ceil(Math.max(de.scrollHeight,document.body?document.body.scrollHeight:0));'
        b'if(v!==last){last=v;parent.postMessage({type:"report-h",h:v},"*");}}'
        b'window.addEventListener("message",function(e){if(e.source!==parent)return;var d=e.data||{};'
        b'if(d.type==="theme"&&(d.theme==="light"||d.theme==="dark")){de.dataset.theme=d.theme;de.style.colorScheme=d.theme;}});'
        b'window.addEventListener("load",h);if(window.ResizeObserver)new ResizeObserver(h).observe(de);setInterval(h,1500);'
        b'parent.postMessage({type:"report-ready"},"*");})();</script>')


def prepare_page(html: bytes) -> bytes:
    """Bọc thành tài liệu đầy đủ (nếu thiếu <!doctype>) và chèn shim nhúng đúng một lần."""
    if not html.lstrip()[:15].lower().startswith(b"<!doctype"):
        html = (b'<!doctype html>\n<html lang="vi">\n<head>\n<meta charset="utf-8">\n'
                b'<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
                b"</head>\n<body>\n" + html + b"\n</body>\n</html>\n")
    if MARK in html:
        return html
    ends = [m.start() for m in re.finditer(rb"</body\s*>", html, re.I)]
    if ends:
        return html[:ends[-1]] + SHIM + b"\n" + html[ends[-1]:]
    return html + b"\n" + SHIM + b"\n"


def _safe_path(key: str) -> str | None:
    parts = [p for p in str(key).strip("/").split("/") if p]
    if not parts or any(p in (".", "..") or p.startswith(".") for p in parts):
        return None
    return "/".join(parts)


def load(site_cfg: Dict[str, Any], base: Path = ROOT) -> Tuple[Dict[str, bytes], Dict[str, str], List[Dict[str, Any]]]:
    """→ ({đường dẫn: HTML đã chuẩn bị}, {đường dẫn hoặc key: lỗi}, [meta báo cáo cho tab Nghiên cứu])."""
    pages: Dict[str, bytes] = {}
    errors: Dict[str, str] = {}
    meta: List[Dict[str, Any]] = []
    for key, src in sorted((site_cfg.get("extra_pages") or {}).items()):
        path = _safe_path(key)
        if not path:
            errors[key] = "đường dẫn không hợp lệ"
            continue
        f = (base / src).resolve()
        if not f.is_file():
            errors[key] = f"không thấy {f}"
            continue
        pages[path] = prepare_page(f.read_bytes())
    for r in site_cfg.get("reports") or []:
        key = str(r.get("key", ""))
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,60}", key):
            errors[key or "?"] = "key báo cáo không hợp lệ (chỉ a-z, 0-9, -)"
            continue
        path = f"reports/{key}"
        item = {"key": key, "title": r.get("title") or key, "date": r.get("date", ""), "note": r.get("note", ""),
                "path": path + "/"}
        f = (base / str(r.get("src", ""))).resolve()
        if not f.is_file():
            errors[key] = f"không thấy {f}"
            item["error"] = "chưa có trang"
        else:
            pages[path] = prepare_page(f.read_bytes())
            item["kb"] = len(pages[path]) // 1024
            item["v"] = hashlib.sha256(pages[path]).hexdigest()[:10]   # ?v= trong iframe: không dính cache trình duyệt/Pages
        meta.append(item)
    return pages, errors, meta


def write(out_dir: Path, pages: Dict[str, bytes], top_dirs: List[str] = ("reports",)) -> None:
    """Ghi trang vào out_dir/<đường dẫn>/index.html; xoá thư mục cũ của các trang để không còn báo cáo đã gỡ."""
    for d in {*top_dirs, *(p.split("/")[0] for p in pages)}:
        tgt = out_dir / d
        if tgt.is_dir() and tgt.resolve() != out_dir.resolve():
            shutil.rmtree(tgt)
    for path, body in pages.items():
        out = out_dir / path / "index.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(body)
