"""Các thao tác cấp cao dùng chung cho bot và CLI."""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from brief import ai, article, compose, db, market, news, schedule
from brief.check_sources import load_sources
from brief.config import DB_PATH, ROOT, TZ, WORKSPACE, load_settings

STATUS_ICON = {"ok": "✅", "empty": "⚪", "blocked": "⛔", "not_found": "❌", "not_feed": "❌", "error": "❌"}


def run_brief(full: bool = False, path: Path = DB_PATH) -> tuple[int, str, str]:
    """Trả (brief_id, html, mode). AI chỉ khi bật, đã đăng nhập và qua kiểm tra; nếu không -> template.

    Một lời gọi Claude cho cả bản tin. Đoạn mở đầu bài (CafeF/VnExpress…) chỉ tải cho tin đã chọn, có cache.
    Bản AI lỗi vài mục → bỏ mục lỗi (salvage), không gọi lại.
    """
    bid, text, clusters = compose.build_news_brief(full=full, path=path)
    ok, why = ai.ai_status()
    if not ok or not clusters:
        return bid, text, "template"
    cfg = load_settings()["ai"]
    start, end, _, _ = compose.brief_window(full, path)
    vn, gold = market.vn_market(path=path), market.gold_market(path=path)
    leads: dict[str, str] = {}
    if cfg.get("fetch_articles", True):
        try:
            hosts = cfg.get("article_hosts", article.DEFAULT_HOSTS)
            leads = article.leads(article.pick_urls(clusters, hosts), hosts, cfg.get("article_chars", 900), path)
        except Exception as ex:                                  # không có đoạn mở đầu thì vẫn dùng RSS
            db.log_event("WARN", "ai", f"article.leads: {type(ex).__name__}: {str(ex)[:150]}", path)
    ev = ai.build_evidence(clusters, vn, gold, start, end, news.latest_gold_press(path=path), leads)
    run_dir = ai.save_run(ev, "bot")
    out, err = ai.run_cli(ev, run_dir)
    if out:
        (run_dir / "ai_raw.txt").write_text(out, encoding="utf-8")
        errs = ai.validate(out, ev)
        note = ""
        if errs:
            fixed, dropped = ai.salvage(out, ev)
            if fixed:
                (run_dir / "ai_dropped.txt").write_text("\n".join(errs + ["--"] + dropped), encoding="utf-8")
                db.log_event("INFO", "ai", f"bỏ {len(dropped)} dòng không qua kiểm tra: {'; '.join(errs[:2])}", path)
                out, errs, note = fixed, [], f"\n<i>Đã bỏ {len(dropped)} dòng AI không khớp dữ liệu nguồn.</i>"
        if not errs:
            html_text = ai.render(out, ev, f"Claude {cfg.get('model', 'sonnet')}") + note
            urls = [u for c in clusters for u in c.canonical_urls]
            with db.connect(path) as con:  # bản template thay bằng bản AI
                con.execute("UPDATE briefs SET status='superseded' WHERE id=?", (bid,))
            nbid = compose.save_brief("news", "ai", html_text, start, end, urls,
                                      {"run_dir": str(run_dir), "leads": len(leads),
                                       "usage": db.kv_get("ai_last_usage", path)}, path, n_items=len(clusters))
            return nbid, html_text, "ai"
        err = "bản AI không qua kiểm tra: " + "; ".join(errs[:3])
    db.log_event("WARN", "ai", err, path)
    return bid, text + f"\n\n⚠️ AI không dùng được lượt này ({compose.e(err)}) – đang hiển thị template.", "template"


def stock_text(force: bool = False, path: Path = DB_PATH) -> str:
    return compose.stock_text(market.vn_market(force=force, path=path))


def gold_text(force: bool = False, path: Path = DB_PATH) -> str:
    g = market.gold_market(force=force, path=path)
    if not db.kv_get("news_last_collect", path):
        news.collect(path=path)
    return compose.gold_text(g, news.latest_gold_press(path=path))


