"""vn_news + run_vn_news_digest: RSS parsing, symbol matching (aliases/exclusions), filters, formatting.
Offline: all fetchers are mocked."""

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from vn_stock.data_loaders import vn_news as N
from vn_stock.scripts import run_vn_news_digest as D

RSS = b"""<?xml version="1.0" encoding="utf-8"?><rss><channel>
<item><title>Vietcombank &amp;amp; BIDV gi\xe1\xba\xa3m l\xc3\xa3i su\xe1\xba\xa5t</title><link>https://x/1</link>
<pubDate>Sun, 15 Nov 2026 09:00:00 +0700</pubDate></item>
<item><title>Nh\xe1\xba\xadn \xc4\x91\xe1\xbb\x8bnh th\xe1\xbb\x8b tr\xc6\xb0\xe1\xbb\x9dng 16/11</title><link>https://x/2</link>
<pubDate>Sun, 15 Nov 2026 16:00:00</pubDate></item>
<item><title></title><link>https://x/3</link></item>
</channel></rss>"""


def _item(title, hours_ago=1, source="cafef"):
    return N.NewsItem(title, f"https://x/{abs(hash(title))}", datetime.now(timezone.utc) - timedelta(hours=hours_ago), source)


class ParseRssTests(unittest.TestCase):
    def test_parse_unescape_and_timezone(self):
        items = N.parse_rss(RSS, "cafef")
        self.assertEqual(len(items), 2)  # empty title dropped
        self.assertEqual(items[0].title, "Vietcombank & BIDV giảm lãi suất")
        self.assertEqual(items[1].published.utcoffset(), timedelta(hours=7))  # naive → VN
        self.assertEqual(items[0].source_name, "CafeF")

    def test_bad_xml_returns_empty(self):
        self.assertEqual(N.parse_rss(b"<html>blocked</html", "cafef"), [])


class MatchTests(unittest.TestCase):
    CASES = [
        ("FPT lãi kỷ lục", "FPT", True),
        ("Tập đoàn FPT ký hợp đồng", "FPT", True),
        ("PNJ bị FPT Retail vượt mặt", "FPT", False),
        ("Vietcombank giảm lãi suất", "VCB", True),
        ("VCBS khuyến nghị mua", "VCB", False),
        ("Lợi nhuận Hòa Phát tăng", "HPG", True),
        ("Masan Consumer chia cổ tức", "MSN", False),
        ("Masan lãi lớn", "MSN", True),
        ("HPG2501 chứng quyền", "HPG", False),
    ]

    def test_cases(self):
        for title, sym, expected in self.CASES:
            with self.subTest(title=title):
                self.assertEqual(N._mentions_symbol(title, sym), expected)

    def test_noise_filter(self):
        self.assertTrue(N._is_noise("CW.HPG/MBS/9M/26-01 HOSE: CHPG2629"))
        self.assertTrue(N._is_noise("Chứng quyền MWG/MBS/9M"))
        self.assertTrue(N._is_noise("HPG: Hoa Phat Group Joint Stock Company - Hoa Phat Group"))
        self.assertFalse(N._is_noise("HPG: Lợi nhuận quý 3 tăng 20%"))

    def test_market_view(self):
        self.assertTrue(N.is_market_view("Cổ phiếu cần quan tâm ngày 16/11"))
        self.assertTrue(N.is_market_view("Góc nhìn kỹ thuật phiên 16/11"))
        self.assertFalse(N.is_market_view("Giá vàng hôm nay"))


class FetchSymbolNewsTests(unittest.TestCase):
    def test_merges_filters_and_limits(self):
        press = [_item("Vietcombank lãi kỷ lục", 2), _item("VCBS ra mắt quỹ", 1), _item("Vietcombank tăng vốn", 200),
                 _item("CW.VCB/SSI chứng quyền mới", 1)]
        kbs = [N.NewsItem("VCB: BCTC quý 3", "https://v/1", datetime.now(timezone.utc) - timedelta(hours=5), "kbs", "VCB")]
        gn = [_item("Vietcombank lãi kỷ lục", 3, "gnews")]  # duplicate title of a press item
        with mock.patch.object(N, "fetch_kbs_news", return_value=kbs), \
             mock.patch.object(N, "fetch_gnews", return_value=gn), \
             mock.patch.object(N, "fetch_press", return_value=press):
            out = N.fetch_symbol_news("VCB", days=3, limit=5)
        titles = [i.title for i in out]
        self.assertEqual(titles, ["Vietcombank lãi kỷ lục", "VCB: BCTC quý 3"])  # newest first, deduped, old/noise dropped

    def test_press_feed_failure_is_isolated(self):
        N._FEED_CACHE.clear()
        with mock.patch.object(N.requests, "get", side_effect=OSError("down")):
            self.assertEqual(N.fetch_press(), [])
        N._FEED_CACHE.clear()


class DigestTests(unittest.TestCase):
    def test_latest_period_from_data(self):
        p = Path(tempfile.mkdtemp()) / "ratios.csv"
        p.write_text("ticker,yearReport,lengthReport\nVCB,2025,3\nVCB,2025,4\nVCB,2024,4\n")
        self.assertEqual(D._latest_period(p), "Q4/2025")
        p.write_text("garbage")
        self.assertEqual(D._latest_period(p), "cache")

    def test_messages_escape_and_split(self):
        items = [_item(f"Tin <{i}> & chi tiết " + "x" * 300) for i in range(30)]
        msgs = D.build_messages({"VCB": items}, [], {"VCB": None})
        self.assertGreater(len(msgs), 1)
        self.assertTrue(all(len(m) <= 4096 for m in msgs))
        self.assertIn("&lt;0&gt; &amp;", msgs[0])
        self.assertIn("[CafeF]", msgs[0])

    def test_empty_digest(self):
        self.assertEqual(D.build_messages({"VCB": []}, [], {}), [])


if __name__ == "__main__":
    unittest.main()
