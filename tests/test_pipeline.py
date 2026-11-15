"""Test luồng chính bằng dữ liệu GIẢ và API Telegram GIẢ (không gọi mạng, không gửi tin thật).

Chạy: ../stock/.venv/bin/python -m unittest discover -s tests -t .
"""

import time
import unittest
from datetime import datetime, timedelta, timezone

from brief import ai, db, news
from brief.config import DB_PATH, TelegramSecret
from brief.telegram_api import TelegramError, send_text, split_message

RSS = """<?xml version="1.0"?><rss><channel>
<item><title>Thủ tướng Lê Minh Hưng đến Philippines dự Hội nghị cấp cao ASEAN lần thứ 49</title>
<link>https://a.test/1?utm_source=x</link><description>Tóm tắt giả lập A dài hơn hai mươi ký tự.</description>
<pubDate>{d1}</pubDate></item>
<item><title>Giá vàng miếng SJC giảm 500.000 đồng</title><link>https://a.test/2</link>
<description>Giá vàng miếng SJC giả lập, dài hơn hai mươi ký tự.</description><pubDate>{d1}</pubDate></item>
</channel></rss>"""
RSS2 = """<?xml version="1.0"?><rss><channel>
<item><title>Thủ tướng tới Philippines, bắt đầu chuyến công tác tham dự Hội nghị cấp cao ASEAN</title>
<link>https://b.test/9</link><description>Tóm tắt giả lập B dài hơn hai mươi ký tự.</description>
<pubDate>{d1}</pubDate></item>
<item><title>Thủ tướng Lê Minh Hưng đến Philippines dự Hội nghị cấp cao ASEAN lần thứ 49</title>
<link>https://a.test/1</link><description>Trùng URL với nguồn A.</description><pubDate>{d1}</pubDate></item>
</channel></rss>"""

SOURCES = [
    {"id": "vnexpress_thoisu", "name": "VnExpress – Thời sự", "kind": "press", "tier": "core", "format": "rss", "url": "u1"},
    {"id": "baochinhphu", "name": "Báo Điện tử Chính phủ", "kind": "official", "tier": "core", "format": "rss", "url": "u2"},
    {"id": "broken", "name": "Hỏng", "kind": "press", "tier": "core", "format": "rss", "url": "u3"},
]


def fake_fetcher(src):
    d1 = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%a, %d %b %Y %H:%M:%S +0000")
    if src["id"] == "broken":
        return {"src": src, "http": None, "elapsed": 0, "items": [], "error": "TimeoutError", "status": "error"}
    body = (RSS if src["id"] == "vnexpress_thoisu" else RSS2).format(d1=d1).encode()
    return {"src": src, "http": 200, "elapsed": 0, "items": news.parse_items(body), "error": None, "status": "ok"}


class FakeApi:
    """Mô phỏng Bot API: có thể ép lỗi ở lần gọi thứ n."""

    def __init__(self, fail_on=None, parse_error_on=None):
        self.sent, self.calls = [], 0
        self.fail_on, self.parse_error_on = set(fail_on or []), set(parse_error_on or [])
        self.secret = TelegramSecret("123:fake", 42, "test")

    def call(self, method, http_timeout=20, **params):
        self.calls += 1
        if self.calls in self.fail_on:
            raise TelegramError(403, "Forbidden: test")
        if self.calls in self.parse_error_on and params.get("parse_mode"):
            raise TelegramError(400, "Bad Request: can't parse entities")
        if method == "sendMessage":
            self.sent.append(params)
            return {"message_id": 1000 + len(self.sent)}
        return {}


class NewsTests(unittest.TestCase):
    def test_collect_dedup_and_failure_isolation(self):
        summary = news.collect(SOURCES, fetcher=fake_fetcher)
        self.assertEqual(summary["broken"]["status"], "error")       # 1 nguồn lỗi
        self.assertEqual(summary["vnexpress_thoisu"]["new"], 2)       # vẫn lưu nguồn khác
        again = news.collect(SOURCES, fetcher=fake_fetcher)           # chạy lại không nhân đôi
        self.assertEqual(again["vnexpress_thoisu"]["new"], 0)
        end = db.now_utc()
        cl = news.select(end - timedelta(hours=24), end, set(), [], {"vn_politics": 3, "gold": 1}, 12)
        asean = [c for c in cl if "philippines" in c.title.lower()]
        self.assertEqual(len(asean), 1)                               # 2 tiêu đề khác nhau + 1 URL trùng -> 1 cụm
        self.assertEqual(sorted(asean[0].publishers), ["baochinhphu", "vnexpress"])
        self.assertEqual(len(asean[0].canonical_urls), 2)             # utm bị bỏ -> URL trùng gộp
        self.assertTrue(any(c.section == "gold" for c in cl))
        # loại tin đã gửi
        cl2 = news.select(end - timedelta(hours=24), end, set(asean[0].canonical_urls), [], {"vn_politics": 3, "gold": 1}, 12)
        self.assertFalse(any("philippines" in c.title.lower() for c in cl2))

    def test_watchlist_hits(self):
        self.assertEqual(news.watchlist_hits("TP.HCM và USD/VND", ["HCM", "VND"]), set())
        self.assertEqual(news.watchlist_hits("HCM báo lãi, VND giảm", ["HCM", "VND"]), {"HCM", "VND"})

    def test_canonical_url(self):
        self.assertEqual(news.canonical_url("HTTPS://A.test/x/?utm_source=a&id=1#f"), "https://a.test/x?id=1")


