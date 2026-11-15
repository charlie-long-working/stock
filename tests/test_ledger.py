"""setups.ledger: vào lệnh mở cửa phiên sau, T+2, các kiểu thoát, trần 5 vị thế, idempotent, an toàn dữ liệu,
và ĐỐI CHIẾU với backtest (cùng engine thoát → cùng ngày/lý do thoát)."""

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from vn_stock.research import setup_backtest as S
from vn_stock.setups import ledger as L
from vn_stock.setups.exits import ExitParams

FLAT = (100, 101, 99, 100)
EX = ExitParams(mode="A", tp_r=2.0, time_stop=20)


def bars(rows, start="2026-10-01"):
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    df["time"] = pd.bdate_range(start, periods=len(df))
    df["volume"] = 1e6
    return df[["time", "open", "high", "low", "close", "volume"]]


def day(df, i):
    return pd.Timestamp(df["time"].iloc[i]).strftime("%Y-%m-%d")


NOFLAGS = {}


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "ledger.json"

    def new(self):
        return L.Ledger(self.path)

    def test_pending_then_open_with_next_open(self):
        df = bars([FLAT] * 3)
        led = self.new()
        led.add("AAA", "macd_rsi_atr", day(df, 2), 100.0, 95.0, 110.0, EX)
        self.assertEqual(led.process("AAA", df, NOFLAGS), [])
        self.assertEqual(led.positions[0]["status"], "pending")
        df2 = bars([FLAT] * 3 + [(101, 102, 100, 101)] * 2)
        led.process("AAA", df2, NOFLAGS)
        p = led.positions[0]
        self.assertEqual((p["status"], p["entry_px"], p["entry_date"]), ("open", 101.0, day(df2, 3)))

    def test_t2_and_stop_exit_message(self):
        rows = [FLAT] * 3 + [(100, 101, 94, 96), (96, 97, 93, 94), (94, 97, 93.5, 96)]
        df = bars(rows)
        led = self.new()
        led.add("AAA", "macd_rsi_atr", day(df, 2), 100.0, 95.0, 110.0, EX)
        ch = led.process("AAA", df, NOFLAGS)
        self.assertEqual(len(ch), 1)
        p = ch[0]
        self.assertEqual((p["exit_date"], p["exit_px"], p["exit_reason"]), (day(df, 5), 95.0, "SL"))
        self.assertAlmostEqual(p["ret"], 95 * (1 - 0.0025) / (100 * 1.0015) - 1)
        msg = L.format_exit(p)
        self.assertIn("BÁN / THOÁT", msg)
        self.assertIn("chạm cắt lỗ", msg)
        self.assertEqual(led.process("AAA", df, NOFLAGS), [])     # đã đóng → không báo lại

    def test_cancel_on_gap_and_stop_above_open(self):
        df = bars([FLAT] * 3 + [(107, 108, 106, 107)])
        led = self.new()
        led.add("AAA", "s", day(df, 2), 100.0, 95.0, None, EX)
        self.assertEqual(led.process("AAA", df, NOFLAGS)[0]["status"], "cancelled")
        df2 = bars([FLAT] * 3 + [(94, 95, 93, 94)])
        led2 = L.Ledger(Path(tempfile.mkdtemp()) / "l.json")
        led2.add("AAA", "s", day(df2, 2), 100.0, 95.0, None, EX)
        self.assertIn("dưới mức cắt lỗ", led2.process("AAA", df2, NOFLAGS)[0]["reason"])
        self.assertIn("HUỶ", L.format_exit(led2.positions[0]))

    def test_signal_exit_and_breakdown(self):
        df = bars([FLAT] * 10)
        flags = {"signal_exit": np.array([False] * 6 + [True] + [False] * 3)}
        ex = ExitParams(mode="A", use_breakdown=False, use_signal_exit=True)
        led = self.new()
        led.add("AAA", "macd_rsi_atr", day(df, 2), 100.0, 95.0, 110.0, ex)
        p = led.process("AAA", df, flags)[0]
        self.assertEqual((p["exit_reason"], p["exit_date"]), ("signal", day(df, 7)))
        df2 = bars([FLAT] * 6 + [(99, 99, 96, 96.5)] + [FLAT] * 3)
        led2 = L.Ledger(Path(tempfile.mkdtemp()) / "l.json")
        led2.add("AAA", "base_breakout", day(df2, 2), 100.0, 90.0, None, ExitParams(mode="B"), base_low=97.5)
        self.assertEqual(led2.process("AAA", df2, NOFLAGS)[0]["exit_reason"], "breakdown")

    def test_max_positions_and_duplicates(self):
        led = self.new()
        for i, s in enumerate("ABCDE"):
            self.assertIsNotNone(led.add(s, "x", "2026-10-01", 100, 95, None, EX))
        self.assertIsNone(led.add("F", "x", "2026-10-01", 100, 95, None, EX))
        self.assertIsNone(led.add("A", "x", "2026-10-01", 100, 95, None, EX))

    def test_relative_levels_survive_dividend_adjustment(self):
        rows = [FLAT] * 3 + [(100, 101, 94, 96), (96, 97, 93, 94), (94, 97, 93.5, 96)]
        df = bars(rows)
        led = self.new()
        led.add("AAA", "s", day(df, 2), 100.0, 95.0, 110.0, EX)
        adj = df.copy()
        adj[["open", "high", "low", "close"]] *= 0.9      # chia cổ tức: giá quá khứ giảm 10%
        p = led.process("AAA", adj, NOFLAGS)[0]
        self.assertAlmostEqual(p["exit_px"], 85.5)       # 95 × 0,9
        self.assertAlmostEqual(p["ret"], 95 * (1 - 0.0025) / (100 * 1.0015) - 1)

    def test_save_load_and_no_capital_field(self):
        led = self.new()
        led.add("AAA", "x", "2026-10-01", 100, 95, None, EX)
        led.save()
        raw = json.loads(self.path.read_text())
        keys = set(raw["positions"][0])
        self.assertFalse(keys & {"capital", "equity", "cash", "account"})
        self.assertEqual(len(L.Ledger(self.path).positions), 1)


