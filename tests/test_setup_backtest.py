"""research.setup_backtest: mô phỏng (phí, T+2, không đuổi giá, 1 vị thế/mã, sự kiện DN), danh mục 5 vị thế,
bootstrap/baseline tái lập được, ngưỡng đạt chuẩn. Dữ liệu giả, không mạng."""

import unittest

import numpy as np
import pandas as pd

from vn_stock.research import setup_backtest as S
from vn_stock.setups.exits import ExitParams

COSTS = {"fee_buy": 0.0015, "fee_sell": 0.0015, "tax_sell": 0.001, "slippage": 0.001}
CFG = S.Config("base_breakout", (), ExitParams(mode="A", tp_r=2.0, time_stop=20), False)


def bars(rows, start="2024-01-01"):
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    df["time"] = pd.bdate_range(start, periods=len(df))
    df["volume"] = 1e6
    return df[["time", "open", "high", "low", "close", "volume"]]


def sig_frame(n, entries, stop):
    s = pd.DataFrame({"entry": False, "stop": np.nan, "rvol": 2.0, "base_low": np.nan, "bear_div": False,
                      "signal_exit": False}, index=range(n))
    for i in entries:
        s.loc[i, "entry"], s.loc[i, "stop"] = True, stop
    return s


FLAT = (100, 101, 99, 100)


class SimulateTests(unittest.TestCase):
    def test_costs_and_tp(self):
        rows = [FLAT] * 3 + [(100, 101, 99, 100)] * 3 + [(100, 112, 100, 111)] + [FLAT] * 3
        df = bars(rows)
        tr = S.simulate_symbol("X", df, sig_frame(len(df), [2], 95.0), CFG, COSTS)
        self.assertEqual(len(tr), 1)
        t = tr[0]
        entry = 100 * 1.001
        target = entry + 2 * (entry - 95.0)
        exit_px = target * 0.999
        self.assertAlmostEqual(t["entry_px"], round(entry, 4))
        self.assertEqual(t["exit"], "TP")
        self.assertAlmostEqual(t["ret"], exit_px * (1 - 0.0015 - 0.001) / (entry * 1.0015) - 1, places=9)
        self.assertEqual((t["date"], t["entry_date"]), ("2024-01-03", "2024-01-04"))

    def test_chase_skip_and_one_position(self):
        rows = [FLAT] * 2 + [(107, 108, 106, 107)] + [FLAT] * 30
        df = bars(rows)
        tr = S.simulate_symbol("X", df, sig_frame(len(df), [1], 95.0), CFG, COSTS)
        self.assertEqual(tr, [])                       # mở cửa +7% so với close tín hiệu → bỏ
        df2 = bars([FLAT] * 70)
        tr2 = S.simulate_symbol("X", df2, sig_frame(70, [2, 5, 8, 30], 95.0), CFG, COSTS)
        days = pd.bdate_range("2024-01-01", periods=70)
        self.assertEqual([t["date"] for t in tr2], [days[i].strftime("%Y-%m-%d") for i in (2, 30)])  # 5, 8 bỏ: đang có vị thế
        self.assertEqual(tr2[0]["exit"], "time")
        self.assertEqual(S.simulate_symbol("X", bars([FLAT] * 15), sig_frame(15, [2], 95.0), CFG, COSTS), [])  # còn mở → không tính

    def test_corporate_action_trade_dropped(self):
        rows = [FLAT] * 3 + [FLAT] * 3 + [(80, 81, 79, 80)] + [FLAT] * 30
        df = bars(rows)
        self.assertEqual(S.simulate_symbol("X", df, sig_frame(len(df), [2], 70.0), CFG, COSTS), [])

    def test_regime_filter(self):
        df = bars([FLAT] * 40)
        cfg = S.Config("base_breakout", (), ExitParams(mode="A"), True)
        bear = pd.Series(True, index=pd.to_datetime(df["time"]))
        self.assertEqual(S.simulate_symbol("X", df, sig_frame(40, [2], 95.0), cfg, COSTS, bearish=bear), [])


def trades(n, ret=0.02, start="2024-01-02", hold=5, symbols=("A", "B", "C", "D", "E", "F")):
    days = pd.bdate_range(start, periods=n * 3)
    rows = []
    for i in range(n):
        rows.append({"symbol": symbols[i % len(symbols)], "date": days[i * 2].strftime("%Y-%m-%d"),
                     "entry_date": days[i * 2 + 1].strftime("%Y-%m-%d"),
                     "exit_date": days[min(i * 2 + 1 + hold, len(days) - 1)].strftime("%Y-%m-%d"),
                     "ret": ret if i % 3 else -ret / 2, "r_mult": 1.0, "bars": hold, "rvol": 2.0, "risk": 0.05})
    return pd.DataFrame(rows)


