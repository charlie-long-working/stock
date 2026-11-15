"""CLI: python -m brief <lệnh>. Mặc định chỉ in ra màn hình; --send mới gửi Telegram."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


def _print(html_text: str) -> None:
    from brief.telegram_api import html_to_plain
    print(html_to_plain(html_text))


def _send(html_text: str, brief_id: int | None = None) -> int:
    from brief.config import telegram_secret
    from brief.telegram_api import Api, send_text
    secret = telegram_secret()
    if not secret:
        print("Thiếu token/chat ID trong .env đã cấu hình.", file=sys.stderr)
        return 2
    res = send_text(Api(secret), secret.chat_id, html_text, brief_id=brief_id)
    for r in res:
        print(f"chunk {r['chunk']}: ok={r['ok']} message_id={r.get('message_id')} error={r.get('error')}"
              + (" (đã gửi trước đó, bỏ qua)" if r.get("skipped") else ""))
    return 0 if res and all(r["ok"] for r in res) else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="brief")
    sub = ap.add_subparsers(dest="cmd", required=True)
    cs = sub.add_parser("check-sources", help="GET từng nguồn và báo cáo")
    cs.add_argument("--write", action="store_true")
    cs.add_argument("--tier", choices=["core", "extended"])
    sub.add_parser("bot", help="Chạy bot Telegram (long polling, tiền cảnh)")
    for name in ("brief", "stock", "gold", "status"):
        p = sub.add_parser(name)
        p.add_argument("--send", action="store_true", help="Gửi tới chat cá nhân đã cấu hình")
        if name == "brief":
            p.add_argument("--full", action="store_true")
        if name in ("stock", "gold"):
            p.add_argument("--refresh", action="store_true")
    ev = sub.add_parser("evidence", help="Tạo gói bằng chứng cho AI (runs/...), không gửi")
    ev.add_argument("--full", action="store_true")
    si = sub.add_parser("site", help="Dựng trang tĩnh site/index.html (tin, BTC/ETH, chứng khoán, vàng bạc)")
    si.add_argument("--parts", help="news,crypto,vn,metals (mặc định: tất cả)")
    si.add_argument("--render-only", action="store_true", help="chỉ dựng lại HTML từ site/data.json")
    si.add_argument("--publish", action="store_true", help="dựng xong thì đẩy lên GitHub Pages")
    pu = sub.add_parser("publish", help="Đẩy site/index.html lên nhánh gh-pages (GitHub Pages)")
    pu.add_argument("--force", action="store_true", help="đẩy cả khi trang không đổi")
    pu.add_argument("--dry-run", action="store_true", help="chỉ tạo commit cục bộ, không push")
    sa = sub.add_parser("send-ai", help="Kiểm tra + gửi bản AI viết sẵn (<run_dir>/ai_brief.txt)")
    sa.add_argument("run_dir")
    sa.add_argument("--producer", default="Claude – phiên Claude Code Desktop, soạn thử nghiệm")
    sa.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    if args.cmd == "check-sources":
        from brief.check_sources import run
        run(write=args.write, tier=args.tier)
        return 0
    if args.cmd == "bot":
        from brief.bot import main as bot_main
        return bot_main()

    if args.cmd == "site":
        from brief import site
        if args.render_only:
            print(site.rerender())
            return 0
        r = site.build(args.parts.split(",") if args.parts else None)
        print(f"{r['path']} ({r['kb']} KB)" + (f" · lỗi: {r['errors']}" if r["errors"] else ""))
        if args.publish:
            from brief import publish
            print(publish.publish())
        return 0 if not r["errors"] else 1
    if args.cmd == "publish":
        from brief import publish
        print(publish.publish(force=args.force, dry_run=args.dry_run))
        return 0
    from brief import service
    if args.cmd == "brief":
        bid, text, mode = service.run_brief(full=args.full)
        _print(text)
        print(f"\n[brief_id={bid} mode={mode}]")
        return _send(text, bid) if args.send else 0
    if args.cmd in ("stock", "gold"):
        text = (service.stock_text if args.cmd == "stock" else service.gold_text)(force=args.refresh)
        _print(text)
        return _send(text) if args.send else 0
    if args.cmd == "status":
        text = service.status_text()
        _print(text)
        return _send(text) if args.send else 0
    if args.cmd == "evidence":
        from brief import ai, compose, db, market
        bid, _, clusters = compose.build_news_brief(full=args.full)
        with db.connect() as con:
            con.execute("UPDATE briefs SET status='evidence_only' WHERE id=?", (bid,))
        start, end, _, _ = compose.brief_window(args.full)
        from brief import news
        evd = ai.build_evidence(clusters, market.vn_market(), market.gold_market(), start, end, news.latest_gold_press())
        d = ai.save_run(evd, "manual")
        (d / "clusters.txt").write_text("\n".join("\t".join(c.canonical_urls) for c in clusters), encoding="utf-8")
        print(d)
        return 0
    if args.cmd == "send-ai":
        from brief import ai, compose
        d = Path(args.run_dir)
        evd = ai.load_run(d)
        raw = (d / "ai_brief.txt").read_text(encoding="utf-8").strip()
        errs = ai.validate(raw, evd)
        if errs:
            print("KHÔNG GỬI – bản AI không qua kiểm tra:")
            for x in errs:
                print("  -", x)
            return 1
        html_text = ai.render(raw, evd, args.producer)
        _print(html_text)
        if args.dry_run:
            return 0
        urls = [u for line in (d / "clusters.txt").read_text(encoding="utf-8").splitlines() for u in line.split("\t") if u]
        m = re.search(r"Khoảng tin: (.+?) → (.+)", evd["text"])
        n_ref = len(set(re.findall(r"\[N(\d+)\]", raw)))
        bid = compose.save_brief("news", "ai", html_text, None, None, urls,
                                 {"run_dir": str(d), "window": m.group(0) if m else ""}, n_items=n_ref)
        from brief import db
        with db.connect() as con:  # window_end = lúc tạo evidence để /brief sau đó lấy tin mới hơn
            con.execute("UPDATE briefs SET window_end=(SELECT created_at FROM briefs WHERE id=?) WHERE id=?", (bid, bid))
        print(f"[brief_id={bid}]")
        return _send(html_text, bid)
    return 2
