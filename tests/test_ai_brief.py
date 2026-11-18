"""Tóm tắt AI: trích đoạn mở đầu bài, cache, salvage, gọi CLI gọn (CLI giả, không mạng, không token thật)."""

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from brief import ai, article, db

VNE = """<html><head><meta property="og:description" content="OG mô tả"></head><body>
<p class="description">Sapo VnExpress: lãi suất giảm 0,5 điểm phần trăm từ hôm nay.</p>
<article class="fck_detail ">
<p class="Normal">Đoạn một nói về quyết định của ngân hàng trung ương với nhiều chi tiết hơn nữa.</p>
<p class="Image">Ảnh: chú thích không lấy</p>
<p class="Normal">Đoạn hai giải thích tác động đến doanh nghiệp và người vay trong năm tới.</p>
<p class="Normal" style="text-align:right;"><strong>Tác giả</strong></p>
</article></body></html>"""

CAFEF = """<html><body><h2 class="sapo" data-role="sapo">Sapo CafeF: chỉ đạo mới về ba dự án luật.</h2>
<div class="detail-content afcbc-body" data-role="content">
<p>Chiều 15/11, Phó Thủ tướng chủ trì cuộc họp về tiếp thu, giải trình ý kiến đại biểu Quốc hội.</p>
</div></body></html>"""


class ArticleTests(unittest.TestCase):
    def test_extract_vnexpress_and_cafef(self):
        t = article.extract(VNE, 900)
        self.assertTrue(t.startswith("Sapo VnExpress"))
        self.assertIn("Đoạn hai", t)
        self.assertNotIn("chú thích", t)
        self.assertNotIn("Tác giả", t)              # đoạn < 40 ký tự bị bỏ
        c = article.extract(CAFEF, 900)
        self.assertIn("Sapo CafeF", c)
        self.assertIn("Phó Thủ tướng", c)
        self.assertLessEqual(len(article.extract(VNE, 80)), 81)
        self.assertEqual(article.extract("<html><p>x</p></html>"), "")

    def test_leads_cache_and_host_filter(self):
        calls = []

        def getter(url, n):
            calls.append(url)
            return ("ok", 200, "nội dung " + url[-1]) if "vnexpress" in url else ("blocked", 403, "")

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "t.db"
            items = [("c1", "https://vnexpress.net/a-1"), ("c2", "https://cafef.vn/b-2"), ("c3", "https://other.vn/c-3")]
            out = article.leads(items, path=p, getter=getter)
            self.assertEqual(out, {"c1": "nội dung 1"})
            self.assertEqual(len(calls), 2)            # other.vn không nằm trong danh sách host
            out2 = article.leads(items, path=p, getter=getter)
            self.assertEqual(out2, out)
            self.assertEqual(len(calls), 2)            # lần 2 đọc cache, kể cả URL bị chặn

    def test_host_ok(self):
        self.assertTrue(article.host_ok("https://www.cafef.vn/x", ["cafef.vn"]))
        self.assertFalse(article.host_ok("https://notcafef.vn/x", ["cafef.vn"]))


