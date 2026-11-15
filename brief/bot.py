"""Bot Telegram long-polling (getUpdates). Chỉ trả lời chat cá nhân đã cấu hình.

An toàn với hệ cảnh báo hiện có: các workflow kia chỉ gọi sendMessage, không đọc updates.
Nếu Telegram báo 409 (có webhook hoặc tiến trình khác đang getUpdates) -> dừng, không tranh chấp.
"""

from __future__ import annotations

import logging
import os
import signal
import threading
import time
from datetime import datetime
from logging.handlers import RotatingFileHandler
from typing import Any, Callable, Optional

from brief import db, schedule, service
from brief.config import LOG_DIR, TelegramSecret, load_settings, redact, telegram_secret
from brief.telegram_api import Api, TelegramError, send_text

HELP = """🤖 <b>Trợ lý thông tin cá nhân</b> (chạy local trên Mac)

/brief – tin mới kể từ bản trước (tối đa 12 mục, có nguồn, giờ, link)
/brief full – tin 24 giờ qua, không loại tin đã gửi
/stock – chỉ số VN-Index/VN30/HNX + watchlist (vnstock VCI)
/gold – vàng COMEX, tỷ giá Vietcombank, giá quy đổi, tham chiếu giá trong nước
/status – trạng thái nguồn, lần cập nhật, lỗi gần nhất
/help – hướng dẫn này

⏰ Tự gửi: bản sáng 08:15 (tin + vàng/tỷ giá), bản chiều 16:30 (tin + chứng khoán nếu có phiên + vàng/tỷ giá).
Máy ngủ lúc đến giờ thì gửi bù khi máy thức, trừ khi đã quá 15:00 (bản sáng) / 23:00 (bản chiều).

Ghi chú:
• 📋 Template = chép nguyên tiêu đề/tóm tắt từ RSS; 🤖 AI = do Claude tổng hợp (chỉ khi bật).
• ⚠️ = dữ liệu cũ/lỗi; 🔗 = chỉ có tiêu đề; tin 1 nguồn chưa được đối chiếu.
• Không có tín hiệu mua/bán, không đặt lệnh.
• Bot dừng khi máy ngủ/tắt; lệnh gửi lúc đó (&gt;15 phút) sẽ bị bỏ qua."""

log = logging.getLogger("brief.bot")