def status_text(started_at: datetime | None = None, path: Path = DB_PATH) -> str:
    now = db.now_utc()
    lines = ["🩺 <b>TRẠNG THÁI</b> · " + compose.fmt_local(now)]
    if started_at:
        lines.append(f"Bot chạy từ {compose.fmt_local(started_at)} · PID {os.getpid()} · máy local (dừng khi máy ngủ/tắt)")
    ok, why = ai.ai_status()
    lines.append(f"AI: {'🤖 ' if ok else '📋 '}{compose.e(why)}")
    u = db.kv_get("ai_last_usage", path)
    if u:
        lines.append(f"Lần gọi AI gần nhất {compose.e(u.get('at', '')[:16].replace('T', ' '))}: "
                     f"{u.get('input_tokens') or 0}+{u.get('cache_read') or 0} token vào (cache), {u.get('output_tokens') or 0} ra, "
                     f"{u.get('seconds')} s{' · LỖI' if u.get('is_error') else ''}")
    lines.append("Telegram bên thứ ba: ⛔ chưa kết nối (chưa có phiên Telegram client và danh sách chat nguồn)")
    lines += ["", "<b>Lịch tự gửi hôm nay</b>"] + schedule.status_lines(path=path)
    names = {s["id"]: s["name"] for s in load_sources()}
    with db.connect(path) as con:
        rows = con.execute(
            "SELECT f.* FROM fetch_log f JOIN (SELECT source_id, MAX(id) mid FROM fetch_log GROUP BY source_id) x "
            "ON f.id = x.mid ORDER BY f.source_id").fetchall()
        last_ok = {r["source_id"]: r["t"] for r in con.execute(
            "SELECT source_id, MAX(started_at) t FROM fetch_log WHERE status='ok' GROUP BY source_id")}
        brief = con.execute("SELECT * FROM briefs WHERE kind='news' AND status IN ('sent','partial','failed') "
                            "ORDER BY id DESC LIMIT 1").fetchone()
        errs = con.execute("SELECT at, component, message FROM events WHERE level IN ('WARN','ERROR') "
                           "ORDER BY id DESC LIMIT 3").fetchall()
        n_items = con.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    lc = db.parse_iso(db.kv_get("news_last_collect", path))
    lines += ["", f"<b>Nguồn tin</b> – lần thu gần nhất {compose.fmt_local(lc)} · {n_items} bài trong kho"]
    if not rows:
        lines.append("Chưa thu thập lần nào. Gõ /brief.")
    for r in rows:
        icon = STATUS_ICON.get(r["status"], "❔")
        extra = f" · {r['n_items']} bài" if r["status"] == "ok" else f" · {compose.e(r['error'] or r['status'])}"
        lo = db.parse_iso(last_ok.get(r["source_id"]))
        if r["status"] != "ok":
            extra += f" · lần OK gần nhất: {compose.fmt_local(lo) if lo else 'chưa có'}"
        if r["source_id"].startswith("vietstock_"):
            extra += " (đã thay bằng Google News)"
        lines.append(f"{icon} {compose.e(names.get(r['source_id'], r['source_id']))}{extra}")
    lines += ["", "<b>Thị trường</b>"]
    for key, label in (("market_vn", "Chứng khoán (vnstock VCI)"), ("market_gold", "Vàng/tỷ giá (Yahoo, VCB)")):
        d = db.kv_get(key, path)
        if not d:
            lines.append(f"⚪ {label}: chưa lấy")
            continue
        t = db.parse_iso(d.get("fetched_at"))
        lines.append(f"{'⚠️' if d.get('errors') else '✅'} {label}: {compose.fmt_local(t)}"
                     + (f" · lỗi: {compose.e('; '.join(d['errors'])[:150])}" if d.get("errors") else ""))
    lines.append("⛔ Giá SJC/vàng nhẫn: chưa có nguồn tự động (sjc.com.vn chặn bot, XML cũ 404)")
    snap = WORKSPACE / "stock" / "vn_stock" / "data" / "screening" / "hourly_vn_snapshot.json"
    if snap.exists():
        import json
        try:
            ga = json.loads(snap.read_text())["generated_at"]
            lines.append(f"ℹ️ Snapshot local repo stock: {ga[:16]} – cũ, không dùng (bot lấy trực tiếp từ VCI)")
        except Exception:
            pass
    lines += ["", "<b>Bản tin gần nhất</b>"]
    if brief:
        lines.append(f"{compose.fmt_local(db.parse_iso(brief['created_at']))} · {brief['mode']} · {brief['n_items']} mục · {brief['status']}")
    else:
        lines.append("Chưa gửi bản nào.")
    if errs:
        lines += ["", "<b>Cảnh báo gần nhất</b>"] + [
            f"{compose.fmt_local(db.parse_iso(r['at']))} [{compose.e(r['component'])}] {compose.e(r['message'][:150])}" for r in errs]
    return "\n".join(lines)