class TelegramTests(unittest.TestCase):
    def _brief(self, text):
        with db.connect() as con:
            return con.execute("INSERT INTO briefs(created_at, kind, mode, text_html) VALUES(?,?,?,?)",
                               (db.iso(db.now_utc()), "news", "template", text)).lastrowid

    def test_split_long_message(self):
        text = "\n\n".join(f"<b>Mục {i}</b>\n" + "x" * 500 for i in range(30))
        chunks = split_message(text)
        self.assertGreater(len(chunks), 3)
        self.assertTrue(all(len(c) <= 3900 for c in chunks))
        self.assertEqual("\n\n".join(chunks), text)                    # không mất nội dung
        self.assertTrue(all(c.count("<b>") == c.count("</b>") for c in chunks))

    def test_partial_failure_then_resume_without_duplicates(self):
        text = "\n\n".join("y" * 1500 for _ in range(6))               # ~3 phần
        bid = self._brief(text)
        api = FakeApi(fail_on=[2])                                     # phần 2 lỗi
        r1 = send_text(api, 42, text, brief_id=bid)
        self.assertEqual([x["ok"] for x in r1], [True, False])
        with db.connect() as con:
            self.assertEqual(con.execute("SELECT status FROM briefs WHERE id=?", (bid,)).fetchone()[0], "partial")
        api2 = FakeApi()
        r2 = send_text(api2, 42, text, brief_id=bid)                   # chạy lại: chỉ gửi phần thiếu
        self.assertTrue(r2[0]["skipped"])
        self.assertEqual(len(api2.sent), len(split_message(text)) - 1)
        with db.connect() as con:
            self.assertEqual(con.execute("SELECT status FROM briefs WHERE id=?", (bid,)).fetchone()[0], "sent")
        api3 = FakeApi()
        send_text(api3, 42, text, brief_id=bid)                        # lần 3: không gửi gì
        self.assertEqual(api3.sent, [])

    def test_html_parse_error_falls_back_to_plain(self):
        api = FakeApi(parse_error_on=[1])
        r = send_text(api, 42, "<b>bad <i>html</b>")
        self.assertTrue(r[0]["ok"] and r[0]["plain"])
        self.assertNotIn("parse_mode", api.sent[0])


class AiValidateTests(unittest.TestCase):
    def setUp(self):
        self.ev = {"text": "[N1] ... 137,5 triệu ... 14/11 09:35\n[M1] VN-Index 1.734,93 điểm, +0,01%",
                   "refs": {"N1": {"url": "https://a.test/1", "label": "VnExpress"}, "M1": {"label": "vnstock"}}}
        self.ev["digits"] = {ai.digits(t) for t in ai.NUM_RE.findall(self.ev["text"])}

    def test_good(self):
        good = "<b>Chứng khoán</b>\n• VN-Index 1.734,93 điểm (+0,01%) [M1]\n• Vàng miếng còn 137,5 triệu [N1]"
        self.assertEqual(ai.validate(good, self.ev), [])
        out = ai.render(good, self.ev, "test")
        self.assertIn('<a href="https://a.test/1">[1]</a>', out)

    def test_rejects_invented_number_missing_ref_and_unknown_id(self):
        bad = "• VN-Index 1.800,00 điểm [M1]\n• Tin không nguồn\n• Bịa [N9]"
        errs = " | ".join(ai.validate(bad, self.ev))
        self.assertIn("1.800,00", errs)
        self.assertIn("thiếu nguồn", errs)
        self.assertIn("[N9]", errs)

    def test_sanitize_blocks_links_and_script(self):
        s = ai.sanitize('<b>ok</b> <a href="x">l</a><script>')
        self.assertIn("<b>ok</b>", s)
        self.assertNotIn("<a ", s)
        self.assertNotIn("<script>", s)


class BotTests(unittest.TestCase):
    def setUp(self):
        from brief import bot as botmod
        self.botmod = botmod
        self.api = FakeApi()
        self.bot = botmod.Bot(self.api.secret, api=self.api)

    def _upd(self, chat_id, text, age_s=0):
        return {"update_id": 1, "message": {"chat": {"id": chat_id}, "text": text, "date": int(time.time() - age_s)}}

    def test_foreign_chat_ignored(self):
        self.bot.process(self._upd(999, "/help"))
        self.assertEqual(self.api.sent, [])
        self.assertEqual(self.bot.ignored_foreign, 1)

    def test_help_and_unknown(self):
        self.bot.process(self._upd(42, "/help"))
        self.bot.process(self._upd(42, "/foo@bedboiz_bot"))
        self.bot.process(self._upd(42, "xin chào"))                  # tin thường: bỏ qua
        self.assertEqual(len(self.api.sent), 2)
        self.assertIn("/brief", self.api.sent[0]["text"])
        self.assertIn("chưa hỗ trợ", self.api.sent[1]["text"])

    def test_stale_command_skipped(self):
        self.bot.process(self._upd(42, "/help", age_s=3600))
        self.assertEqual(self.api.sent, [])


if __name__ == "__main__":
    unittest.main()
