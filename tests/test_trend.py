"""setups/trend.py: EMA 25/50/200 + dải tuần SMA20W/EMA21W — nhân quả, tuần đã đóng, chế độ lọc,
và cách bot / backtest dùng bộ lọc. Offline, giá tổng hợp. Cần ../Trading-bot trên PYTHONPATH (run_swing_vn)."""

import unittest
from unittest import mock

import numpy as np
import pandas as pd

from vn_stock.research import setup_backtest as S
from vn_stock.scripts import run_swing_vn as R
from vn_stock.setups import trend as T
from vn_stock.setups.exits import ExitParams
from vn_stock.strategies.macd_rsi import MACDRSIResult, MACDRSISignalType


def prices(n=600, end="2026-11-13", start=50.0, step=0.002, seed=0, noise=0.002):
    t = pd.bdate_range(end=end, periods=n)
    rng = np.random.default_rng(seed)
    c = start * np.exp(np.cumsum(step + rng.normal(0, noise, n)))
    return pd.DataFrame({"time": t, "open": c, "high": c * 1.01, "low": c * 0.99, "close": c, "volume": 2_000_000.0})


def trend_down_last(n=600):
    """Tăng dài rồi giảm mạnh 60 phiên cuối → nến cuối dưới EMA200 và dưới dải tuần."""
    df = prices(n, step=0.002)
    c = df["close"].to_numpy().copy()
    c[-60:] = c[-61] * np.exp(np.cumsum(np.full(60, -0.012)))
    df["open"], df["high"], df["low"], df["close"] = c, c * 1.01, c * 0.99, c
    return df


class TrendFrameTests(unittest.TestCase):
    def test_causal_prefix(self):
        df = prices(noise=0.01)
        full = T.trend_frame(df)
        cols = ["ema25", "ema50", "ema200", "sma20w", "ema21w", "full_ok"]
        for k in (250, 333, 452, len(df) - 2):  # gồm điểm giữa tuần
            with self.subTest(k=k):
                cut = T.trend_frame(df.iloc[: k + 1]).iloc[-1]
                np.testing.assert_allclose(cut[cols].astype(float), full.iloc[k][cols].astype(float), equal_nan=True)

    def test_weekly_band_uses_closed_weeks_only(self):
        df = prices(400, end="2026-11-18")  # kết thúc thứ Tư
        band = T.weekly_band(df)
        w = pd.Series(df["close"].to_numpy(), index=df["time"]).resample("W-FRI").last()
        expected = w.loc[:"2026-11-13"].rolling(20).mean().iloc[-1]  # tuần đóng gần nhất: thứ 6 13/11
        self.assertAlmostEqual(band["sma20w"].iloc[-1], expected)
        # thứ 6 13/11 đã dùng tuần của chính nó (đóng cửa thứ 6 = tuần đóng)
        i = df.index[df["time"] == "2026-11-13"][0]
        self.assertAlmostEqual(band["sma20w"].iloc[i], expected)
        self.assertNotAlmostEqual(band["sma20w"].iloc[i - 1], expected)

    def test_modes_and_states(self):
        up, down = T.trend_frame(prices()), T.trend_frame(trend_down_last())
        self.assertEqual(up["state"].iloc[-1], "up")
        self.assertTrue(T.passes(up, "full").iloc[-1])
        self.assertEqual(down["state"].iloc[-1], "down")
        for m in ("ema200", "band", "full"):
            self.assertFalse(T.passes(down, m).iloc[-1], m)
        self.assertTrue(T.passes(down, "none").all())
        with self.assertRaises(ValueError):
            T.passes(up, "bogus")

    def test_describe_marks_position(self):
        s = T.snapshot(trend_down_last())
        txt = T.describe(s)
        self.assertIn("⚠️ ngược xu hướng", txt)
        self.assertIn("EMA200", txt)
        self.assertIn("↓", txt)


class BacktestConfigTests(unittest.TestCase):
    def test_old_ids_unchanged_new_ids_differ(self):
        base = S.Config("macd_signed", (("allow_short", False),),
                        ExitParams(mode="A", time_stop=30, use_breakdown=False, use_signal_exit=True), False)
        self.assertEqual(base.id, "macd_signed-4198415f")  # id đang khoá trong setups/config.json
        filt = S.Config(base.setup, base.params, base.exit, False, "full")
        self.assertNotEqual(filt.id, base.id)
        self.assertEqual(S.config_from_dict(filt.to_dict()), filt)
        self.assertEqual(S.config_from_dict({k: v for k, v in base.to_dict().items() if k != "trend"}), base)

    def test_signals_filtered_by_trend(self):
        df = trend_down_last()
        cfg = S.Config("macd_rsi_atr", (), ExitParams(mode="A", time_stop=60), False, "full")
        feats = S.F.add_common(df)
        raw = S.signals(S.Config("macd_rsi_atr", (), cfg.exit, False), df, feats)["entry"]
        filt = S.signals(cfg, df, feats)["entry"]
        ok = T.passes(T.trend_frame(df), "full").to_numpy()
        self.assertTrue((filt.to_numpy() == (raw.to_numpy() & ok)).all())

    def test_pick_legacy_uses_validate_only(self):
        a, b = S.BENCHMARK, S.BENCHMARK_TREND
        res = {a.id: {"validate": {"n": 200, "pf": 0.9}}, b.id: {"validate": {"n": 80, "pf": 1.1}}}
        self.assertIs(S.pick_legacy(res, a, b), b)
        res[b.id] = {"validate": {"n": 10, "pf": 3.0}}  # quá ít lệnh
        self.assertIs(S.pick_legacy(res, a, b), a)


class BotTests(unittest.TestCase):
    LONG = MACDRSIResult(signal=MACDRSISignalType.LONG, rsi=55.0, stop_loss=40.0, take_profit=60.0)

    def scan(self, df, live_cfg):
        with mock.patch.object(R, "macd_rsi_signal", return_value=self.LONG), \
             mock.patch.object(R, "macd_signed_signal", return_value=None):
            return R.scan_symbol("AAA", df, None, "bearish", 10.0, None, live_cfg)

    def test_counter_trend_signal_dropped_only_when_config_asks(self):
        df = trend_down_last()
        sigs, _ = self.scan(df, {"macd_rsi_atr": {"verdict": "off", "config": {"trend": "none"}}})
        self.assertEqual(len(sigs), 1)
        self.assertTrue(any("⚠️ ngược xu hướng" in n for n in sigs[0].notes))
        sigs, _ = self.scan(df, {"macd_rsi_atr": {"verdict": "off", "config": {"trend": "full"}}})
        self.assertEqual(sigs, [])
        sigs, _ = self.scan(prices(), {"macd_rsi_atr": {"verdict": "off", "config": {"trend": "full"}}})
        self.assertEqual(len(sigs), 1)

    def test_watch_block_labels_and_orders_by_trend(self):
        items = [("BBB", {"setup": "base_breakout", "note": "x"}), ("AAA", {"setup": "base_breakout", "note": "y"})]
        txt = R.watch_block("2026-11-13", items, {}, {"AAA": {"state": "up"}, "BBB": {"state": "down"}})
        self.assertLess(txt.index("AAA"), txt.index("BBB"))
        self.assertIn("✅ thuận xu hướng", txt)
        self.assertIn("⚠️ ngược xu hướng", txt)
        self.assertNotIn("✅", R.watch_block("2026-11-13", items, {}))  # không có dữ liệu xu hướng → không gắn nhãn


if __name__ == "__main__":
    unittest.main()