class PortfolioStatsTests(unittest.TestCase):
    def test_portfolio_caps_concurrent(self):
        t = trades(30, hold=20)
        acc, port = S.portfolio(t, max_pos=5)
        self.assertLess(len(acc), len(t))
        for d in pd.bdate_range("2024-01-02", periods=90):
            ds = d.strftime("%Y-%m-%d")
            self.assertLessEqual(int(((acc["entry_date"] <= ds) & (acc["exit_date"] >= ds)).sum()), 5)
        self.assertAlmostEqual(acc["w"].iloc[0], 0.2)   # 1% / 5% rủi ro = 20% (trần)

    def test_stats_and_bootstrap_reproducible(self):
        t = trades(60)
        s = S.stats(t)
        self.assertEqual(s["n"], 60)
        self.assertGreater(s["pf"], 1)
        a = S.block_bootstrap_lb(t["ret"].to_numpy(), n_iter=500)
        self.assertEqual(a, S.block_bootstrap_lb(t["ret"].to_numpy(), n_iter=500))
        self.assertIsNone(S.block_bootstrap_lb(np.array([0.1, 0.2])))

    def test_period_split(self):
        self.assertEqual([S.period(d) for d in ("2021-12-31", "2022-01-03", "2023-12-29", "2024-01-02")],
                         ["train", "validate", "validate", "oos"])


class GateTests(unittest.TestCase):
    def test_strong_edge_ships(self):
        rng = np.random.default_rng(0)
        oos = trades(120, symbols=tuple("ABCDEFGHIJKL"))
        oos["ret"] = rng.normal(0.03, 0.02, len(oos))
        oos.loc[::3, "ret"] = -0.01
        oos["entry_date"] = [("2024" if i < 60 else "2025") + d[4:] for i, d in enumerate(oos["entry_date"])]
        acc, port = S.portfolio(oos)
        g = S.evaluate_gates(oos, oos, oos, np.full(500, 0.0), port)
        self.assertEqual(g["verdict"], "ship", g["checks"])

    def test_weak_edge_is_watch_or_off(self):
        oos = trades(80)
        oos["ret"] = np.where(np.arange(80) % 2, 0.011, -0.01)
        acc, port = S.portfolio(oos)
        g = S.evaluate_gates(oos, oos, oos, np.full(500, 0.02), port)
        self.assertEqual(g["verdict"], "watch")
        self.assertFalse(g["checks"]["pf>=1.2"])
        oos["ret"] = -0.01
        self.assertEqual(S.evaluate_gates(oos, oos, oos, np.full(10, 0.0), port)["verdict"], "off")

    def test_concentration_gate(self):
        oos = trades(80, symbols=("A", "B"))
        c = S.concentration(oos)
        self.assertGreater(c["top_share"], 0.25)


class SelectionTests(unittest.TestCase):
    def test_select_uses_train_and_validate_only(self):
        a = S.Config("div_bull", (("trigger", "immediate"),), ExitParams(mode="A"), False)
        b = S.Config("div_bull", (("trigger", "confirm"),), ExitParams(mode="A"), False)
        c = S.Config("div_bull", (("trigger", "immediate"),), ExitParams(mode="B"), False)
        cfgs = {a.id: a, b.id: b, c.id: c}
        res = {a.id: {"train": {"n": 200, "mean": 0.01}, "validate": {"pf": 1.3}},
               b.id: {"train": {"n": 200, "mean": 0.02}, "validate": {"pf": 0.9}},
               c.id: {"train": {"n": 200, "mean": 0.005}, "validate": {"pf": 1.4}}}
        self.assertEqual(S.select(res, cfgs, "div_bull"), a.id)   # b tốt hơn train nhưng hỏng validate
        res[c.id]["validate"]["pf"] = 0.8                          # lân cận của a đều yếu → a không bền
        self.assertEqual(S.select(res, cfgs, "div_bull"), None)
        res[c.id]["validate"]["pf"] = 1.4
        res[a.id]["train"]["n"] = 10                               # thiếu mẫu train → không được chọn
        self.assertEqual(S.select(res, cfgs, "div_bull"), c.id)
        self.assertEqual(S.config_from_dict(a.to_dict()).id, a.id)


class MacdSignedCausalityTests(unittest.TestCase):
    """Backtest macd_signed phải ra ĐÚNG tín hiệu mà bot live tính trên dữ liệu cắt tới nến i
    (precompute swing trên cả chuỗi sẽ lộ đỉnh/đáy trước khi được xác nhận)."""

    def test_matches_live_on_prefix(self):
        from vn_stock.strategies.macd_signed import MacdSignedParams, macd_signed_signal

        rng = np.random.default_rng(21)
        n = 420
        c = 50 * np.exp(np.cumsum(rng.normal(0.0005, 0.018, n)))
        o = np.r_[c[0], c[:-1]]
        df = pd.DataFrame({"time": pd.bdate_range("2020-01-01", periods=n), "open": o,
                           "high": np.maximum(o, c) * 1.01, "low": np.minimum(o, c) * 0.99, "close": c,
                           "volume": 1e6})
        p = MacdSignedParams(allow_short=False)
        fr = S.macd_signed_frame(df, p, warmup=60)
        hi, lo, cl = (df[k].to_numpy() for k in ("high", "low", "close"))
        checked = 0
        for i in range(61, n):
            idea = macd_signed_signal(hi[: i + 1], lo[: i + 1], cl[: i + 1], p)
            prev = macd_signed_signal(hi[:i], lo[:i], cl[:i], p)
            fresh = idea is not None and idea.side == "long" and (
                prev is None or (prev.setup, prev.side) != (idea.setup, idea.side))
            self.assertEqual(bool(fr["entry"].iloc[i]), fresh, i)
            if fresh:
                self.assertAlmostEqual(fr["stop"].iloc[i], idea.stop_loss, places=9)
                self.assertAlmostEqual(fr["target"].iloc[i], idea.take_profit, places=9)
                checked += 1
        self.assertGreater(checked, 3)


if __name__ == "__main__":
    unittest.main()
