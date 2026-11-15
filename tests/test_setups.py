"""vn_stock.setups: nền/phá nền, phân kỳ, engine thoát (T+2), % vốn — dữ liệu giả, không mạng.
Quan trọng nhất: test CHỐNG NHÌN TRƯỚC (tính trên df[:k] phải giống hệt dòng k−1 khi tính trên df đầy đủ)."""

import unittest

import numpy as np
import pandas as pd

from vn_stock.setups import base_breakout as B
from vn_stock.setups import divergence as V
from vn_stock.setups import features as F
from vn_stock.setups.exits import ExitParams, Position, init_target, step
from vn_stock.setups.sizing import max_pct_capital, sizing_note


def frame(close, vol=None, spread=0.01, start="2015-01-01"):
    c = np.asarray(close, float)
    o = np.r_[c[0], c[:-1]]
    hi = np.maximum(o, c) * (1 + spread / 2)
    lo = np.minimum(o, c) * (1 - spread / 2)
    v = np.full(len(c), 1_000_000.0) if vol is None else np.asarray(vol, float)
    return pd.DataFrame({"time": pd.bdate_range(start, periods=len(c)), "open": o, "high": hi, "low": lo,
                         "close": c, "volume": v})


def random_walk(n=700, seed=3):
    rng = np.random.default_rng(seed)
    return frame(50 * np.exp(np.cumsum(rng.normal(0.0004, 0.015, n))),
                 vol=rng.uniform(5e5, 2e6, n))


def base_then_breakout():
    """300 phiên tăng đều → 40 phiên đi ngang 98–102 volume cạn → phá nền 104.5 với volume ×3."""
    up = np.linspace(40, 99, 300)
    rng = np.random.default_rng(1)
    flat = 100 + rng.uniform(-1.5, 1.5, 40)
    close = np.r_[up, flat, 104.5, 105.5, 106, 107, 108]
    vol = np.r_[np.full(300, 1.0e6), np.full(40, 0.55e6), 3.0e6, 1.2e6, 1.2e6, 1.2e6, 1.2e6]
    df = frame(close, vol, spread=0.008)
    df.loc[340, "high"] = 104.7  # đóng cửa gần đỉnh phiên (CLV cao)
    df.loc[340, "low"] = 101.0
    return df


class FeatureTests(unittest.TestCase):
    def test_pctrank_and_atr(self):
        s = pd.Series([1.0, 2, 3, 4, 5])
        self.assertEqual(F.rolling_pctrank(s, 5).iloc[-1], 1.0)
        self.assertTrue(np.isnan(F.rolling_pctrank(s, 5).iloc[3]))
        self.assertGreater(F.atr(random_walk(100)).iloc[-1], 0)


class NoLookaheadTests(unittest.TestCase):
    def assert_prefix_equal(self, fn, df, cols, ks):
        full = fn(df)
        for k in ks:
            part = fn(df.iloc[:k].reset_index(drop=True))
            for col in cols:
                a, b = part[col].iloc[-1], full[col].iloc[k - 1]
                if isinstance(a, (float, np.floating)) and np.isnan(a):
                    self.assertTrue(np.isnan(b), (col, k))
                else:
                    self.assertEqual(a, b, (col, k))

    def test_base_breakout_is_causal(self):
        df = random_walk(700)
        self.assert_prefix_equal(lambda d: B.detect(d, B.BaseParams(require_uptrend=False, bbw_rank_max=0.9,
                                                                       dryup_max=2.0, drift_frac=2.0)),
                                 df, ["base_ok", "base_high", "breakout", "breakdown", "stop"], range(280, 700, 37))

    def test_divergence_is_causal(self):
        df = random_walk(700, seed=9)
        self.assert_prefix_equal(lambda d: V.detect(d, V.DivSetupParams(require_sma200=False)),
                                 df, ["bull_div", "bear_div", "entry", "stop"], range(280, 700, 41))


class BaseBreakoutTests(unittest.TestCase):
    P = B.BaseParams(min_value_bn=0.0)

    def test_breakout_fires_on_the_breakout_bar_only(self):
        df = base_then_breakout()
        out = B.detect(df, self.P)
        self.assertEqual(list(np.nonzero(out["breakout"].to_numpy())[0]), [340])
        self.assertTrue(out.loc[339, "base_ok"])
        self.assertGreaterEqual(out.loc[340, "base_n"], 20)
        self.assertLess(out.loc[340, "stop"], 104.5)

    def test_needs_volume(self):
        df = base_then_breakout()
        df.loc[340, "volume"] = 0.6e6   # < SMA50 volume (≈0,64 triệu sau nền cạn) → rvol < 1,5
        out = B.detect(df, self.P)
        self.assertFalse(out.loc[340, "breakout"])           # vượt đỉnh không có volume → không báo
        self.assertEqual(list(np.nonzero(out["breakout"].to_numpy())[0]), [341])  # phiên sau có volume → báo

    def test_steady_trend_is_not_a_base(self):
        df = frame(np.linspace(40, 120, 400))
        self.assertFalse(B.detect(df, self.P)["breakout"].any())

    def test_breakdown(self):
        df = base_then_breakout().iloc[:340].copy()
        df.loc[339, ["close", "low"]] = [95.0, 94.5]
        df.loc[339, "open"] = 99.0
        self.assertTrue(B.detect(df, self.P)["breakdown"].iloc[-1])