class Bot:
    def __init__(self, secret: TelegramSecret, api: Optional[Api] = None):
        self.secret = secret
        self.api = api or Api(secret)
        self.settings = load_settings()["telegram"]
        self.offset: Optional[int] = db.kv_get("tg_offset")
        self.started_at = db.now_utc()
        self.busy: dict[str, bool] = {}
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.news_lock = threading.Lock()  # /brief và lịch không thu thập tin cùng lúc
        self.ignored_foreign = 0

    # ------------------------------------------------------------ helpers
    def reply(self, text: str, brief_id: Optional[int] = None) -> list[dict[str, Any]]:
        res = send_text(self.api, self.secret.chat_id, text, brief_id=brief_id)
        ok = all(r["ok"] for r in res)
        log.info("reply chunks=%d ok=%s msg_ids=%s", len(res), ok, [r.get("message_id") for r in res])
        if not ok:
            db.log_event("ERROR", "send", "; ".join(str(r.get("error")) for r in res if not r["ok"])[:300])
        return res

    def typing(self) -> None:
        try:
            self.api.call("sendChatAction", chat_id=self.secret.chat_id, action="typing", http_timeout=10)
        except TelegramError:
            pass

    def run_job(self, name: str, fn: Callable[[], None]) -> None:
        with self.lock:
            if self.busy.get(name):
                self.reply(f"⏳ /{name} đang chạy, chờ kết quả lượt trước.")
                return
            self.busy[name] = True

        def wrapper():
            try:
                self.typing()
                fn()
            except Exception as ex:
                msg = redact(f"{type(ex).__name__}: {ex}", self.secret)[:300]
                log.exception("job %s failed", name)
                db.log_event("ERROR", name, msg)
                self.reply(f"❌ /{name} lỗi: {msg}\nXem /status.")
            finally:
                with self.lock:
                    self.busy[name] = False

        threading.Thread(target=wrapper, name=f"job-{name}", daemon=True).start()

    # ------------------------------------------------------------ commands
    def handle(self, text: str, late_min: float) -> None:
        parts = text.strip().split()
        cmd = parts[0].split("@")[0].lower() if parts else ""
        args = [a.lower() for a in parts[1:]]
        note = f"\n\n<i>(lệnh gửi {late_min:.0f} phút trước, xử lý trễ)</i>" if late_min >= 1 else ""
        if cmd in ("/start", "/help"):
            self.reply(HELP)
        elif cmd == "/brief":
            full = "full" in args

            def job():
                with self.news_lock:
                    bid, html_text, mode = service.run_brief(full=full)
                self.reply(html_text + note, brief_id=bid)
            self.run_job("brief", job)
        elif cmd == "/stock":
            self.run_job("stock", lambda: self.reply(service.stock_text(force="refresh" in args) + note))
        elif cmd == "/gold":
            self.run_job("gold", lambda: self.reply(service.gold_text(force="refresh" in args) + note))
        elif cmd == "/status":
            self.run_job("status", lambda: self.reply(service.status_text(self.started_at)))
        elif cmd.startswith("/"):
            self.reply("Lệnh chưa hỗ trợ. Gõ /help.")
        # tin nhắn thường: bỏ qua

    def process(self, upd: dict[str, Any]) -> None:
        msg = upd.get("message") or upd.get("edited_message")
        if not msg:
            return
        chat_id = (msg.get("chat") or {}).get("id")
        if chat_id != self.secret.chat_id:
            self.ignored_foreign += 1
            log.warning("ignored update from unauthorized chat (count=%d)", self.ignored_foreign)
            return
        text = msg.get("text") or ""
        if not text.startswith("/"):
            return
        late_min = (time.time() - msg.get("date", time.time())) / 60
        if late_min > self.settings["ignore_older_min"]:
            log.info("skip stale command (%.0f min old)", late_min)
            db.log_event("INFO", "bot", f"bỏ qua lệnh cũ {late_min:.0f} phút")
            return
        log.info("command %s (late %.1f min)", text.split()[0][:20], late_min)
        self.handle(text, late_min)

    # ------------------------------------------------------------ loop
    def poll_once(self) -> int:
        params: dict[str, Any] = {"timeout": self.settings["poll_timeout_s"], "allowed_updates": ["message"]}
        if self.offset is not None:
            params["offset"] = self.offset
        updates = self.api.call("getUpdates", http_timeout=self.settings["poll_timeout_s"] + 15, **params)
        for upd in updates:
            self.offset = upd["update_id"] + 1
            db.kv_set("tg_offset", self.offset)
            try:
                self.process(upd)
            except Exception:
                log.exception("process update failed")
        return len(updates)

    def run(self) -> int:
        me = self.api.call("getMe")
        wh = self.api.call("getWebhookInfo")
        if wh.get("url"):
            log.error("Bot đang dùng webhook – không chạy getUpdates để tránh ngắt luồng hiện có.")
            db.log_event("ERROR", "bot", "webhook đang bật – từ chối polling")
            return 3
        log.info("bot @%s started; polling (webhook none, pending=%s)", me.get("username"), wh.get("pending_update_count"))
        db.kv_set("bot_runtime", {"username": me.get("username"), "started_at": db.iso(self.started_at)})
        db.log_event("INFO", "bot", f"khởi động @{me.get('username')}")
        sch = schedule.Scheduler(lambda text, bid: self.reply(text, brief_id=bid), self.news_lock,
                                 redact=lambda s: redact(s, self.secret))
        threading.Thread(target=schedule.run_forever, args=(sch, self.stop), name="schedule", daemon=True).start()
        backoff = 1
        while not self.stop.is_set():
            try:
                self.poll_once()
                backoff = 1
            except TelegramError as ex:
                if ex.code == 409:
                    log.error("409 Conflict: có tiến trình khác đang nhận updates – dừng để không tranh chấp.")
                    db.log_event("ERROR", "bot", "409 conflict – dừng polling")
                    return 4
                log.warning("getUpdates error: %s", redact(str(ex), self.secret))
                time.sleep(min(backoff, 60))
                backoff *= 2
        log.info("bot stopped")
        return 0


def setup_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    h = RotatingFileHandler(LOG_DIR / "bot.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(threadName)s %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(h)
    for noisy in ("urllib3", "yfinance", "peewee"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def main() -> int:
    rc = _main()
    if rc in (2, 3, 4) and os.environ.get("BRIEF_SUPERVISED"):
        log.error("Dừng hẳn (mã %d): lỗi cấu hình hoặc xung đột – launchd sẽ không tự chạy lại. "
                  "Sửa xong thì chạy scripts/botctl.sh start.", rc)
        return 0
    return rc


def _main() -> int:
    setup_logging()
    secret = telegram_secret()
    if not secret:
        from brief import config
        log.error("Không đọc được token/chat ID: %s", config.SECRET_ERROR or "không rõ")
        return 2
    bot = Bot(secret)

    def _stop(*_):
        bot.stop.set()
        raise SystemExit(0)  # ngắt ngay cả khi đang chờ long-poll

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    db.prune()
    try:
        return bot.run()
    finally:
        db.log_event("INFO", "bot", "dừng")
        log.info("bot exit")
