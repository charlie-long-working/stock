"""Soạn văn bản Telegram (HTML) từ dữ liệu đã có. Template = không AI, chép nguyên tiêu đề/tóm tắt RSS."""

from __future__ import annotations

import html
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from brief import db, market, news
from brief.check_sources import load_sources
from brief.config import DB_PATH, TZ, load_settings

SOURCE_NAMES = {s["id"]: s["name"].split(" – ")[0].split(" (")[0] for s in load_sources()}
SOURCE_NAMES.update({"gnews_reuters": "Reuters*", "gnews_apnews": "AP*", "gnews_vietstock": "Vietstock*"})
INDEX_NAMES = {"VNINDEX": "VN-Index", "VN30": "VN30", "HNXINDEX": "HNX-Index"}
SESSION_TEXT = {
    "intraday": "đang trong phiên – số liệu chưa chốt",
    "closed_today": "phiên hôm nay đã đóng cửa",
    "weekend": "hôm nay cuối tuần – không có phiên; số liệu của phiên gần nhất",
    "pre_open": "chưa mở phiên hôm nay; số liệu của phiên gần nhất",
    "no_data_today": "⚠️ ngày thường nhưng chưa có dữ liệu phiên hôm nay (nghỉ lễ hoặc nguồn trễ – chưa xác minh)",
}


def e(s: Any) -> str:
    return html.escape(str(s), quote=False)


def vn_num(x: float, nd: int = 0) -> str:
    s = f"{x:,.{nd}f}"
    return s.replace(",", "§").replace(".", ",").replace("§", ".")


def signed_pct(p: float) -> str:
    return ("+" if p > 0 else "") + vn_num(p, 2) + "%"


def fmt_local(dt: Optional[datetime], with_date: bool = True) -> str:
    if not dt:
        return "—"
    d = dt.astimezone(TZ)
    return d.strftime("%d/%m %H:%M") if with_date else d.strftime("%H:%M")


def weekday_date(d: datetime) -> str:
    return f"{market.WEEKDAYS[d.weekday()]} {d.strftime('%d/%m/%Y')}"


def age_text(dt: Optional[datetime], now: datetime) -> str:
    if not dt:
        return ""
    h = (now - dt).total_seconds() / 3600
    return f"{int(h * 60)} phút trước" if h < 1 else f"{h:.0f} giờ trước"


