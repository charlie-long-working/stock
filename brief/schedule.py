"""Tự gửi bản tin theo lịch, chạy trong tiến trình bot (máy phải thức).

Quy tắc (cấu hình ở [schedule] trong settings.toml):
- Đến mốc `at` (giờ VN) thì gửi các phần `parts` của slot.
- Lỡ mốc vì máy ngủ hoặc bot tắt: khi bot chạy lại, gửi bù và ghi rõ "gửi bù". Đã quá `skip_after`
  thì bỏ qua, để bản sau bao phủ (bản tin luôn lấy tin kể từ bản đã gửi trước, nên không mất tin).
- Lỗi giữa chừng: thử lại sau `retry_min` phút, tối đa `max_attempts` lần. Phần nào đã gửi xong thì
  không gửi lại; phần tin tức gửi tiếp từ đoạn còn thiếu (deliveries theo brief_id).
- Trạng thái mỗi slot mỗi ngày lưu ở kv `sched:<ngày>:<slot>`.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime, time as dtime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

from brief import db
from brief.config import DB_PATH, TZ, load_settings

log = logging.getLogger("brief.schedule")

DONE = ("sent", "skipped_stale", "gave_up")
PART_NAMES = {"news": "tin tức", "stock": "chứng khoán", "gold": "vàng – tỷ giá"}


@dataclass(frozen=True)
class Slot:
    name: str
    label: str
    at: dtime
    skip_after: dtime
    parts: tuple[str, ...]


def _t(s: str) -> dtime:
    h, m = s.split(":")
    return dtime(int(h), int(m))


def load_config(settings: Optional[dict[str, Any]] = None) -> tuple[dict[str, Any], list[Slot]]:
    sc = dict((settings or load_settings()).get("schedule") or {})
    slots = [Slot(x["name"], x["label"], _t(x["at"]), _t(x["skip_after"]), tuple(x.get("parts", ["news"])))
             for x in sc.get("slots", [])]
    sc.setdefault("enabled", False)
    sc.setdefault("late_after_min", 20)
    sc.setdefault("retry_min", 10)
    sc.setdefault("max_attempts", 3)
    return sc, slots


def state_key(day, slot: Slot) -> str:
    return f"sched:{day.isoformat()}:{slot.name}"


def due_at(slot: Slot, now_local: datetime) -> datetime:
    return datetime.combine(now_local.date(), slot.at, tzinfo=now_local.tzinfo)


def decide(slot: Slot, now_local: datetime, state: Optional[dict[str, Any]], retry_min: int, max_attempts: int) -> str:
    """'wait' | 'run' | 'skip' | 'done'. Hàm thuần, không I/O."""
    st = (state or {}).get("status")
    if st in DONE:
        return "done"
    if now_local < due_at(slot, now_local):
        return "wait"
    if now_local.time() >= slot.skip_after:
        return "skip"
    if state:  # đã thử (failed/running do tiến trình chết giữa chừng)
        if state.get("attempts", 0) >= max_attempts:
            return "skip"
        last = db.parse_iso(state.get("last_at"))
        if last and now_local - last.astimezone(TZ) < timedelta(minutes=retry_min):
            return "wait"
    return "run"


class Scheduler:
    def __init__(self, send: Callable[[str, Optional[int]], list[dict[str, Any]]], news_lock: threading.Lock,
                 redact: Callable[[str], str] = lambda s: s, path: Path = DB_PATH,
                 settings: Optional[dict[str, Any]] = None):
        self.send, self.news_lock, self.redact, self.path = send, news_lock, redact, path
        self.settings = settings

    def tick(self, now: Optional[datetime] = None) -> list[tuple[str, str]]:
        """Kiểm tra mọi slot của hôm nay. Trả [(slot, hành động)] để log/test."""
        sc, slots = load_config(self.settings)
        if not sc["enabled"]:
            return []
        now = (now or datetime.now(TZ)).astimezone(TZ)
        out = []
        for slot in slots:
            key = state_key(now.date(), slot)
            state = db.kv_get(key, self.path)
            act = decide(slot, now, state, sc["retry_min"], sc["max_attempts"])
            if act == "skip":
                st = dict(state or {})
                st.update(status="gave_up" if state else "skipped_stale", closed_at=db.iso(db.now_utc()))
                db.kv_set(key, st, self.path)
                why = (f"bỏ cuộc sau {st.get('attempts', 0)} lần lỗi" if state
                       else f"lỡ mốc {slot.at:%H:%M}, đã quá {slot.skip_after:%H:%M} (máy ngủ/bot tắt)")
                db.log_event("WARN" if state else "INFO", "schedule", f"bản {slot.label} {now:%d/%m}: {why}", self.path)
                log.info("slot %s %s: %s", slot.name, now.date(), why)
            elif act == "run":
                self.run_slot(slot, now, state, sc)
            if act in ("skip", "run"):
                out.append((slot.name, act))
        return out

    def run_slot(self, slot: Slot, now: datetime, state: Optional[dict[str, Any]], sc: dict[str, Any]) -> dict[str, Any]:
        from brief import compose, market, service  # import muộn, tránh vòng import

        key = state_key(now.date(), slot)
        st = dict(state or {})
        st["parts"] = dict(st.get("parts") or {})
        st["attempts"] = st.get("attempts", 0) + 1
        st.update(status="running", last_at=db.iso(now))  # theo giờ của tick (test dùng giờ giả)
        db.kv_set(key, st, self.path)
        late = now - due_at(slot, now) > timedelta(minutes=sc["late_after_min"])
        header = f"⏰ <b>Bản tin {slot.label}</b> · lịch {slot.at:%H:%M}"
        if late:
            header += f" · <b>gửi bù lúc {now:%H:%M}</b> (lỡ mốc: máy ngủ, bot tắt hoặc lỗi mạng)"
        log.info("slot %s attempt %d%s", slot.name, st["attempts"], " (late)" if late else "")
        all_ok = True
        for part in slot.parts:
            p = dict(st["parts"].get(part) or {})
            if p.get("ok"):
                continue
            try:
                if part == "news":
                    if not p.get("text"):
                        with self.news_lock:
                            bid, html_text, mode = service.run_brief(path=self.path)
                        p = {"bid": bid, "mode": mode, "text": header + "\n" + html_text}
                        st["parts"][part] = p
                        db.kv_set(key, st, self.path)  # lưu trước khi gửi: lần thử sau gửi tiếp đúng bản này
                    res = self.send(p["text"], p["bid"])
                elif part == "stock":
                    vn = market.vn_market(path=self.path)
                    if vn.get("session") not in ("intraday", "closed_today"):
                        p = {"ok": True, "skipped": f"không có phiên hôm nay ({vn.get('session')})"}
                        st["parts"][part] = p
                        continue
                    res = self.send(compose.stock_text(vn), None)
                elif part == "gold":
                    res = self.send(service.gold_text(path=self.path), None)
                else:
                    raise ValueError(f"phần không hỗ trợ: {part}")
                p["ok"] = bool(res) and all(r["ok"] for r in res)
                p["msg_ids"] = [r.get("message_id") for r in res]
                if not p["ok"]:
                    p["error"] = self.redact("; ".join(str(r.get("error")) for r in res if not r["ok"]))[:200]
                else:
                    p.pop("error", None)
            except Exception as ex:
                log.exception("slot %s part %s failed", slot.name, part)
                p["ok"] = False
                p["error"] = self.redact(f"{type(ex).__name__}: {ex}")[:200]
            if p.get("ok"):
                p.pop("text", None)  # đã gửi xong thì bỏ nội dung, giữ kv gọn
            st["parts"][part] = p
            all_ok = all_ok and bool(p.get("ok"))
            db.kv_set(key, st, self.path)
        if all_ok:
            st["status"] = "sent"
            db.log_event("INFO", "schedule", f"đã gửi bản {slot.label} {now:%d/%m}{' (gửi bù)' if late else ''}", self.path)
        else:
            gave_up = st["attempts"] >= sc["max_attempts"]
            st["status"] = "gave_up" if gave_up else "failed"
            errs = "; ".join(f"{k}: {v.get('error')}" for k, v in st["parts"].items() if not v.get("ok"))
            db.log_event("ERROR" if gave_up else "WARN", "schedule",
                         f"bản {slot.label} {now:%d/%m} lần {st['attempts']}/{sc['max_attempts']} lỗi – {errs}"[:300],
                         self.path)
        st["late"] = late
        db.kv_set(key, st, self.path)
        return st


def status_lines(now: Optional[datetime] = None, path: Path = DB_PATH,
                 settings: Optional[dict[str, Any]] = None) -> list[str]:
    from brief.compose import e, fmt_local

    sc, slots = load_config(settings)
    if not sc["enabled"]:
        return ["⏸ Lịch tự gửi: đang tắt ([schedule] enabled = false)"]
    now = (now or datetime.now(TZ)).astimezone(TZ)
    lines = []
    for slot in slots:
        st = db.kv_get(state_key(now.date(), slot), path) or {}
        s = st.get("status")
        head = f"Bản {slot.label} {slot.at:%H:%M}: "
        if s == "sent":
            ids = [i for p in st.get("parts", {}).values() for i in (p.get("msg_ids") or []) if i]
            skipped = [PART_NAMES.get(k, k) for k, p in st.get("parts", {}).items() if p.get("skipped")]
            lines.append("✅ " + head + f"đã gửi {fmt_local(db.parse_iso(st.get('last_at')), with_date=False)}"
                         + (" (gửi bù)" if st.get("late") else "") + f" · {len(ids)} tin nhắn"
                         + (f" · bỏ phần {', '.join(skipped)} (không có phiên)" if skipped else ""))
        elif s == "skipped_stale":
            lines.append("⏭ " + head + f"không gửi – lỡ mốc và đã quá {slot.skip_after:%H:%M}")
        elif s == "gave_up":
            lines.append("❌ " + head + f"lỗi sau {st.get('attempts')} lần – xem cảnh báo bên dưới")
        elif s in ("failed", "running"):
            lines.append("⚠️ " + head + f"đang thử lại (lần {st.get('attempts')}/{sc['max_attempts']})"
                         + "".join(f" · {e(PART_NAMES.get(k, k))}: {e(v.get('error'))}"
                                   for k, v in st.get("parts", {}).items() if v.get("error")))
        elif now < due_at(slot, now):
            lines.append("⏳ " + head + "chờ đến giờ")
        else:
            lines.append("⏳ " + head + "đến giờ, sẽ gửi trong vòng 1 phút")
    lines.append("<i>Chỉ chạy khi máy thức. Lỡ mốc thì gửi bù khi máy thức lại, trừ khi đã quá "
                 + ", ".join(f"{s.skip_after:%H:%M} (bản {s.label})" for s in slots) + ".</i>")
    return lines


def site_due(now: datetime, settings: Optional[dict[str, Any]] = None, path: Path = DB_PATH) -> Optional[str]:
    """Mốc dựng lại trang tĩnh đã đến hạn mà hôm nay chưa dựng (bỏ qua nếu đã quá mốc kế tiếp)."""
    sc = (settings or load_settings()).get("site") or {}
    if not sc.get("enabled", False):
        return None
    now = now.astimezone(TZ)
    times = sorted(_t(x) for x in sc.get("rebuild_at", []))
    due = None
    for i, t in enumerate(times):
        if now.time() >= t and (i + 1 == len(times) or now.time() < times[i + 1]):
            due = t
    if due is None:
        return None
    key = f"site:{now.date().isoformat()}:{due:%H:%M}"
    return None if db.kv_get(key, path) else key


def site_tick(now: Optional[datetime] = None, path: Path = DB_PATH) -> Optional[dict[str, Any]]:
    key = site_due(now or datetime.now(TZ), path=path)
    if not key:
        return None
    from brief import site
    db.kv_set(key, {"status": "running", "at": db.iso(db.now_utc())}, path)
    try:
        r = site.build(path=path)
        db.kv_set(key, {"status": "done", "at": db.iso(db.now_utc()), "errors": r["errors"]}, path)
        log.info("site rebuilt %s (%s KB) errors=%s", key, r["kb"], r["errors"])
    except Exception as e:
        db.kv_set(key, {"status": "failed", "at": db.iso(db.now_utc()), "error": f"{type(e).__name__}: {e}"[:200]}, path)
        db.log_event("ERROR", "site", f"dựng trang lỗi: {type(e).__name__}: {str(e)[:200]}", path)
        log.exception("site build failed")
        return None
    r["publish"] = site_publish(path)
    return r


def site_publish(path: Path = DB_PATH) -> Optional[dict[str, Any]]:
    """Đẩy trang vừa dựng lên gh-pages (nếu [site] publish = true). Lỗi chỉ ghi log, không chặn bot."""
    from brief import publish
    if not publish.config()["enabled"]:
        return None
    try:
        p = publish.publish(path=path)
        log.info("site publish: %s", p)
        return p
    except Exception as e:
        db.log_event("ERROR", "site", f"đẩy trang lỗi: {type(e).__name__}: {str(e)[:200]}", path)
        log.exception("site publish failed")
        return {"status": "failed", "error": f"{type(e).__name__}: {e}"[:200]}


def run_forever(scheduler: Scheduler, stop: threading.Event, every_s: int = 30) -> None:
    """Vòng lặp trong thread riêng của bot. Khi máy thức dậy, đồng hồ thật nhảy -> tick kế tiếp gửi bù."""
    while True:
        try:
            for name, act in scheduler.tick():
                log.info("schedule %s -> %s", name, act)
        except Exception:
            log.exception("schedule tick failed")
        try:
            site_tick(path=scheduler.path)
        except Exception:
            log.exception("site tick failed")
        if stop.wait(every_s):
            return
