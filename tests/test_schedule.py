"""Test lịch tự gửi bằng giờ giả, dữ liệu giả và hàm gửi giả (không gọi mạng, không gửi tin thật)."""

import threading
import unittest
from datetime import datetime, timedelta
from unittest import mock

from brief import db, schedule, service
from brief.config import TZ

SETTINGS = {"schedule": {
    "enabled": True, "late_after_min": 20, "retry_min": 10, "max_attempts": 3,
    "slots": [
        {"name": "morning", "label": "sáng", "at": "08:15", "skip_after": "15:00", "parts": ["news", "gold"]},
        {"name": "afternoon", "label": "chiều", "at": "16:30", "skip_after": "23:00", "parts": ["news", "stock", "gold"]},
    ]}}
DAY = 0


def at(hh, mm, day_offset=0):
    # mỗi test dùng một ngày riêng để trạng thái kv không lẫn nhau
    return datetime(2030, 1, 7, hh, mm, tzinfo=TZ) + timedelta(days=DAY + day_offset)


class FakeSender:
    def __init__(self, fail_texts=()):
        self.sent, self.fail_texts = [], list(fail_texts)

    def __call__(self, text, bid):
        for f in self.fail_texts:
            if f in text:
                self.fail_texts.remove(f)
                return [{"chunk": 0, "ok": False, "error": "TimeoutError"}]
        self.sent.append((text, bid))
        return [{"chunk": 0, "ok": True, "message_id": len(self.sent)}]


class ScheduleTests(unittest.TestCase):
    def setUp(self):
        global DAY
        DAY += 3
        self.calls = {"brief": 0}

        def fake_brief(full=False, path=None):
            self.calls["brief"] += 1
            return 900 + self.calls["brief"], "📰 <b>BẢN TIN</b> giả", "template"

        self.session = "closed_today"
        patches = [
            mock.patch.object(service, "run_brief", side_effect=fake_brief),
            mock.patch.object(service, "gold_text", return_value="🥇 VÀNG giả"),
            mock.patch("brief.market.vn_market", side_effect=lambda **k: {"session": self.session, "indices": []}),
            mock.patch("brief.compose.stock_text", return_value="📈 CHỨNG KHOÁN giả"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.send = FakeSender()
        self.sch = schedule.Scheduler(self.send, threading.Lock(), settings=SETTINGS)

    def texts(self):
        return [t for t, _ in self.send.sent]

    def test_before_due_does_nothing(self):
        self.assertEqual(self.sch.tick(at(8, 14)), [])
        self.assertEqual(self.send.sent, [])

    def test_on_time_sends_once(self):
        self.assertEqual(self.sch.tick(at(8, 15)), [("morning", "run")])
        t = self.texts()
        self.assertEqual(len(t), 2)
        self.assertIn("Bản tin sáng", t[0])
        self.assertNotIn("gửi bù", t[0])
        self.assertIn("VÀNG", t[1])
        self.assertEqual(self.sch.tick(at(8, 16)), [])          # lần kiểm tra sau: không gửi lại
        self.assertEqual(len(self.send.sent), 2)
        st = db.kv_get(schedule.state_key(at(8, 15).date(), schedule.load_config(SETTINGS)[1][0]))
        self.assertEqual(st["status"], "sent")

    def test_catch_up_after_wake_is_labelled(self):
        self.assertEqual(self.sch.tick(at(10, 2)), [("morning", "run")])   # máy thức lúc 10:02
        self.assertIn("gửi bù lúc 10:02", self.texts()[0])

    def test_too_late_is_skipped(self):
        acts = self.sch.tick(at(15, 30))     # bản sáng quá 15:00 -> bỏ; bản chiều chưa đến giờ
        self.assertEqual(acts, [("morning", "skip")])
        self.assertEqual(self.send.sent, [])
        lines = "\n".join(schedule.status_lines(at(15, 30), settings=SETTINGS))
        self.assertIn("không gửi", lines)
        self.assertIn("chờ đến giờ", lines)

    def test_afternoon_skips_stock_without_session(self):
        self.session = "weekend"
        self.sch.tick(at(15, 0))             # bản sáng bị bỏ trước
        self.sch.tick(at(16, 30))
        t = self.texts()
        self.assertEqual(len(t), 2)          # tin + vàng, không có chứng khoán
        self.assertFalse(any("CHỨNG KHOÁN" in x for x in t))

    def test_afternoon_with_session_has_three_parts(self):
        self.sch.tick(at(15, 0))
        self.sch.tick(at(16, 31))
        self.assertEqual([x.split()[0] for x in self.texts()], ["⏰", "📈", "🥇"])

    def test_partial_failure_retries_only_missing_part(self):
        self.send.fail_texts = ["VÀNG"]
        self.sch.tick(at(8, 15))
        self.assertEqual(len(self.send.sent), 1)                 # tin đã gửi, vàng lỗi
        self.assertEqual(self.sch.tick(at(8, 20)), [])           # chưa đủ 10 phút -> chờ
        self.assertEqual(self.sch.tick(at(8, 26)), [("morning", "run")])
        self.assertEqual(self.calls["brief"], 1)                 # không tạo bản tin mới
        self.assertEqual(len(self.send.sent), 2)
        self.assertIn("VÀNG", self.texts()[1])

    def test_news_resend_uses_same_brief(self):
        self.send.fail_texts = ["Bản tin sáng"]
        self.sch.tick(at(8, 15))
        self.sch.tick(at(8, 30))
        self.assertEqual(self.calls["brief"], 1)
        news_sends = [b for t, b in self.send.sent if "Bản tin sáng" in t]
        self.assertEqual(news_sends, [901])                       # cùng brief_id -> deliveries chống trùng

    def test_gives_up_after_max_attempts(self):
        self.send.fail_texts = ["VÀNG"] * 5
        for m in (15, 30, 45, 59):
            self.sch.tick(at(8, m))
        st = db.kv_get(schedule.state_key(at(8, 15).date(), schedule.load_config(SETTINGS)[1][0]))
        self.assertEqual(st["status"], "gave_up")
        self.assertEqual(st["attempts"], 3)

    def test_disabled(self):
        sch = schedule.Scheduler(self.send, threading.Lock(), settings={"schedule": {"enabled": False}})
        self.assertEqual(sch.tick(at(8, 15)), [])


if __name__ == "__main__":
    unittest.main()
