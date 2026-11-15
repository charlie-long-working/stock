"""run_swing_vn: session/week boundaries, liquidity filter, long-only strategies, edge trigger, dedupe.
Offline: synthetic prices, mocked strategies/clock/Telegram. Needs ../Trading-bot on PYTHONPATH (botdown.swing_common)."""

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

from vn_stock.scripts import run_swing_vn as R
from vn_stock.strategies.macd_rsi import MACDRSIResult, MACDRSISignalType
from vn_stock.strategies.macd_signed import MacdSignedIdea


def at(s):
    return mock.patch.object(R, "now_vn", return_value=datetime.fromisoformat(s + "+07:00"))


def prices(n=300, end="2026-11-13", price=50.0, vol=1_000_000.0, step=0.003):
    t = pd.bdate_range(end=end, periods=n)
    c = price * np.exp(np.cumsum(np.full(n, step)))
    return pd.DataFrame({"time": t, "open": c, "high": c * 1.01, "low": c * 0.99, "close": c, "volume": vol})


def idea(side="long", setup="cross"):
    return MacdSignedIdea(side=side, regime="macd_pos", setup=setup, tier="tier1", entry=50.0, entry_low=49.5,
                          entry_high=50.5, stop_loss=48.0, take_profit=54.0, risk=2.0, rr=2.0, rsi=55.0,
                          hist=0.1, reason="cross up")


class SessionTests(unittest.TestCase):
    def test_expected_last_session(self):
        for now, exp in [("2026-11-14T09:00:00", "2026-11-13"),   # Sat → Fri
                         ("2026-11-16T10:00:00", "2026-11-13"),   # Mon before close → Fri
                         ("2026-11-17T16:00:00", "2026-11-17"),   # Tue after close → today
                         ("2026-11-17T14:59:00", "2026-11-16")]:
            with self.subTest(now=now), at(now):
                self.assertEqual(R._expected_last_session(), exp)

    def test_week_closes_only_after_friday_session(self):
        df = prices(400, end="2026-11-13")  # ends Friday
        with at("2026-11-13T14:00:00"):
            _, we = R._weekly(df)
        self.assertEqual(we, "2026-11-06")  # Friday before close → previous week
        with at("2026-11-13T15:30:00"):
            t, we = R._weekly(df)
        self.assertEqual(we, "2026-11-13")
        self.assertEqual(t["bias"], "Tăng")


class ScanSymbolTests(unittest.TestCase):
    def scan(self, df, macd=None, signed=(None, None), min_value=10.0):
        macd = macd or MACDRSIResult(signal=MACDRSISignalType.NEUTRAL)
        with mock.patch.object(R, "macd_rsi_signal", return_value=macd), \
             mock.patch.object(R, "macd_signed_signal", side_effect=list(signed)):
            return R.scan_symbol("AAA", df, None, "bearish", min_value)

    def test_illiquid_symbol_skipped(self):
        sigs, why = self.scan(prices(vol=1000.0))
        self.assertEqual(sigs, [])
        self.assertIn("GTGD", why)

    def test_macd_rsi_long_signal(self):
        r = MACDRSIResult(signal=MACDRSISignalType.LONG, stop_loss=48.0, take_profit=55.0, rsi=58.0)
        sigs, why = self.scan(prices(), macd=r)
        self.assertIsNone(why)
        self.assertEqual([(s.strategy, s.side, s.stop, s.target) for s in sigs], [("macd_rsi_atr", "long", 48.0, 55.0)])
        self.assertTrue(any("T+2" in n for n in sigs[0].notes))

    def test_macd_signed_only_new_long_setups(self):
        self.assertEqual(self.scan(prices(), signed=(idea(), None))[0][0].strategy, "macd_signed")
        self.assertEqual(self.scan(prices(), signed=(idea(), idea()))[0], [])          # same setup as yesterday
        self.assertEqual(self.scan(prices(), signed=(idea("short"), None))[0], [])     # VN: no shorts
        self.assertEqual(len(self.scan(prices(), signed=(idea(setup="continuation"), idea()))[0]), 1)

    def test_short_history(self):
        self.assertEqual(self.scan(prices(50))[1], "thiếu dữ liệu")


class MainTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.adj = self.tmp / "adj"
        self.adj.mkdir()
        for s in ["AAA", "VNINDEX", "VN30", "HNXINDEX"]:
            prices(400, end="2026-11-13").to_csv(self.adj / f"{s}.csv", index=False)

    def run_main(self, send, argv):
        r = MACDRSIResult(signal=MACDRSISignalType.LONG, stop_loss=48.0, take_profit=55.0, rsi=58.0)
        with mock.patch.object(R, "ADJ", self.adj), mock.patch.object(R, "STORE", self.tmp / "sent.json"), \
             mock.patch.object(R, "_intel_index", return_value=({"AAA": {}}, {"regime": "bearish"})), \
             mock.patch.object(R, "wait_for_intel", return_value="ok"), \
             mock.patch.object(R, "macd_rsi_signal", return_value=r), \
             mock.patch.object(R, "macd_signed_signal", return_value=None), \
             mock.patch("vn_stock.notify.telegram.send_message", send), \
             mock.patch("sys.argv", ["x"] + argv), mock.patch("builtins.print"), at("2026-11-13T16:05:00"):
            return R.main()

    def test_signal_weekly_and_dedupe(self):
        send = mock.Mock(return_value=(True, None))
        self.assertEqual(self.run_main(send, ["--wait-min", "0"]), 0)
        text = "\n".join(c[0][0] for c in send.call_args_list)
        self.assertIn("xu hướng tuần kết thúc 2026-11-13", text)
        self.assertIn("macd_rsi_atr", text)
        send.reset_mock()
        self.run_main(send, ["--wait-min", "0"])
        send.assert_not_called()

    def test_stale_data_warning(self):
        send = mock.Mock(return_value=(True, None))
        with mock.patch.object(R, "_expected_last_session", return_value="2026-11-20"):
            self.run_main(send, ["--wait-min", "0", "--daily-only"])
        self.assertIn("chưa có phiên 2026-11-20", send.call_args[0][0])


if __name__ == "__main__":
    unittest.main()
