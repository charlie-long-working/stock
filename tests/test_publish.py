import json
import re
import tempfile
import unittest
from pathlib import Path

from brief import publish, reports, site

TEMPLATE = Path(site.__file__).with_name("site_template.html")


class ExtraPagesTest(unittest.TestCase):
    def test_reads_wraps_and_rejects_bad_paths(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            (base / "r.html").write_text("<title>R</title><p>x</p>", encoding="utf-8")
            (base / "full.html").write_text("<!DOCTYPE html><html><body>y</body></html>", encoding="utf-8")
            cfg = {"extra_pages": {"reports/r": "r.html", "/full/": "full.html", "../up": "r.html",
                                   ".github/x": "r.html", "missing": "nope.html"}}
            pages, errors = publish.extra_pages(cfg, base=base)
            self.assertEqual(sorted(pages), ["full", "reports/r"])
            self.assertTrue(pages["reports/r"].startswith(b"<!doctype html>"))
            self.assertIn(b'<meta charset="utf-8">', pages["reports/r"])
            # trang đã đủ doctype: giữ nguyên, chỉ chèn shim nhúng ngay trước </body>
            self.assertTrue(pages["full"].startswith(b"<!DOCTYPE html><html><body>y"))
            self.assertTrue(pages["full"].endswith(b"</body></html>"))
            self.assertEqual(pages["full"].count(reports.MARK), 1)
            self.assertEqual(sorted(errors), ["../up", ".github/x", "missing"])

    def test_no_config(self):
        self.assertEqual(publish.extra_pages({}), ({}, {}))


class ReportsTest(unittest.TestCase):
    def test_prepare_page_idempotent(self):
        once = reports.prepare_page(b"<p>a</p>")
        self.assertEqual(reports.prepare_page(once), once)
        self.assertEqual(once.count(reports.MARK), 1)
        self.assertLess(once.index(reports.MARK), once.rindex(b"</body>"))
        self.assertEqual(reports.prepare_page(b"<!doctype html><p>no body").count(reports.MARK), 1)

    def test_load_reports(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            (base / "a.html").write_text("<p>A</p>", encoding="utf-8")
            cfg = {"reports": [{"key": "ok-1", "title": "A", "date": "2026-11-16", "src": "a.html"},
                               {"key": "gone", "title": "B", "src": "b.html"},
                               {"key": "../x", "src": "a.html"}, {"key": "Bad Key", "src": "a.html"}]}
            pages, errors, meta = reports.load(cfg, base)
            self.assertEqual(sorted(pages), ["reports/ok-1"])
            self.assertEqual([m["key"] for m in meta], ["ok-1", "gone"])
            self.assertEqual(meta[0]["path"], "reports/ok-1/")
            self.assertNotIn("error", meta[0])
            self.assertRegex(meta[0]["v"], r"^[0-9a-f]{10}$")
            self.assertIn("error", meta[1])
            self.assertEqual(sorted(errors), ["../x", "Bad Key", "gone"])

    def test_rerender_copies_reports_and_lists_them(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            src = base / "rep.html"
            src.write_text("<p>R</p>", encoding="utf-8")
            out = base / "site"
            (out / "reports" / "stale").mkdir(parents=True)             # báo cáo đã gỡ khỏi config → bị xoá
            (out / "data.json").write_text(json.dumps({"generated_at": "x", "errors": {}}), encoding="utf-8")
            settings = {"site": {"reports": [{"key": "rep", "title": "R", "src": str(src)}]}}
            site.rerender(out, settings)
            self.assertTrue((out / "reports" / "rep" / "index.html").is_file())
            self.assertFalse((out / "reports" / "stale").exists())
            html = (out / "index.html").read_text(encoding="utf-8")
            self.assertIn('"key":"rep"', html)


class TemplateTest(unittest.TestCase):
    def test_every_tab_has_section_and_builder(self):
        html = TEMPLATE.read_text(encoding="utf-8")
        tabs = re.findall(r'<button role="tab"[^>]*data-t="([a-z]+)"', html)
        self.assertIn("research", tabs)
        self.assertEqual(len(tabs), len(set(tabs)))
        for t in tabs:
            self.assertIn(f'<section id="tab-{t}"', html, t)
            self.assertRegex(html, rf"BUILD\.{t} = ", t)


if __name__ == "__main__":
    unittest.main()
