"""run_swing_vn: session/week boundaries, liquidity filter, long-only strategies, edge trigger, dedupe.
Offline: synthetic prices, mocked strategies/clock/Telegram. Needs ../Trading-bot on PYTHONPATH (botdown.swing_common)."""

import json
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

    def run_main(self, send, argv, tape=None, live=None, setups=None, collect=None, macd=True):
        r = (MACDRSIResult(signal=MACDRSISignalType.LONG, stop_loss=48.0, take_profit=55.0, rsi=58.0) if macd
             else MACDRSIResult(signal=MACDRSISignalType.NEUTRAL))
        self.collect = collect or mock.Mock(return_value=([], {}))
        with mock.patch.object(R, "ADJ", self.adj), mock.patch.object(R, "STORE", self.tmp / "sent.json"), \
             mock.patch.object(R, "LEDGER_PATH", self.tmp / "ledger.json"), \
             mock.patch.object(R.TAPE, "collect", self.collect), \
             mock.patch.object(R.TAPE, "load_daily", return_value=tape if tape is not None else pd.DataFrame()), \
             mock.patch.object(R.LIVE, "load_live_config", return_value=live or {}), \
             mock.patch.object(R.LIVE, "scan_setups", return_value=setups or ([], [])), \
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


    def test_tape_collected_only_when_live(self):
        send = mock.Mock(return_value=(True, None))
        self.run_main(send, ["--wait-min", "0"])
        self.collect.assert_called_once()
        self.run_main(send, ["--wait-min", "0", "--dry-run"])
        self.collect.assert_not_called()
        self.run_main(send, ["--wait-min", "0", "--no-tape"])
        self.collect.assert_not_called()

    def test_buy_goes_to_ledger_then_sell_message(self):
        send = mock.Mock(return_value=(True, None))
        self.run_main(send, ["--wait-min", "0", "--no-tape", "--daily-only"])
        led = json.loads((self.tmp / "ledger.json").read_text())
        self.assertEqual([p["status"] for p in led["positions"]], ["pending"])
        self.assertIn("Tối đa ~", send.call_args[0][0])                     # % vốn trong tin MUA
        # phiên sau: mở cửa rồi sập qua SL; 2 phiên sau nữa (T+2) mới bán được
        df = pd.read_csv(self.adj / "AAA.csv", parse_dates=["time"])
        last = df.iloc[-1]
        extra = pd.DataFrame({"time": pd.bdate_range(last["time"], periods=4)[1:],
                              "open": [last["close"], 40.0, 40.0], "high": [last["close"], 41.0, 41.0],
                              "low": [40.0, 39.0, 39.0], "close": [40.0, 40.0, 40.0], "volume": 1_000_000.0})
        pd.concat([df, extra]).to_csv(self.adj / "AAA.csv", index=False)
        send.reset_mock()
        with at("2026-11-18T16:05:00"):
            self.run_main(send, ["--wait-min", "0", "--no-tape", "--daily-only"], macd=False)
        text = "\n".join(c[0][0] for c in send.call_args_list)
        self.assertIn("BÁN / THOÁT", text)
        self.assertIn("chạm cắt lỗ", text)

    def test_dry_run_never_writes_ledger(self):
        self.run_main(mock.Mock(return_value=(True, None)), ["--wait-min", "0", "--dry-run", "--daily-only"])
        self.assertFalse((self.tmp / "ledger.json").exists())

    def test_ship_and_watch_setups(self):
        live = {"base_breakout": {"verdict": "ship", "evidence": "OOS tốt",
                                  "config": {"exit": {"mode": "B", "time_stop": 40}}},
                "div_bull": {"verdict": "watch", "evidence": "OOS chưa đạt", "config": {"exit": {"mode": "A"}}}}
        ship = [{"setup": "base_breakout", "close": 60.0, "stop": 56.0, "target": None, "base_low": 55.0,
                 "note": "nền 40 phiên"}]
        watch = [{"setup": "div_bull", "close": 60.0, "stop": 57.0, "target": 66.0, "base_low": None,
                  "note": "phân kỳ dương <x>"}]
        send = mock.Mock(return_value=(True, None))
        self.run_main(send, ["--wait-min", "0", "--no-tape", "--daily-only"], live=live, setups=(ship, watch), macd=False)
        text = "\n".join(c[0][0] for c in send.call_args_list)
        self.assertIn("base_breakout", text)
        self.assertIn("Theo dõi — chưa đạt kiểm chứng", text)
        self.assertIn("phân kỳ dương &lt;x&gt;", text)
        led = json.loads((self.tmp / "ledger.json").read_text())
        self.assertEqual([p["strategy"] for p in led["positions"]], ["base_breakout"])

    def test_tape_leaders_message(self):
        tape = pd.DataFrame([{"date": "2026-11-13", "symbol": "AAA", "buy_vol": 3e6, "sell_vol": 1e6,
                              "buy_value_bn": 30.0, "sell_value_bn": 10.0, "large_buy_value_bn": 5.0,
                              "large_sell_value_bn": 1.0, "nar": 0.5, "reconciled": True}])
        send = mock.Mock(return_value=(True, None))
        self.run_main(send, ["--wait-min", "0", "--no-tape", "--daily-only"], tape=tape)
        text = "\n".join(c[0][0] for c in send.call_args_list)
        self.assertIn("Dòng tiền chủ động 2026-11-13", text)
        self.assertIn("Mua chủ động ròng: 1p +50%", text)


if __name__ == "__main__":
    unittest.main()