# ---------------------------------------------------------------- stock
def stock_text(data: dict[str, Any], now: Optional[datetime] = None) -> str:
    now = now or db.now_utc()
    fetched = db.parse_iso(data.get("fetched_at"))
    lines = [f"📈 <b>CHỨNG KHOÁN VIỆT NAM</b>",
             f"Nguồn: vnstock (VCI) · lấy lúc {fmt_local(fetched)}"
             + (f" (bộ nhớ đệm {data['cache_age_min']:.0f}′)" if data.get("cache_age_min") else ""),
             f"Trạng thái: {e(SESSION_TEXT.get(data.get('session', ''), data.get('session', '')))}", ""]
    for ix in data.get("indices", []):
        chg = ix["close"] - ix["prev_close"]
        pct = chg / ix["prev_close"] * 100 if ix["prev_close"] else 0
        lines.append(
            f"• <b>{INDEX_NAMES.get(ix['symbol'], ix['symbol'])}</b> {vn_num(ix['close'], 2)} "
            f"({'+' if chg >= 0 else ''}{vn_num(chg, 2)} | {signed_pct(pct)}) · phiên {datetime.fromisoformat(ix['date']).strftime('%d/%m')}"
            f" · KL {vn_num(ix['volume'] / 1e6, 1)} tr"
        )
    wl = data.get("watchlist", [])
    if wl:
        up = sum(1 for w in wl if w["pct"] > 0)
        dn = sum(1 for w in wl if w["pct"] < 0)
        td = wl[0].get("trading_date") or "?"
        lines += ["", f"<b>Watchlist</b> ({len(wl)} mã – {e(data.get('watchlist_label', ''))}) · phiên {e(td)}",
                  f"Tăng {up} · Giảm {dn} · Đứng {len(wl) - up - dn}"]
        top = sorted(wl, key=lambda w: -w["pct"])
        fmt = lambda w: f"{w['symbol']} {vn_num(w['price'] / 1000, 2)} ({signed_pct(w['pct'])})"  # noqa: E731
        lines.append("▲ " + (", ".join(fmt(w) for w in top[:5] if w["pct"] > 0) or "—"))
        lines.append("▼ " + (", ".join(fmt(w) for w in reversed(top[-5:]) if w["pct"] < 0) or "—"))
        by_val = sorted(wl, key=lambda w: -w["value_bn"])[:3]
        lines.append("GTGD lớn nhất: " + ", ".join(f"{w['symbol']} {vn_num(w['value_bn'], 0)} tỷ" for w in by_val))
        fn = sorted(wl, key=lambda w: -w["foreign_net_bn"])
        buys = [w for w in fn[:3] if w["foreign_net_bn"] > 0]
        sells = [w for w in reversed(fn[-3:]) if w["foreign_net_bn"] < 0]
        if buys or sells:
            lines.append("Khối ngoại ròng (theo bảng giá VCI): mua " + (", ".join(f"{w['symbol']} {vn_num(w['foreign_net_bn'], 1)} tỷ" for w in buys) or "—")
                         + " · bán " + (", ".join(f"{w['symbol']} {vn_num(-w['foreign_net_bn'], 1)} tỷ" for w in sells) or "—"))
        lines.append("<i>Giá: nghìn đồng/cp, % so với giá tham chiếu. Không phải khuyến nghị; bot không tạo tín hiệu mua/bán.</i>")
    if data.get("errors"):
        lines += ["", "⚠️ Lỗi nguồn: " + e("; ".join(data["errors"])[:400])]
    return "\n".join(lines)


# ---------------------------------------------------------------- gold
def gold_text(g: dict[str, Any], press: Optional[dict[str, Any]], now: Optional[datetime] = None) -> str:
    now = now or db.now_utc()
    fetched = db.parse_iso(g.get("fetched_at"))
    lines = ["🥇 <b>VÀNG – TỶ GIÁ</b>", f"Lấy lúc {fmt_local(fetched)}", ""]
    gc = g.get("gc")
    if gc:
        bt = datetime.fromisoformat(gc["bar_time"])
        pct = (gc["price"] / gc["prev_close"] - 1) * 100 if gc["prev_close"] else 0
        stale = (now - bt) > timedelta(hours=3)
        lines += [
            "<b>Quốc tế</b> – COMEX GC=F (hợp đồng tương lai, Yahoo Finance, có thể trễ ~10–15′):",
            f"• {vn_num(gc['price'], 1)} USD/oz ({signed_pct(pct)} so với đóng cửa {datetime.fromisoformat(gc['prev_date']).strftime('%d/%m')})",
            f"• Nến 1h gần nhất: {fmt_local(bt)} giờ VN" + (f" ⚠️ dữ liệu cũ {age_text(bt, now)}"
                                                         + (" (cuối tuần, thị trường đóng)" if bt.astimezone(TZ).weekday() >= 4 and now.astimezone(TZ).weekday() >= 5 else "")
                                                         if stale else ""),
        ]
    else:
        lines.append("⚠️ Chưa lấy được giá vàng quốc tế.")
    vcb = g.get("vcb")
    lines.append("")
    if vcb:
        lines += ["<b>Tỷ giá USD/VND</b>",
                  f"• Vietcombank niêm yết ({fmt_local(datetime.fromisoformat(vcb['as_of'])) if vcb.get('as_of') else '—'}): "
                  f"Mua {vn_num(vcb['buy'])} · Chuyển khoản {vn_num(vcb['transfer'])} · Bán {vn_num(vcb['sell'])}"]
    vy = g.get("vnd_yahoo")
    if vy:
        lines.append(f"• Yahoo VND=X (tham chiếu quốc tế): {vn_num(vy['rate'])} · {fmt_local(datetime.fromisoformat(vy['bar_time']))}")
    if g.get("implied_vnd_luong"):
        lines += ["", "<b>Giá quy đổi</b> (KHÔNG phải giá bán lẻ; chưa gồm thuế, phí, chênh lệch nhập khẩu):",
                  f"• {vn_num(g['implied_vnd_luong'] / 1e6, 2)} triệu đồng/lượng = GC=F × VCB bán ra × 37,5/31,1035"]
    lines += ["", "<b>Vàng trong nước (SJC miếng, vàng nhẫn)</b>",
              "⚠️ Chưa có nguồn giá niêm yết tự động: " + e(g.get("domestic", {}).get("reason", ""))]
    if press:
        pub = db.parse_iso(press["published_at"])
        lines += [f"Tham chiếu báo chí (chưa xác minh lại từ SJC) – {e(SOURCE_NAMES.get(press['source_id'], press['source_id']))} · {fmt_local(pub)}:",
                  f"<a href=\"{e(press['url'])}\">{e(press['title'])}</a>",
                  f"<i>{e(press['summary'][:300])}</i>"]
    lines.append("<i>Mua vào = giá nơi bán mua lại từ khách; Bán ra = giá bán cho khách; chênh lệch = bán ra − mua vào.</i>")
    if g.get("errors"):
        lines.append("⚠️ Lỗi nguồn: " + e("; ".join(g["errors"])[:300]))
    return "\n".join(lines)


