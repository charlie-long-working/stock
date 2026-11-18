"""Đẩy site/index.html lên nhánh gh-pages của repo stock (public) → GitHub Actions deploy Pages.

python -m brief publish [--force] [--dry-run]

- Repo làm việc riêng ở var/pages-repo (không đụng cây làm việc của ../stock).
- Mỗi lần đẩy là một commit mồ côi + force push: nhánh gh-pages luôn chỉ có 1 commit, repo không phình
  dù trang ~2.5 MB dựng 2 lần/ngày.
- Bỏ qua nếu index.html không đổi so với lần đẩy trước (trừ --force).
- Workflow deploy (brief/pages_workflow.yml) được chép kèm vào nhánh, nên push là đủ để kích hoạt CI.
- Trang phụ ([site] extra_pages) và báo cáo ([[site.reports]] → reports/<key>/) được chép thành <đường dẫn>/index.html;
  đổi nội dung chúng cũng tính là thay đổi.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

from brief import db, reports
from brief.config import DB_PATH, ROOT, VAR, load_settings
from brief.site import OUT_DIR

WORKFLOW = Path(__file__).with_name("pages_workflow.yml")
REPO_DIR = VAR / "pages-repo"
KV_KEY = "site_last_publish"

README = """# Bảng tin thị trường (trang tĩnh)

Nhánh này được tạo tự động bởi bot daily-brief (máy cá nhân), mỗi lần dựng lại trang sẽ ghi đè bằng một commit mới.
Không sửa tay. Dữ liệu: tin RSS 24h (tiêu đề, trích đoạn, link gốc), BTC/ETH, cổ phiếu VN, vàng bạc.
Thông tin tham khảo, không phải khuyến nghị đầu tư.
"""


def _git(repo: Path, *args: str, timeout: int = 120) -> str:
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_SSH_COMMAND="ssh -o BatchMode=yes -o ConnectTimeout=20")
    git = shutil.which("git") or "/usr/bin/git"
    r = subprocess.run([git, "-C", str(repo), *args], capture_output=True, text=True, timeout=timeout, env=env)
    if r.returncode != 0:
        raise RuntimeError(f"git {args[0]} lỗi ({r.returncode}): {(r.stderr or r.stdout).strip()[:300]}")
    return r.stdout.strip()


def config(settings: Optional[dict] = None) -> Dict[str, Any]:
    sc = (settings or load_settings()).get("site") or {}
    return {"enabled": bool(sc.get("publish", False)),
            "remote": sc.get("publish_remote", ""),
            "branch": sc.get("publish_branch", "gh-pages"),
            "url": sc.get("page_url", ""),
            "extra_pages": dict(sc.get("extra_pages") or {}),
            "reports": list(sc.get("reports") or [])}


def extra_pages(cfg: Dict[str, Any], base: Path = ROOT) -> tuple[Dict[str, bytes], Dict[str, str]]:
    """Trang phụ + báo cáo nghiên cứu: {đường dẫn: HTML đã chuẩn bị}, {đường dẫn/key: lỗi} (xem brief/reports.py)."""
    pages, errors, _ = reports.load(cfg, base)
    return pages, errors


def publish(force: bool = False, dry_run: bool = False, settings: Optional[dict] = None,
            site_dir: Path = OUT_DIR, repo_dir: Path = REPO_DIR, path: Path = DB_PATH) -> Dict[str, Any]:
    cfg = config(settings)
    if not cfg["remote"]:
        raise RuntimeError("thiếu [site] publish_remote trong config/settings.toml")
    index = site_dir / "index.html"
    html = index.read_bytes()
    pages, page_errors = extra_pages(cfg)
    h = hashlib.sha256(html)
    for key, body in pages.items():
        h.update(b"\0" + key.encode() + b"\0" + body)
    digest = h.hexdigest()
    last = db.kv_get(KV_KEY, path) or {}
    if not force and last.get("sha256") == digest:
        return {"status": "unchanged", "sha256": digest[:12], "url": cfg["url"]}

    meta: Dict[str, Any] = {"published_at": db.iso(db.now_utc()), "kb": len(html) // 1024, "sha256": digest,
                            "extra_pages": sorted(pages)}
    if page_errors:
        meta["extra_page_errors"] = page_errors
    try:
        data = json.loads((site_dir / "data.json").read_text(encoding="utf-8"))
        meta.update(generated_at=data.get("generated_at"), errors=data.get("errors") or {})
    except Exception:
        pass

    if not (repo_dir / ".git").exists():
        repo_dir.mkdir(parents=True, exist_ok=True)
        _git(repo_dir, "init", "-q", "-b", cfg["branch"])
    for f in repo_dir.iterdir():                                   # chỉ giữ đúng các file của lần này
        if f.name != ".git":
            shutil.rmtree(f) if f.is_dir() else f.unlink()
    (repo_dir / "index.html").write_bytes(html)
    reports.write(repo_dir, pages)
    (repo_dir / ".nojekyll").write_text("")
    (repo_dir / "README.md").write_text(README, encoding="utf-8")
    (repo_dir / "publish.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    wf = repo_dir / ".github" / "workflows"
    wf.mkdir(parents=True)
    shutil.copy(WORKFLOW, wf / "pages.yml")

    _git(repo_dir, "add", "-A")
    tree = _git(repo_dir, "write-tree")
    msg = f"Bảng tin {meta.get('generated_at') or meta['published_at']}"
    commit = _git(repo_dir, "commit-tree", tree, "-m", msg)       # commit mồ côi: không giữ lịch sử
    _git(repo_dir, "update-ref", f"refs/heads/{cfg['branch']}", commit)
    _git(repo_dir, "symbolic-ref", "HEAD", f"refs/heads/{cfg['branch']}")
    if dry_run:
        return {"status": "dry-run", "commit": commit[:10], "sha256": digest[:12], "url": cfg["url"]}

    _git(repo_dir, "push", "-q", "--force", cfg["remote"], f"{commit}:refs/heads/{cfg['branch']}")
    db.kv_set(KV_KEY, {"at": meta["published_at"], "sha256": digest, "commit": commit, "kb": meta["kb"]}, path)
    db.log_event("INFO", "site", f"đẩy trang lên {cfg['branch']} ({meta['kb']} KB, {commit[:10]})", path)
    return {"status": "pushed", "commit": commit[:10], "kb": meta["kb"], "url": cfg["url"]}