class DivergenceTests(unittest.TestCase):
    def test_bull_divergence_known_5_bars_after_pivot(self):
        # giá tạo đáy thấp hơn nhưng giảm chậm lại → phân kỳ dương ở đáy thứ 2
        a = np.linspace(100, 80, 10)    # nhịp giảm 1: dốc
        b = np.linspace(80, 88, 15)
        c = np.linspace(88, 78, 50)     # nhịp giảm 2: đáy thấp hơn nhưng thoải → MACD cao hơn
        d = np.linspace(78, 85, 20)
        close = np.r_[np.full(260, 100.0), a, b[1:], c[1:], d[1:]]
        df = frame(close, spread=0.004)
        first_low, second_low = 260 + 9, 260 + 9 + 14 + 49
        for k in (first_low, second_low):     # đáy pivot phải thấp hơn hẳn các nến hai bên
            df.loc[k, "low"] -= 0.3
        out = V.detect(df, V.DivSetupParams(require_sma200=False, min_value_bn=0, risk_max=0.5))
        idx = np.nonzero(out["bull_div"].to_numpy())[0]
        self.assertEqual(int(np.argmin(df["low"].to_numpy())), second_low)
        self.assertEqual(list(idx), [second_low + 5])          # biết đúng 5 nến sau đáy, không sớm hơn


class ExitEngineTests(unittest.TestCase):
    def pos(self, **kw):
        base = dict(symbol="X", setup="t", entry_i=0, entry_px=100.0, stop=95.0, atr=2.0)
        base.update(kw)
        return init_target(Position(**base), ExitParams(mode="A", tp_r=2.0, time_stop=20))

    def test_t2_stop_hit_on_day0_fills_on_day2(self):
        p, ex = self.pos(), ExitParams(mode="A")
        self.assertIsNone(step(p, 0, 100, 101, 94, 96, ex))   # chạm SL phiên mua → chưa bán được
        self.assertIsNone(step(p, 1, 96, 97, 93, 94, ex))
        ev = step(p, 2, 94, 97, 93.5, 96, ex)                  # chiều T+2: min(SL, close)
        self.assertEqual((ev.i, ev.px, ev.reason), (2, 95.0, "SL"))

    def test_gap_down_after_t2_fills_at_open(self):
        p, ex = self.pos(), ExitParams(mode="A")
        for i, bar in enumerate([(100, 101, 99, 100), (100, 101, 99, 100), (100, 101, 99, 100)]):
            self.assertIsNone(step(p, i, *bar, ex))
        ev = step(p, 3, 90, 92, 89, 91, ex)
        self.assertEqual((ev.px, ev.reason), (90, "SL"))

    def test_tp_and_sl_priority(self):
        p, ex = self.pos(), ExitParams(mode="A")
        for i in range(3):
            step(p, i, 100, 101, 99, 100, ex)
        ev = step(p, 3, 105, 111, 94, 100, ex)                 # chạm cả SL lẫn TP → SL trước
        self.assertEqual(ev.reason, "SL")
        p2 = self.pos()
        for i in range(3):
            step(p2, i, 100, 101, 99, 100, ex)
        self.assertEqual(step(p2, 3, 112, 113, 111, 112, ex).px, 112)  # gap qua TP → khớp open

    def test_tp_on_day2_needs_close(self):
        p, ex = self.pos(), ExitParams(mode="A")
        step(p, 0, 100, 101, 99, 100, ex)
        step(p, 1, 100, 101, 99, 100, ex)
        self.assertIsNone(step(p, 2, 100, 112, 99, 105, ex))   # chạm TP buổi sáng nhưng chiều không giữ
        self.assertEqual(step(p, 3, 106, 111, 105, 110, ex).reason, "TP")

    def test_structural_exit_next_open(self):
        p, ex = self.pos(), ExitParams(mode="A")
        for i in range(3):
            step(p, i, 100, 101, 99, 100, ex)
        self.assertIsNone(step(p, 3, 100, 101, 98, 98, ex, {"breakdown": True}))
        ev = step(p, 4, 97, 99, 96, 98, ex)
        self.assertEqual((ev.px, ev.reason), (97, "breakdown"))

    def test_time_stop_and_trailing(self):
        ex = ExitParams(mode="A", time_stop=5)
        p = self.pos()
        ev = None
        for i in range(10):
            ev = step(p, i, 100, 101, 99, 100, ex)
            if ev:
                break
        self.assertEqual((ev.i, ev.reason), (5, "time"))
        exb = ExitParams(mode="B", trail_atr=2.0, time_stop=40)
        q = init_target(Position("X", "t", 0, 100.0, 95.0, 2.0), exb)
        for i, c in enumerate([100, 103, 106, 110, 112]):
            step(q, i, c, c + 1, c - 1, c, exb)
        self.assertIsNone(q.target)
        self.assertEqual(q.stop, 108.0)                        # 112 − 2·ATR
        self.assertEqual(step(q, 5, 109, 110, 107, 108, exb).reason, "trail")


class SizingTests(unittest.TestCase):
    def test_sizing(self):
        self.assertAlmostEqual(max_pct_capital(100, 95), 0.20)    # 5% rủi ro → 20% (trần)
        self.assertAlmostEqual(max_pct_capital(100, 92), 0.125)   # 8% rủi ro → 12,5%
        self.assertEqual(max_pct_capital(100, 101), 0.0)
        self.assertIn("12.5%", sizing_note(100, 92))


if __name__ == "__main__":
    unittest.main()