# ---------------------------------------------------------------- news brief
def brief_window(full: bool, path: Path = DB_PATH) -> tuple[datetime, datetime, set[str], Optional[datetime]]:
    s = load_settings()["brief"]
    end = db.now_utc()
    start = end - timedelta(hours=s["window_hours"])
    exclude: set[str] = set()
    last_sent: Optional[datetime] = None
    with db.connect(path) as con:
        row = con.execute("SELECT id, window_end FROM briefs WHERE kind='news' AND status='sent' "
                          "ORDER BY id DESC LIMIT 1").fetchone()
        if row:
            last_sent = db.parse_iso(row["window_end"])
        if not full:
            if last_sent and last_sent > start:
                start = last_sent - timedelta(minutes=30)  # chồng 30′ để không sót bài đăng trễ
            cut = db.iso(end - timedelta(hours=48))
            exclude = {r["canonical_url"] for r in con.execute(
                "SELECT r.canonical_url FROM brief_refs r JOIN briefs b ON b.id=r.brief_id "
                "WHERE b.status='sent' AND b.created_at >= ?", (cut,))}
    return start, end, exclude, last_sent


def item_line(i: int, c: news.Cluster, summary_chars: int) -> str:
    srcs = ", ".join(dict.fromkeys(SOURCE_NAMES.get(s, s) for s in c.sources))
    tag = " 🔗<i>chỉ tiêu đề</i>" if c.title_only else ""
    multi = f" ({len(c.publishers)} nguồn)" if len(c.publishers) > 1 else ""
    lines = [f"{i}. <b>{e(c.title)}</b>{tag}"]
    if c.summary and not c.title_only:
        s = c.summary if len(c.summary) <= summary_chars else c.summary[:summary_chars].rsplit(" ", 1)[0] + "…"
        lines.append(e(s))
    lines.append(f"— {e(srcs)}{multi} · {fmt_local(c.published)} · <a href=\"{e(c.url)}\">link</a>")
    return "\n".join(lines)


