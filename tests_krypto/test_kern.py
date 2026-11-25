import json
import unittest

from krypto import depot as d
from krypto import strategien as s


def reihe(start, schritte):
    """Kursreihe: start, dann multiplikative Schritte."""
    werte = [start]
    for f in schritte:
        werte.append(werte[-1] * f)
    return werte


class DepotTest(unittest.TestCase):
    def test_kauf_und_verkauf_mit_gebuehr(self):
        dep = d.neues_depot("x", "t0")
        d.umschichten(dep, "BTC", {"BTC": 100.0})
        self.assertAlmostEqual(dep["menge"], 9.99 / 100.0)
        self.assertAlmostEqual(dep["gebuehren"], 0.01)
        self.assertEqual(dep["orders"], 1)
        d.umschichten(dep, None, {"BTC": 200.0})
        erloes = 9.99 / 100.0 * 200.0
        self.assertAlmostEqual(dep["bargeld"], erloes * 0.999)
        self.assertAlmostEqual(dep["gebuehren"], 0.01 + erloes * 0.001)
        self.assertEqual(dep["orders"], 2)

    def test_keine_order_ohne_wechsel(self):
        dep = d.neues_depot("x", "t0")
        d.umschichten(dep, "ETH", {"ETH": 10.0})
        d.umschichten(dep, "ETH", {"ETH": 12.0})
        self.assertEqual(dep["orders"], 1)

    def test_wechsel_coin_zwei_orders(self):
        dep = d.neues_depot("x", "t0")
        d.umschichten(dep, "ETH", {"ETH": 10.0, "SOL": 5.0})
        d.umschichten(dep, "SOL", {"ETH": 10.0, "SOL": 5.0})
        self.assertEqual(dep["orders"], 3)
        self.assertEqual(dep["coin"], "SOL")
        self.assertAlmostEqual(d.wert(dep, {"SOL": 5.0}), 10.0 * 0.999 ** 3)

    def test_ziel_erreicht_bleibt(self):
        dep = d.neues_depot("x", "t0")
        d.umschichten(dep, "SOL", {"SOL": 1.0})
        d.bewerten(dep, {"SOL": 150.0}, "t1")
        self.assertEqual(dep["status"], d.ZIEL_ERREICHT)
        self.assertEqual(dep["ziel_zeit"], "t1")
        d.bewerten(dep, {"SOL": 50.0}, "t2")
        d.bewerten(dep, {"SOL": 200.0}, "t3")
        self.assertEqual(dep["ziel_zeit"], "t1")

    def test_pleite_handelt_nicht_mehr(self):
        dep = d.neues_depot("x", "t0")
        d.umschichten(dep, "SOL", {"SOL": 100.0})
        d.bewerten(dep, {"SOL": 5.0}, "t1")
        self.assertEqual(dep["status"], d.BANKROTT)
        self.assertEqual(dep["pleite_zeit"], "t1")
        orders = dep["orders"]
        d.umschichten(dep, None, {"SOL": 5.0})
        d.umschichten(dep, "BTC", {"SOL": 5.0, "BTC": 1.0})
        self.assertEqual(dep["orders"], orders)
        self.assertEqual(dep["coin"], "SOL")

    def test_max_drawdown(self):
        dep = d.neues_depot("x", "t0")
        d.umschichten(dep, "BTC", {"BTC": 10.0})
        d.bewerten(dep, {"BTC": 20.0}, "t1")
        d.bewerten(dep, {"BTC": 15.0}, "t2")
        d.bewerten(dep, {"BTC": 18.0}, "t3")
        self.assertAlmostEqual(dep["max_drawdown"], 0.25)

    def test_json_rundreise(self):
        dep = d.neues_depot("x", "t0")
        d.umschichten(dep, "BTC", {"BTC": 10.0})
        self.assertEqual(json.loads(json.dumps(dep)), dep)


class StrategieTest(unittest.TestCase):
    def kurse(self, btc, eth, sol):
        return {"BTC": btc, "ETH": eth, "SOL": sol}

    def test_momentum_waehlt_staerksten(self):
        k = self.kurse(reihe(100, [1.001] * 30), reihe(100, [1.003] * 30), reihe(100, [0.999] * 30))
        self.assertEqual(s.momentum_rotation(k), "ETH")

    def test_momentum_bargeld_wenn_alle_fallen(self):
        k = self.kurse(*(reihe(100, [0.99] * 30) for _ in range(3)))
        self.assertIsNone(s.momentum_rotation(k))

    def test_momentum_zu_wenig_daten(self):
        k = self.kurse(*(reihe(100, [1.01] * 10) for _ in range(3)))
        self.assertIsNone(s.momentum_rotation(k))

    def test_trend_waehlt_groessten_abstand(self):
        k = self.kurse(reihe(100, [1.001] * 60), reihe(100, [0.99] * 60), reihe(100, [1.004] * 60))
        self.assertEqual(s.trendfolge(k), "SOL")

    def test_trend_bargeld_unter_durchschnitt(self):
        k = self.kurse(*(reihe(100, [0.995] * 60) for _ in range(3)))
        self.assertIsNone(s.trendfolge(k))

    def test_btc_halten(self):
        self.assertEqual(s.btc_halten({}), "BTC")

    def test_reproduzierbar(self):
        k = self.kurse(reihe(100, [1.001, 0.998] * 30), reihe(50, [1.002, 0.999] * 30), reihe(20, [0.997, 1.004] * 30))
        for f in s.REGEL_STRATEGIEN.values():
            self.assertEqual(f(k), f(json.loads(json.dumps(k))))

    def test_szenario_orders_und_werte(self):
        # 30 Stunden ETH steigt, dann 30 Stunden fällt alles: Momentum kauft ETH, verkauft danach.
        btc = reihe(100, [1.0] * 30 + [0.99] * 30)
        eth = reihe(100, [1.01] * 30 + [0.99] * 30)
        sol = reihe(100, [1.0] * 30 + [0.99] * 30)
        dep = d.neues_depot("Momentum-Rotation", "t0")
        for i in range(25, 61):
            k = self.kurse(btc[: i + 1], eth[: i + 1], sol[: i + 1])
            preise = {c: k[c][-1] for c in k}
            d.umschichten(dep, s.momentum_rotation(k), preise)
            d.bewerten(dep, preise, f"t{i}")
        self.assertEqual(dep["orders"], 2)
        self.assertIsNone(dep["coin"])
        # Gekauft bei i=25, verkauft beim ersten Stundenwert, an dem die 24h-Rendite <= 0 ist.
        kauf = eth[25]
        verkauf_i = next(i for i in range(26, 61) if eth[i] / eth[i - 24] - 1 <= 0)
        erwartet = 10 * 0.999 / kauf * eth[verkauf_i] * 0.999
        self.assertAlmostEqual(dep["bargeld"], erwartet)


if __name__ == "__main__":
    unittest.main()
