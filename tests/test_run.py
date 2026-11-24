import json
import os
import pathlib
import tempfile
import unittest
from unittest import mock

from bot import alpaca
from bot.run import run

BOT_DIR = pathlib.Path(__file__).resolve().parent.parent / "bot"


def bars(last_close, today="2026-12-01"):
    """200 abgeschlossene Tage zu 100 $, der letzte davon = last_close, plus der heutige Teilbalken."""
    hist = [(f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}", 100.0) for i in range(199)]
    hist.append(("2026-11-30", last_close))
    hist.append((today, last_close))
    return hist


class FakeClient:
    def __init__(self, is_open=True, today="2026-12-01", last_close=110.0, fill_status="filled"):
        self.is_open = is_open
        self.today = today
        self.last_close = last_close
        self.fill_status = fill_status
        self.submitted = []

    def clock(self):
        return {"is_open": self.is_open, "timestamp": f"{self.today}T10:00:00-05:00"}

    def daily_closes(self, symbol):
        return bars(self.last_close, self.today)

    def submit(self, symbol, order):
        self.submitted.append((symbol, order))
        return {"id": "o1"}

    def get_order(self, order_id):
        if self.fill_status != "filled":
            return {"status": self.fill_status}
        o = self.submitted[-1][1]
        qty = o.get("qty") or o["notional"] / self.last_close
        return {"status": "filled", "filled_qty": str(qty), "filled_avg_price": str(self.last_close)}


class RunTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.state = os.path.join(self.dir.name, "state.json")
        self.report = os.path.join(self.dir.name, "REPORT.md")

    def tearDown(self):
        self.dir.cleanup()

    def go(self, client):
        return run(client, lambda: 1.1, self.state, self.report, sleep=lambda s: None)

    def test_first_run_starts_test_and_buys(self):
        c = FakeClient(last_close=110.0)
        s = self.go(c)
        self.assertEqual(s["start_date"], "2026-12-01")
        self.assertEqual(s["eur_usd"], 1.1)
        self.assertEqual(c.submitted, [("SPY", {"side": "buy", "notional": 9.9})])
        self.assertAlmostEqual(s["shares"], 0.09)
        self.assertAlmostEqual(s["benchmark"]["shares"], 9.9 / 110.0)
        self.assertEqual(len(s["orders"]), 1)
        self.assertIn("Letzter erfolgreicher Lauf: **2026-12-01**", open(self.report).read())
        self.assertEqual(json.load(open(self.state))["last_run"], "2026-12-01")

    def test_closed_market_only_updates_report(self):
        self.go(FakeClient(last_close=110.0))
        c = FakeClient(is_open=False, today="2026-12-05")
        s = self.go(c)
        self.assertEqual(c.submitted, [])
        self.assertEqual(s["last_run"], "2026-12-05")
        self.assertIn("**2026-12-05**", open(self.report).read())

    def test_closed_market_before_start_writes_nothing(self):
        self.assertIsNone(self.go(FakeClient(is_open=False)))
        self.assertFalse(os.path.exists(self.state))

    def test_no_trade_mid_month(self):
        self.go(FakeClient(last_close=110.0))
        c = FakeClient(today="2026-12-02", last_close=90.0)
        self.go(c)
        self.assertEqual(c.submitted, [])

    def test_signal_change_sells_once_next_month(self):
        self.go(FakeClient(last_close=110.0))
        c = FakeClient(today="2027-01-04", last_close=90.0)
        s = self.go(c)
        self.assertEqual(len(c.submitted), 1)
        self.assertEqual(c.submitted[0][1]["side"], "sell")
        self.assertEqual(s["shares"], 0.0)

    def test_unfilled_order_retries_next_run(self):
        s = self.go(FakeClient(last_close=110.0, fill_status="rejected"))
        self.assertEqual(s["orders"], [])
        self.assertIsNone(s["last_decision_month"])
        c = FakeClient(today="2026-12-02", last_close=110.0)
        self.go(c)
        self.assertEqual(len(c.submitted), 1)


class SafetyTest(unittest.TestCase):
    def test_orders_only_go_to_paper(self):
        self.assertEqual(alpaca.TRADING_URL, "https://paper-api.alpaca.markets")

    def test_no_live_endpoint_in_code(self):
        for path in BOT_DIR.glob("*.py"):
            text = path.read_text()
            self.assertNotIn("://api.alpaca.markets", text, path.name)

    def test_missing_keys_stop_without_leaking(self):
        with mock.patch.dict(os.environ, {"ALPACA_KEY_ID": "", "ALPACA_SECRET_KEY": "geheim123"}):
            with self.assertRaises(SystemExit) as ctx:
                alpaca.AlpacaPaper.from_env()
        self.assertNotIn("geheim123", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
