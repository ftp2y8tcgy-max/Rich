import unittest

from bot import core
from bot.report import render

RATE = 1.1  # 1 € = 1,10 $ -> Start 11,00 $, Gebühr 1,10 $
UP = [100.0] * 199 + [110.0]    # letzter Kurs über SMA200 -> hold
DOWN = [100.0] * 199 + [90.0]   # letzter Kurs unter SMA200 -> cash


def fresh():
    return core.new_state("2026-12-01", RATE, 100.0)


class StrategyTest(unittest.TestCase):
    def test_signal(self):
        self.assertEqual(core.signal(UP), "hold")
        self.assertEqual(core.signal(DOWN), "cash")
        self.assertIsNone(core.signal([100.0] * 199))

    def test_buy_on_first_day_of_month_when_above_sma(self):
        s = fresh()
        self.assertEqual(core.plan_order(s, "2026-12-01", UP), {"side": "buy", "notional": 9.9})
        self.assertEqual(s["last_decision_month"], "2026-12")

    def test_no_order_mid_month(self):
        s = fresh()
        core.plan_order(s, "2026-12-01", DOWN)  # Bargeld, keine Order
        self.assertIsNone(core.plan_order(s, "2026-12-15", UP))

    def test_no_order_when_position_already_matches(self):
        s = fresh()
        self.assertIsNone(core.plan_order(s, "2026-12-01", DOWN))
        core.apply_fill(s, "2026-12-01", "buy", 0.099, 100.0)
        self.assertIsNone(core.plan_order(s, "2027-01-04", UP))

    def test_sell_next_month_when_below_sma(self):
        s = fresh()
        core.apply_fill(s, "2026-12-01", "buy", 0.099, 100.0)
        s["last_decision_month"] = "2026-12"
        self.assertEqual(core.plan_order(s, "2027-01-04", DOWN), {"side": "sell", "qty": 0.099})

    def test_too_little_data_does_not_consume_month(self):
        s = fresh()
        self.assertIsNone(core.plan_order(s, "2026-12-01", [100.0] * 50))
        self.assertIsNone(s["last_decision_month"])
        self.assertTrue(s["notes"])

    def test_skip_buy_below_min_notional(self):
        s = fresh()
        s["cash"] = 2.0
        self.assertIsNone(core.plan_order(s, "2026-12-01", UP))


class LedgerTest(unittest.TestCase):
    def test_start_and_benchmark(self):
        s = fresh()
        self.assertAlmostEqual(s["capital_usd"], 11.0)
        self.assertAlmostEqual(s["fee_usd"], 1.1)
        self.assertAlmostEqual(s["benchmark"]["shares"], 0.099)
        self.assertAlmostEqual(s["benchmark"]["fees_paid"], 1.1)

    def test_buy_sell_cycle_with_fees(self):
        s = fresh()
        core.apply_fill(s, "2026-12-01", "buy", 0.099, 100.0)
        self.assertAlmostEqual(s["cash"], 0.0)
        e = core.record_day(s, "2026-12-02", 110.0)
        self.assertAlmostEqual(e["bot"], 10.89)
        self.assertAlmostEqual(e["bench"], 10.89)
        core.apply_fill(s, "2027-01-04", "sell", 0.099, 120.0)
        self.assertAlmostEqual(s["cash"], 10.78)
        self.assertEqual(s["shares"], 0.0)
        self.assertAlmostEqual(s["fees_paid"], 2.2)
        self.assertEqual(len(s["orders"]), 2)

    def test_record_day_once_per_date(self):
        s = fresh()
        core.record_day(s, "2026-12-01", 100.0)
        core.record_day(s, "2026-12-01", 101.0)
        self.assertEqual(len(s["history"]), 1)
        self.assertEqual(s["last_run"], "2026-12-01")

    def test_max_drawdown(self):
        self.assertAlmostEqual(core.max_drawdown([10, 12, 9, 11, 6, 8]), 0.5)
        self.assertEqual(core.max_drawdown([1, 2, 3]), 0.0)


class ReportTest(unittest.TestCase):
    def test_report_fields(self):
        s = fresh()
        core.apply_fill(s, "2026-12-01", "buy", 0.099, 100.0)
        core.record_day(s, "2026-12-01", 100.0)
        core.record_day(s, "2026-12-31", 90.0)
        md = render(s)
        for needle in [
            "Spielgeld",
            "garantieren nichts",
            "Letzter erfolgreicher Lauf: **2026-12-31**",
            "seit 30 Tagen",
            "Startkapital: 10,00 €",
            "Depotwert",
            "Gebühren gesamt | 1,00 € | 1,00 €",
            "Anzahl Orders | 1 | 1",
            "Größter Zwischenverlust | -10,0 % | -10,0 %",
            "Veränderung seit Start",
            "| 2026-12-01 | Kauf |",
        ]:
            self.assertIn(needle, md)

    def test_report_without_history(self):
        self.assertIn("Noch keine Tageswerte", render(fresh()))


if __name__ == "__main__":
    unittest.main()