class ParityTests(unittest.TestCase):
    """Sổ lệnh live và backtest dùng chung exits.step → cùng ngày thoát và lý do (giá khác nhau đúng bằng trượt giá)."""

    def test_same_exit_as_backtest(self):
        rng = np.random.default_rng(5)
        c = 100 * np.exp(np.cumsum(rng.normal(0.002, 0.02, 80)))
        o = np.r_[c[0], c[:-1]] * (1 + rng.normal(0, 0.003, 80))
        df = bars(list(zip(o, np.maximum(o, c) * 1.01, np.minimum(o, c) * 0.99, c)))
        sig = pd.DataFrame({"entry": False, "stop": np.nan, "rvol": 2.0, "base_low": np.nan, "bear_div": False,
                            "signal_exit": False}, index=df.index)
        t = 10
        stop = float(df["close"].iloc[t]) * 0.95
        sig.loc[t, ["entry", "stop"]] = [True, stop]
        cfg = S.Config("base_breakout", (), ExitParams(mode="B", time_stop=40, use_breakdown=False), False)
        nocost = {"fee_buy": 0.0, "fee_sell": 0.0, "tax_sell": 0.0, "slippage": 0.0}
        bt = S.simulate_symbol("AAA", df, sig, cfg, nocost)[0]
        led = L.Ledger(Path(tempfile.mkdtemp()) / "l.json")
        led.add("AAA", "base_breakout", day(df, t), float(df["close"].iloc[t]), stop, None, cfg.exit)
        lv = led.process("AAA", df, {})[0]
        self.assertEqual((lv["exit_date"], lv["exit_reason"]), (bt["exit_date"], bt["exit"]))
        self.assertAlmostEqual(lv["exit_px"], bt["exit_px"], places=3)


if __name__ == "__main__":
    unittest.main()
