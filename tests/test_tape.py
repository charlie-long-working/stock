"""vn_stock.tape: tổng hợp mua/bán chủ động, phân trang, kiểm tra phiên, upsert, chỉ số và tin top 10.
Offline: tick giả, page_fn giả, api_call không chờ."""

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

import pandas as pd

from vn_stock.tape import collect as C
from vn_stock.tape import metrics as M


def ticks(day="2026-11-13", rows=None):
    rows = rows or [("09:15:00", 50.0, 1000, "ato"), ("09:30:00", 50.1, 2000, "buy"), ("10:00:00", 50.0, 500, "sell"),
                    ("10:00:00", 50.0, 500, "sell"), ("11:00:00", 50.2, 30000, "buy"), ("14:45:00", 50.1, 4000, "atc")]
    return pd.DataFrame([{"time": f"{day} {t}", "price": p, "volume": v, "match_type": m,
                          "id": f"{day}_{t}_{p}_{v}"} for t, p, v, m in rows])


def no_wait():
    return mock.patch.object(C, "api_call", side_effect=lambda fn, label="": fn())


class AggregateTests(unittest.TestCase):
    def test_sums_and_ratio(self):
        r = C.aggregate(ticks(), "vcb", ref_volume=38000, large_thr_bn=1.0)
        self.assertEqual((r["buy_vol"], r["sell_vol"], r["ato_vol"], r["atc_vol"]), (32000, 1000, 1000, 4000))
        self.assertEqual(r["total_vol"], 38000)
        self.assertAlmostEqual(r["nar"], round((32000 - 1000) / 33000, 4))
        self.assertTrue(r["reconciled"])
        self.assertTrue(r["complete"])
        self.assertEqual(r["symbol"], "VCB")

    def test_duplicate_ids_are_real_trades(self):
        # two identical sells share an id on KBS — both must count
        self.assertEqual(C.aggregate(ticks(), "X")["sell_vol"], 1000)

    def test_large_lot_threshold(self):
        r = C.aggregate(ticks(), "X", large_thr_bn=1.0)  # 30000 × 50.2k = 1.506 tỷ
        self.assertEqual(r["large_buy_vol"], 30000)
        self.assertAlmostEqual(r["large_buy_value_bn"], 1.506, places=3)
        self.assertEqual(r["large_sell_vol"], 0)

    def test_incomplete_session_and_mismatch(self):
        r = C.aggregate(ticks(rows=[("10:00:00", 10.0, 100, "buy")]), "X", ref_volume=1000)
        self.assertFalse(r["complete"])
        self.assertFalse(r["reconciled"])

    def test_threshold_clip(self):
        self.assertEqual(C.large_threshold_bn(50), 0.3)
        self.assertEqual(C.large_threshold_bn(5000), 3.0)
        self.assertEqual(C.large_threshold_bn(None), 1.0)


class ApiCallTests(unittest.TestCase):
    def test_rate_limit_exit_is_retried(self):
        fn = mock.Mock(side_effect=[SystemExit(1), "ok"])
        with mock.patch.object(C.time, "sleep"):
            self.assertEqual(C.api_call(fn, min_interval=0, wait_on_limit=0), "ok")
        self.assertEqual(fn.call_count, 2)

    def test_persistent_error_raises(self):
        with mock.patch.object(C.time, "sleep"), self.assertRaises(RuntimeError):
            C.api_call(mock.Mock(side_effect=RuntimeError("x")), min_interval=0)


class SessionTests(unittest.TestCase):
    def test_expected_session(self):
        tz = C.TZ
        for now, exp in [(datetime(2026, 11, 13, 15, 5, tzinfo=tz), "2026-11-13"),
                         (datetime(2026, 11, 16, 8, 25, tzinfo=tz), "2026-11-13"),
                         (datetime(2026, 11, 15, 10, 0, tzinfo=tz), "2026-11-13"),
                         (datetime(2026, 11, 17, 14, 0, tzinfo=tz), "2026-11-16")]:
            with self.subTest(now=now):
                self.assertEqual(C.expected_session(now), exp)


