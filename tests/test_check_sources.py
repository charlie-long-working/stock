"""Test parser bằng dữ liệu GIẢ (không gọi mạng). Chạy: python3 -m unittest discover -s tests"""

import unittest
from datetime import datetime, timezone

from brief.check_sources import (
    Check,
    looks_like_html,
    parse_feed,
    parse_sjc,
    parse_vcb,
    strip_html,
)
from brief.http import FetchResult

RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Mau</title>
<item><title>Tin A</title><link>https://example.test/a</link>
<description><![CDATA[<a href="x"><img src="y"/></a></br>Tom tat gia lap cho tin A, du dai.]]></description>
<pubDate>Sat, 14 Nov 2026 07:30:00 +0700</pubDate></item>
<item><title>Tin B</title><link>https://example.test/b</link>
<description></description><pubDate>Fri, 13 Nov 2026 22:00:00 GMT</pubDate></item>
</channel></rss>"""

ATOM = b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>Mau</title>
<entry><title>X</title><summary>Mot doan tom tat gia lap du hai muoi ky tu.</summary>
<updated>2026-11-14T01:00:00Z</updated></entry></feed>"""

VCB = b"""<?xml version="1.0" encoding="utf-8"?><ExrateList>
<DateTime>11/14/2026 8:00:00 AM</DateTime>
<Exrate CurrencyCode="EUR" Buy="1" Transfer="2" Sell="3"/>
<Exrate CurrencyCode="USD" Buy="25,000.00" Transfer="25,030.00" Sell="25,400.00"/>
<Source>Joint Stock Commercial Bank for Foreign Trade of Vietnam - Vietcombank</Source>
</ExrateList>"""

SJC = """<?xml version="1.0" encoding="utf-8"?><root>
<ratelist updated="08:30:00 AM 14/11/2026" unit="nghìn đồng/lượng">
<city name="Hồ Chí Minh">
<item buy="100,000" sell="102,000" type="Vàng SJC 1L - 10L"/>
<item buy="99,000" sell="101,000" type="Vàng nhẫn SJC 99,99 1 chỉ"/>
</city></ratelist></root>""".encode("utf-8")


class ParserTests(unittest.TestCase):
    def test_strip_html(self):
        self.assertEqual(strip_html("<p>A &amp; <b>B</b></p>"), "A & B")
        self.assertEqual(strip_html(None), "")

    def test_rss(self):
        st = parse_feed(RSS)
        self.assertEqual(st["n_items"], 2)
        self.assertEqual(st["n_summary"], 1)
        self.assertFalse(st["full_text"])
        self.assertEqual(st["newest"], datetime(2026, 11, 14, 0, 30, tzinfo=timezone.utc))
        self.assertFalse(st["naive_dates"])

    def test_atom(self):
        st = parse_feed(ATOM)
        self.assertEqual(st["n_items"], 1)
        self.assertEqual(st["n_summary"], 1)

    def test_vcb(self):
        st = parse_vcb(VCB)
        self.assertEqual(st["n_items"], 2)
        self.assertEqual(st["usd"]["Sell"], "25,400.00")
        self.assertIn("8:00", st["datetime"])

    def test_sjc_detects_ring(self):
        st = parse_sjc(SJC)
        self.assertEqual(st["n_items"], 2)
        self.assertTrue(any("nhẫn" in t for t in st["types"]))
        self.assertEqual(st["unit"], "nghìn đồng/lượng")

    def test_html_detection(self):
        r = FetchResult(url="u", status=200, content_type="text/html; charset=utf-8", body=b"<html>")
        self.assertTrue(looks_like_html(r))
        r2 = FetchResult(url="u", status=200, content_type="application/xml", body=b"<?xml ?><rss/>")
        self.assertFalse(looks_like_html(r2))

    def test_us_style_naive_date(self):
        from brief.check_sources import TZ, parse_date
        dt = parse_date("11/14/2026 3:57:00 PM")
        self.assertEqual(dt, datetime(2026, 11, 14, 15, 57, tzinfo=TZ))

    def test_age(self):
        c = Check(id="x", name="x", kind="press", tier="core", url="u",
                  newest=datetime(2026, 11, 14, 0, 0, tzinfo=timezone.utc))
        self.assertEqual(c.age_hours(datetime(2026, 11, 14, 6, 0, tzinfo=timezone.utc)), 6.0)


if __name__ == "__main__":
    unittest.main()