def news_template(clusters: list[news.Cluster], start: datetime, end: datetime,
                  vn: Optional[dict[str, Any]], gold: Optional[dict[str, Any]],
                  source_errors: list[str]) -> str:
    s = load_settings()["brief"]
    now_l = end.astimezone(TZ)
    head = [f"📰 <b>BẢN TIN</b> – {weekday_date(now_l)} · {now_l.strftime('%H:%M')} (giờ VN)",
            "Chế độ: 📋 <b>Template, không AI</b> – tiêu đề/tóm tắt chép nguyên từ RSS, chưa được tổng hợp lại.",
            f"Khoảng tin: {fmt_local(start)} → {fmt_local(end)} · {len(clusters)} mục"]
    body: list[str] = []
    i = 0
    for sec in news.SECTION_ORDER:
        items = [c for c in clusters if c.section == sec]
        if sec == "stock" and vn and vn.get("indices"):
            ix = vn["indices"][0]
            pct = (ix["close"] / ix["prev_close"] - 1) * 100
            body += ["", f"<b>{news.SECTION_TITLES[sec]}</b>",
                     f"Số liệu: VN-Index {vn_num(ix['close'], 2)} ({signed_pct(pct)}) phiên "
                     f"{datetime.fromisoformat(ix['date']).strftime('%d/%m')} – chi tiết: /stock"]
        elif sec == "gold" and gold and gold.get("gc"):
            body += ["", f"<b>{news.SECTION_TITLES[sec]}</b>",
                     f"Số liệu: GC=F {vn_num(gold['gc']['price'], 1)} USD/oz"
                     + (f" · VCB bán {vn_num(gold['vcb']['sell'])}" if gold.get("vcb") else "")
                     + " · giá SJC: chưa có nguồn tự động – chi tiết: /gold"]
        elif items:
            body += ["", f"<b>{news.SECTION_TITLES[sec]}</b>"]
        for c in items:
            i += 1
            body.append(item_line(i, c, s["summary_chars"]))
    if not clusters:
        body += ["", "Không có tin mới đáng kể trong khoảng này (không lấp đầy bằng tin cũ). Dùng /brief full để xem 24 giờ."]
    foot = ["", "<i>* qua Google News, chỉ có tiêu đề. 🔗 = chưa có tóm tắt từ báo gốc. "
                "Tin 1 nguồn chưa được đối chiếu. Telegram bên thứ ba: chưa kết nối.</i>"]
    if source_errors:
        foot.append("⚠️ Nguồn lỗi lượt này: " + e(", ".join(source_errors)))
    return "\n".join(head + body + foot)


def save_brief(kind: str, mode: str, text_html: str, start: Optional[datetime], end: Optional[datetime],
               urls: list[str], meta: Optional[dict[str, Any]] = None, path: Path = DB_PATH,
               n_items: Optional[int] = None) -> int:
    import json
    with db.connect(path) as con:
        cur = con.execute(
            "INSERT INTO briefs(created_at, kind, mode, window_start, window_end, n_items, text_html, status, meta)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            (db.iso(db.now_utc()), kind, mode, db.iso(start), db.iso(end),
             n_items if n_items is not None else len(urls), text_html, "built",
             json.dumps(meta or {}, ensure_ascii=False)),
        )
        bid = cur.lastrowid
        con.executemany("INSERT OR IGNORE INTO brief_refs(brief_id, canonical_url) VALUES(?,?)",
                        [(bid, u) for u in urls])
    return int(bid)


def build_news_brief(full: bool = False, path: Path = DB_PATH) -> tuple[int, str, list[news.Cluster]]:
    """Thu thập -> chọn -> template. Trả (brief_id, html, clusters). Chưa gửi."""
    s = load_settings()
    summary = news.collect(path=path)
    errors = [k for k, v in summary.items() if v["status"] not in ("ok", "empty") and not k.startswith("vietstock_")]
    start, end, exclude, _ = brief_window(full, path)
    wl, _ = market.load_watchlist(s)
    clusters = news.select(start, end, exclude, wl, s["brief"]["caps"], s["brief"]["max_items"],
                           s["brief"]["dedup_jaccard"], path)
    vn = gold = None
    try:
        vn = market.vn_market(path=path)
    except Exception as ex:  # một nguồn lỗi không làm hỏng bản tin
        db.log_event("WARN", "brief", f"vn_market: {type(ex).__name__}", path)
    try:
        gold = market.gold_market(path=path)
    except Exception as ex:
        db.log_event("WARN", "brief", f"gold_market: {type(ex).__name__}", path)
    text = news_template(clusters, start, end, vn, gold, errors)
    urls = [u for c in clusters for u in c.canonical_urls]
    bid = save_brief("news", "template", text, start, end, urls, {"full": full}, path, n_items=len(clusters))
    return bid, text, clusters
