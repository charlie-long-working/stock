"""Dựng trang tĩnh site/index.html (một file, dữ liệu nhúng sẵn, mở trực tiếp bằng trình duyệt).

python -m brief site [--parts news,crypto,vn,metals]
Thư viện biểu đồ tải từ CDN (Chart.js 4.4.1, lightweight-charts 4.1.3) → cần internet khi xem.
Lần dựng có phần lỗi: giữ phần đó từ lần dựng trước (data.json), đánh dấu _stale và ghi lỗi ở chân trang.
Mỗi phần mang _built_at (giờ dựng thật của phần đó) → huy hiệu độ tươi đầu mỗi tab.
Báo cáo nghiên cứu ([[site.reports]]) được chép vào site/reports/<key>/ để xem local giống hệt Pages.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from brief import db, reports
from brief.config import DB_PATH, ROOT, load_settings

TEMPLATE = Path(__file__).with_name("site_template.html")
OUT_DIR = ROOT / "site"


def render(payload: Dict[str, Any]) -> str:
    data = json.dumps(payload, ensure_ascii=False, default=str, separators=(",", ":"))
    # thoát mọi "<" (và & >) thành \uXXXX: dữ liệu không thể đóng/mở thẻ <script> hay chú thích HTML
    data = data.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    html = TEMPLATE.read_text(encoding="utf-8")
    assert "/*__DATA__*/" in html
    return html.replace("/*__DATA__*/", data)


PARTS = ("news", "crypto", "vn", "metals")


def attach_reports(payload: Dict[str, Any], out_dir: Path, settings: Optional[dict] = None) -> None:
    """Chép báo cáo nghiên cứu vào out_dir và đưa danh sách vào payload["reports"] (lỗi không chặn trang)."""
    try:
        sc = (settings or load_settings()).get("site") or {}
        pages, errs, meta = reports.load(sc)
        reports.write(out_dir, pages)
        payload["reports"] = meta
        if errs:
            payload.setdefault("errors", {})["reports"] = "; ".join(f"{k}: {v}" for k, v in errs.items())[:400]
    except Exception as e:                                          # không để báo cáo phụ làm hỏng bảng tin
        payload["reports"] = []
        payload.setdefault("errors", {})["reports"] = f"{type(e).__name__}: {str(e)[:200]}"


def rerender(out_dir: Path = OUT_DIR, settings: Optional[dict] = None) -> str:
    """Dựng lại HTML từ data.json lần trước (khi chỉ sửa giao diện hoặc danh sách báo cáo)."""
    payload = json.loads((out_dir / "data.json").read_text(encoding="utf-8"))
    payload.get("errors", {}).pop("reports", None)
    attach_reports(payload, out_dir, settings)
    (out_dir / "index.html").write_text(render(payload), encoding="utf-8")
    return str(out_dir / "index.html")


def build(parts: Optional[List[str]] = None, path: Path = DB_PATH, out_dir: Path = OUT_DIR,
          settings: Optional[dict] = None) -> Dict[str, Any]:
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
    for p in PARTS:
        old = prev.get(p) if isinstance(prev.get(p), dict) else None
        if old is not None:
            old.setdefault("_built_at", prev.get("generated_iso"))  # data.json cũ chưa có _built_at
        if p not in payload and old is not None:                    # phần không dựng lại lần này
            payload[p] = old
        elif isinstance(payload.get(p), dict) and payload[p].get("error") and old is not None and not old.get("error"):
            payload["errors"][p] = payload[p]["error"] + " – đang hiển thị dữ liệu lần trước"
            old["_stale"] = payload[p]["error"]
            payload[p] = old
        elif isinstance(payload.get(p), dict):
            payload[p]["_built_at"] = payload["generated_iso"]
            payload[p].pop("_stale", None)
    attach_reports(payload, out_dir, settings)
    tmp = out_dir / "index.html.tmp"
    tmp.write_text(render(payload), encoding="utf-8")
    tmp.replace(out_dir / "index.html")
    pj.write_text(json.dumps(payload, ensure_ascii=False, default=str), encoding="utf-8")
    db.kv_set("site_last_build", {"at": db.iso(db.now_utc()), "errors": payload.get("errors", {}),
                                  "parts": parts or list(PARTS)}, path)
    db.log_event("INFO" if not payload.get("errors") else "WARN", "site",
                 f"dựng trang: {(out_dir / 'index.html').stat().st_size // 1024} KB, lỗi: {payload.get('errors') or 'không'}", path)
    return {"path": str(out_dir / "index.html"), "kb": (out_dir / "index.html").stat().st_size // 1024,
            "errors": payload.get("errors", {})}
