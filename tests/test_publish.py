import tempfile
import unittest
from pathlib import Path

from brief import publish


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
            self.assertEqual(pages["full"], b"<!DOCTYPE html><html><body>y</body></html>")
            self.assertEqual(sorted(errors), ["../up", ".github/x", "missing"])

    def test_no_config(self):
        self.assertEqual(publish.extra_pages({}), ({}, {}))


if __name__ == "__main__":
    unittest.main()