class SalvageAndCliTests(unittest.TestCase):
    def setUp(self):
        self.ev = {"text": "[N1] lãi suất 0,5 điểm\n[N2] 15/11 họp\n[N3] x\n[M1] VN-Index 1.734,93",
                   "refs": {"N1": {"url": "u1"}, "N2": {"url": "u2"}, "N3": {"url": "u3"}, "M1": {"label": "m"}}}
        self.ev["digits"] = {ai.digits(t) for t in ai.NUM_RE.findall(self.ev["text"])}

    def test_salvage_drops_only_bad_lines(self):
        txt = ("<b>Kinh tế VN</b>\n• Lãi suất giảm 0,5 điểm [N1]\n• Họp 15/11 [N2]\n• Tin x [N3]\n"
               "• VN-Index 1.734,93 [M1]\n• Bịa 9.999 tỷ [N1]")
        fixed, dropped = ai.salvage(txt, self.ev)
        self.assertIsNotNone(fixed)
        self.assertNotIn("9.999", fixed)
        self.assertEqual(len(dropped), 1)
        self.assertEqual(ai.validate(fixed, self.ev), [])

    def test_salvage_gives_up_when_too_many_bad(self):
        fixed, _ = ai.salvage("• a 111 [N1]\n• b 222 [N2]\n• c [N3]", self.ev)
        self.assertIsNone(fixed)

    def test_cli_args_lean(self):
        a = ai.cli_args({"model": "sonnet", "effort": "low"}, "/x/claude", "SYS", api_key=False)
        self.assertEqual(a[a.index("--tools") + 1], "")
        self.assertEqual(a[a.index("--system-prompt") + 1], "SYS")
        self.assertIn("--no-session-persistence", a)
        self.assertNotIn("--bare", a)
        self.assertIn("--bare", ai.cli_args({}, "/x/claude", "SYS", api_key=True))

    def test_find_cli_prefers_path(self):
        with tempfile.TemporaryDirectory() as d:
            exe = Path(d) / "claude"
            exe.write_text("#!/bin/sh\n")
            exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
            with mock.patch.dict(os.environ, {"PATH": d}):
                self.assertEqual(ai.find_cli("claude"), str(exe))

    def test_run_cli_with_fake_cli(self):
        with tempfile.TemporaryDirectory() as d:
            exe = Path(d) / "claude"
            exe.write_text("#!/bin/sh\ncat > /dev/null\n"
                           "echo '{\"result\": \"• Lãi suất giảm 0,5 điểm [N1]\", \"is_error\": false, "
                           "\"usage\": {\"input_tokens\": 1200, \"output_tokens\": 300}, \"total_cost_usd\": 0.01}'\n")
            exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
            with mock.patch.object(ai, "find_cli", return_value=str(exe)), \
                    mock.patch.object(ai, "auth_env", return_value=(dict(os.environ), "env:CLAUDE_CODE_OAUTH_TOKEN")):
                out, err = ai.run_cli(self.ev, Path(d))
            self.assertEqual(err, "")
            self.assertEqual(out, "• Lãi suất giảm 0,5 điểm [N1]")
            u = json.loads((Path(d) / "ai_usage.json").read_text())
            self.assertEqual(u["input_tokens"], 1200)
            self.assertEqual(db.kv_get("ai_last_usage")["output_tokens"], 300)

    def test_run_cli_not_logged_in(self):
        with tempfile.TemporaryDirectory() as d:
            exe = Path(d) / "claude"
            exe.write_text("#!/bin/sh\ncat > /dev/null\necho '{\"result\": \"Not logged in\", \"is_error\": true}'\nexit 1\n")
            exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
            with mock.patch.object(ai, "find_cli", return_value=str(exe)):
                out, err = ai.run_cli(self.ev)
            self.assertIsNone(out)
            self.assertIn("Not logged in", err)

    def test_evidence_uses_leads(self):
        from datetime import datetime, timezone
        from brief.news import Cluster
        c = Cluster(title="T", summary="RSS tóm tắt", url="https://vnexpress.net/a", canonical_urls=["c1"],
                    sources=["vnexpress_kinhdoanh"], kinds=["press"], published=datetime.now(timezone.utc),
                    section="vn_economy")
        now = datetime.now(timezone.utc)
        ev = ai.build_evidence([c], None, None, now, now, None, {"c1": "Đoạn mở đầu 2026"})
        self.assertIn("Nội dung: Đoạn mở đầu 2026", ev["text"])
        self.assertNotIn("RSS tóm tắt", ev["text"])
        self.assertIn("2026", ev["digits"])


class SiteAiBriefTests(unittest.TestCase):
    def test_only_bot_generated_ai_brief(self):
        from brief import compose, site_data
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "t.db"
            compose.save_brief("news", "ai", "thử tay", None, None, [], {"run_dir": "runs/x/manual-1"}, p)
            self.assertIsNone(site_data.latest_ai_brief(p))
            compose.save_brief("news", "ai", "<b>bot</b>", None, None, [],
                               {"run_dir": "runs/x/bot-1", "usage": {"model": "sonnet"}}, p, n_items=5)
            b = site_data.latest_ai_brief(p)
            self.assertEqual((b["html"], b["model"], b["n_items"]), ("<b>bot</b>", "sonnet", 5))


if __name__ == "__main__":
    unittest.main()