class FetchCollectTests(unittest.TestCase):
    def setUp(self):
        self.daily = Path(tempfile.mkdtemp()) / "tape" / "daily.csv"

    def test_pagination_stops_on_short_page(self):
        pages = {1: ticks().iloc[:3], 2: ticks().iloc[3:6], 3: ticks().iloc[:0]}
        calls = []

        def page_fn(sym, p, size):
            calls.append(p)
            return pages[p]

        with no_wait():
            df, n = C.fetch_ticks("X", {}, page_size=3, page_fn=page_fn)
        self.assertEqual(len(df), 6)
        self.assertEqual(calls, [1, 2, 3])
        with no_wait():
            C.fetch_ticks("X", {}, page_size=10, page_fn=lambda s, p, z: ticks())
        self.assertEqual(n, 3)

    def run_collect(self, page_fn, symbols=("AAA", "BBB"), session="2026-11-13", **kw):
        with no_wait():
            return C.collect(list(symbols), session, cfg={}, page_fn=page_fn,
                             ref_fn=lambda s, d: (38000, 1000.0), daily_path=self.daily, log=lambda m: None, **kw)

    def test_errors_isolated_and_wrong_session_rejected(self):
        def page_fn(sym, p, size):
            if sym == "BAD":
                raise RuntimeError("down")
            return ticks(day="2026-11-12") if sym == "OLD" else ticks()

        rows, errors = self.run_collect(page_fn, symbols=("AAA", "BAD", "OLD"))
        self.assertEqual([r["symbol"] for r in rows], ["AAA"])
        self.assertIn("down", errors["BAD"])
        self.assertIn("2026-11-12", errors["OLD"])
        self.assertTrue((self.daily.parent / "status.json").exists())
        self.assertTrue((self.daily.parent / "raw" / "2026-11-13.csv.gz").exists())

    def test_incomplete_rejected(self):
        rows, errors = self.run_collect(lambda s, p, z: ticks(rows=[("10:00:00", 10.0, 100, "buy")]), symbols=("AAA",))
        self.assertEqual(rows, [])
        self.assertIn("chưa kết thúc", errors["AAA"])

    def test_rerun_is_idempotent_and_skips_collected(self):
        page_fn = mock.Mock(side_effect=lambda s, p, z: ticks())
        self.run_collect(page_fn)
        first = C.load_daily(self.daily)
        page_fn.reset_mock()
        rows, _ = self.run_collect(page_fn)
        page_fn.assert_not_called()
        self.assertEqual(rows, [])
        self.run_collect(page_fn, force=True)
        again = C.load_daily(self.daily)
        self.assertEqual(len(first), 2)
        self.assertEqual(len(again), 2)


def history(n=25):
    rows = []
    for i, d in enumerate(pd.bdate_range("2026-10-01", periods=n)):
        for sym, b, s in (("AAA", 3000 + i, 1000), ("BBB", 1000, 3000), ("CCC", 10, 10)):
            rows.append({"date": d.strftime("%Y-%m-%d"), "symbol": sym, "buy_vol": b, "sell_vol": s,
                         "buy_value_bn": b * 0.01, "sell_value_bn": s * 0.01, "large_buy_value_bn": 1.0,
                         "large_sell_value_bn": 0.5, "nar": (b - s) / (b + s), "reconciled": True})
    return pd.DataFrame(rows)


class MetricsTests(unittest.TestCase):
    def test_features_windows_use_summed_volume(self):
        h = history()
        f = M.tape_features(h, "AAA")
        w = h[h.symbol == "AAA"].tail(5)
        exp = (w.buy_vol.sum() - w.sell_vol.sum()) / (w.buy_vol.sum() + w.sell_vol.sum())
        self.assertEqual(f["n_days"], 25)
        self.assertAlmostEqual(f["nar_5"], round(exp, 4))
        self.assertAlmostEqual(f["large_net_bn_5"], 2.5)
        self.assertIsNone(M.tape_features(h.head(6), "AAA")["nar_5"])  # only 2 days → no 5d value

    def test_unreconciled_rows_ignored(self):
        h = history(3)
        h.loc[h.symbol == "AAA", "reconciled"] = False
        self.assertEqual(M.tape_features(h, "AAA")["n_days"], 0)

    def test_leaders_and_format(self):
        h = history()
        day = h.date.max()
        tb, ts = M.daily_leaders(h, day, k=10, min_value_bn=1.0)
        self.assertEqual([r["symbol"] for r in tb], ["AAA"])
        self.assertEqual([r["symbol"] for r in ts], ["BBB"])  # CCC below liquidity floor
        msg = M.format_leaders(day, tb, ts)
        self.assertIn("AAA +", msg)
        self.assertIn("BBB -", msg)
        self.assertIsNone(M.format_leaders(day, [], []))

    def test_note(self):
        self.assertIsNone(M.tape_note({"n_days": 0}))
        self.assertIn("5p", M.tape_note(M.tape_features(history(), "AAA")))


if __name__ == "__main__":
    unittest.main()
