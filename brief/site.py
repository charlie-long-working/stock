"""Dựng trang tĩnh site/index.html (một file, dữ liệu nhúng sẵn, mở trực tiếp bằng trình duyệt).

python -m brief site [--parts news,crypto,vn,metals]
Thư viện biểu đồ tải từ CDN (Chart.js 4.4.1, lightweight-charts 4.1.3) → cần internet khi xem.
Lần dựng có phần lỗi: giữ phần đó từ lần dựng trước (data.json) và ghi lỗi ở chân trang.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from brief import db
from brief.config import DB_PATH, ROOT

TEMPLATE = Path(__file__).with_name("site_template.html")
OUT_DIR = ROOT / "site"


def render(payload: Dict[str, Any]) -> str:
    data = json.dumps(payload, ensure_ascii=False, default=str, separators=(",", ":"))
    # thoát mọi "<" (và & >) thành \uXXXX: dữ liệu không thể đóng/mở thẻ <script> hay chú thích HTML
    data = data.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    html = TEMPLATE.read_text(encoding="utf-8")
    assert "/*__DATA__*/" in html
    return html.replace("/*__DATA__*/", data)


def rerender(out_dir: Path = OUT_DIR) -> str:
    """Dựng lại HTML từ data.json lần trước (khi chỉ sửa giao diện)."""
    payload = json.loads((out_dir / "data.json").read_text(encoding="utf-8"))
    (out_dir / "index.html").write_text(render(payload), encoding="utf-8")
    return str(out_dir / "index.html")


def build(parts: Optional[List[str]] = None, path: Path = DB_PATH, out_dir: Path = OUT_DIR) -> Dict[str, Any]:
    from brief import site_data
    out_dir.mkdir(parents=True, exist_ok=True)
    prev = {}
    pj = out_dir / "data.json"
    if pj.exists():
        try:
            prev = json.loads(pj.read_text(encoding="utf-8"))
        except Exception:
            prev = {}
    payload = site_data.build_payload(path, parts)
    for p in ("news", "crypto", "vn", "metals"):
        if p not in payload and p in prev:                       # phần không dựng lại lần này
            payload[p] = prev[p]
        elif isinstance(payload.get(p), dict) and payload[p].get("error") and p in prev and not prev[p].get("error"):
            payload["errors"][p] = payload[p]["error"] + " – đang hiển thị dữ liệu lần trước"
            payload[p] = prev[p]
    tmp = out_dir / "index.html.tmp"
    tmp.write_text(render(payload), encoding="utf-8")
    tmp.replace(out_dir / "index.html")
    pj.write_text(json.dumps(payload, ensure_ascii=False, default=str), encoding="utf-8")
    db.kv_set("site_last_build", {"at": db.iso(db.now_utc()), "errors": payload.get("errors", {}),
                                  "parts": parts or ["news", "crypto", "vn", "metals"]}, path)
    db.log_event("INFO" if not payload.get("errors") else "WARN", "site",
                 f"dựng trang: {(out_dir / 'index.html').stat().st_size // 1024} KB, lỗi: {payload.get('errors') or 'không'}", path)
    return {"path": str(out_dir / "index.html"), "kb": (out_dir / "index.html").stat().st_size // 1024,
            "errors": payload.get("errors", {})}
