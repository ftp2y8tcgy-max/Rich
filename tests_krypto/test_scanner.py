import json
import math
import os
import tempfile
import unittest

from krypto import backtest, bericht, depot as dp, lauf, markt, strategien, universum

H = 3600
T0 = 1_780_000_000 // H * H


def paar(base, quote="ZEUR", ws=None, ordermin="0.0001", costmin="0.5", lot=8):
    return {"base": base, "quote": quote, "wsname": ws or f"{base}/EUR", "status": "online",
            "ordermin": ordermin, "costmin": costmin, "lot_decimals": lot}


def tick(preis, umsatz_stueck=1e6, spread=0.001):
    return {"a": [str(preis * (1 + spread / 2))], "b": [str(preis * (1 - spread / 2))], "c": [str(preis)],
            "v": ["0", str(umsatz_stueck)], "p": ["0", str(preis)]}


class FakeKraken:
    """Nachbau der öffentlichen Kraken-API mit erfundenen Stundenkursen."""

    def __init__(self, kurse):
        self.kurse = kurse          # pair -> funktion(stunde) -> preis
        self.jetzt = T0
        self.anfragen = 0
        self.paare = {"XXBTZEUR": paar("XXBT", ws="XBT/EUR", ordermin="0.00005"),
                      "XETHZEUR": paar("XETH", ws="ETH/EUR", ordermin="0.002"),
                      "SOLEUR": paar("SOL", ordermin="0.02"),
                      "MOONEUR": paar("MOON", ordermin="1", lot=0),
                      "USDTEUR": paar("USDT"), "XBTUSD": paar("XXBT", quote="ZUSD", ws="XBT/USD"),
                      "DUENNEUR": paar("DUENN")}

    def preis(self, pair, t):
        return self.kurse[pair]((t - T0) // H)

    def asset_pairs(self):
        self.anfragen += 1
        return self.paare

    def ticker(self):
        self.anfragen += 1
        t = {p: tick(self.preis(p, self.jetzt)) for p in self.kurse}
        t["USDTEUR"] = tick(0.92)
        t["XBTUSD"] = tick(70000)
        t["DUENNEUR"] = tick(1.0, umsatz_stueck=10)       # zu wenig Umsatz
        return t

    def ohlc(self, pair, interval=60, since=None):
        self.anfragen += 1
        ende = self.jetzt // H * H
        start = max(ende - 719 * H, since or 0)
        return [(t, self.preis(pair, t)) for t in range(start, ende + 1, H)]


def standard_kurse(mond=lambda h: 1.0 + 0.0 * h):
    return {"XXBTZEUR": lambda h: 60000 * (1 + 0.0002 * math.sin(h / 5)),
            "XETHZEUR": lambda h: 2500 * (1 + 0.003 * math.sin(h / 3)),
            "SOLEUR": lambda h: 150 * (1 + 0.004 * math.sin(h / 7)),
            "MOONEUR": mond}


class UniversumTest(unittest.TestCase):
    def test_nur_liquide_euro_ohne_stablecoins(self):
        api = FakeKraken(standard_kurse())
        uni = universum.waehlen(api.asset_pairs(), api.ticker())
        self.assertEqual(set(uni), {"XXBTZEUR", "XETHZEUR", "SOLEUR", "MOONEUR"})
        self.assertEqual(uni["XXBTZEUR"]["coin"], "BTC")
        self.assertEqual(list(uni)[0], "XXBTZEUR")        # nach Umsatz sortiert


class MarktTest(unittest.TestCase):
    def test_laufende_kerze_und_luecken(self):
        s = {}
        markt.einpflegen(s, "X", [(T0, 1.0), (T0 + 2 * H, 3.0), (T0 + 3 * H, 4.0)], jetzt=T0 + 3 * H + 60)
        self.assertEqual(s["X"], {"t0": T0, "c": [1.0, 1.0, 3.0]})   # Lücke gefüllt, laufende Kerze fehlt
        markt.einpflegen(s, "X", [(T0 + 3 * H, 4.0)], jetzt=T0 + 4 * H)
        self.assertEqual(s["X"]["c"], [1.0, 1.0, 3.0, 4.0])


class StrategieTest(unittest.TestCase):
    def matrix(self):
        n = 200
        return {"A": [100 * 1.004 ** i for i in range(n)], "B": [100.0] * n, "BTC": [100 * 1.001 ** i for i in range(n)]}

    def test_kein_blick_in_die_zukunft(self):
        m = self.matrix()
        kosten = {p: 0.005 for p in m}
        for v in strategien.VARIANTEN:
            vorher = strategien.ranglisten(v, m, kosten, "BTC")
            m2 = {p: c[:150] + [c[149] * 0.5] * 50 for p, c in m.items()}     # Zukunft ab 150 verändert
            nachher = strategien.ranglisten(v, m2, kosten, "BTC")
            self.assertEqual(vorher[:150], nachher[:150], v["id"])

    def test_huerde_nach_kosten(self):
        m = self.matrix()
        listen = strategien.ranglisten(strategien.NACH_ID["mom24"], m, {p: 0.005 for p in m}, "BTC")
        self.assertEqual(listen[150][0][1], "A")
        self.assertNotIn("B", [p for _, p in listen[150]])
        teuer = strategien.ranglisten(strategien.NACH_ID["mom24"], m, {p: 0.05 for p in m}, "BTC")
        self.assertEqual(teuer[150], [])          # Anstieg deckt 4 × 5 % Kosten nicht

    def test_wechsel_hysterese(self):
        self.assertEqual(strategien.ziel([(3.0, "A"), (2.8, "B")], "B"), "B")
        self.assertEqual(strategien.ziel([(3.6, "A"), (2.8, "B")], "B"), "A")
        self.assertEqual(strategien.ziel([(3.0, "A")], "B"), "A")
        self.assertIsNone(strategien.ziel([], "B"))


class BacktestTest(unittest.TestCase):
    def test_kosten_werden_abgezogen(self):
        m = {"A": [100.0] * 50}
        listen = [[(1.0, "A")] if i % 2 else [] for i in range(50)]     # erzwingt Kauf/Verkauf im Wechsel
        wert, _, _, trades, _ = backtest.simulieren(listen, m, {"A": 0.01}, 1, 50)
        self.assertEqual(trades, 49)              # Stunde 1, 3, …, 49 kaufen, 2, 4, …, 48 verkaufen
        self.assertAlmostEqual(wert, 0.99 ** 49)

    def test_trailing_stop(self):
        c = [100.0, 100, 110, 120, 100, 100]
        listen = [[(1.0, "A")] for _ in c]
        wert, gehalten, _, trades, _ = backtest.simulieren(listen, {"A": c}, {"A": 0.0}, 1, 5)
        self.assertEqual(trades, 2)                # Kauf, dann Stop bei 100 < 120 × 0,9
        self.assertAlmostEqual(wert, 1.0)

    def test_walk_forward_und_auswahl(self):
        n = 720
        m = {"A": [100 * (1.003 ** i) for i in range(n)], "BTC": [100.0 + (i % 5) for i in range(n)]}
        kosten = {p: 0.005 for p in m}
        listen = backtest.alle_ranglisten(m, kosten, "BTC")
        tab = backtest.auswahl(listen, m, kosten, n)
        self.assertNotIn(tab[0]["id"], ("bar", "btc"))
        wf = backtest.walk_forward(listen, m, kosten, "BTC")
        self.assertGreater(wf["ergebnis"], wf["btc"])
        self.assertEqual(wf["tage"], math.ceil((n - 337) / 24))


class DepotTest(unittest.TestCase):
    def test_kraken_mindestorder_und_gebuehr(self):
        d = dp.neues_depot(10.0)
        trade, grund = dp.kaufen(d, "MOONEUR", {"coin": "MOON", "ordermin": 1, "costmin": 0.5, "lot_decimals": 0},
                                 20.0, "t")
        self.assertIsNone(trade)
        self.assertIn("Mindestorder", grund)
        trade, _ = dp.kaufen(d, "XXBTZEUR", {"coin": "BTC", "ordermin": 0.00005, "costmin": 0.5, "lot_decimals": 8},
                             60000.0, "t")
        self.assertAlmostEqual(trade["menge"], 0.00016600)
        self.assertAlmostEqual(trade["gebuehr"], 0.000166 * 60000 * 0.004)
        v = dp.verkaufen(d, 59000.0, "t2", "Test")
        self.assertAlmostEqual(v["ergebnis"], 0.000166 * 59000 * 0.996 - 0.000166 * 60000 * 1.004)
        self.assertAlmostEqual(d["bargeld"], 10 - 0.000166 * 60000 * 1.004 + 0.000166 * 59000 * 0.996)


class LaufTest(unittest.TestCase):
    def test_viele_laeufe_mit_rakete_und_absturz(self):
        # MOON steigt ab Stunde 750 kräftig, stürzt bei Stunde 790 ab
        def mond(h):
            if h < 750:
                return 1.0 + 0.001 * math.sin(h)
            if h < 790:
                return 1.0 * 1.02 ** (h - 750)
            return 1.02 ** 40 * 0.7
        api = FakeKraken(standard_kurse(mond))
        api.paare["MOONEUR"]["ordermin"] = "0.1"
        api.paare["MOONEUR"]["lot_decimals"] = 2
        api.jetzt = T0 + 740 * H + 120
        z = lauf.neuer_zustand(api.jetzt, 10.0)
        lauf.schritt(z, api, api.jetzt)
        self.assertEqual(len(z["markt"]), 4)                # erster Lauf lädt alle Coins
        self.assertTrue(z["btc_depot"]["pair"])
        anfragen_vorher = api.anfragen
        for _ in range(12 * 60):                             # 60 Stunden in 5-Minuten-Schritten
            api.jetzt += 300
            lauf.schritt(z, api, api.jetzt)
        self.assertLess((api.anfragen - anfragen_vorher) / (12 * 60), 1.6)   # höflich: meist nur der Ticker
        gekauft = [t for t in z["trades"] if t["art"] == "Kauf"]
        self.assertTrue(any(t["coin"] == "MOON" for t in gekauft), z["ereignisse"][-5:])
        stops = [t for t in z["trades"] if t["art"] == "Verkauf" and t["grund"].startswith("Stop")]
        self.assertTrue(stops)
        self.assertTrue(z["auswahl"] and z["walk_forward"])
        md = bericht.markdown(z)
        for teil in ("Stand", "Gewählte Strategie", "Walk-Forward", "Echtgeld-Freigabe: 🔴", "Letzte Trades",
                     "Beobachtete Coins (4)"):
            self.assertIn(teil, md)
        self.assertTrue(bericht.svg(z).startswith("<svg"))

    def test_main_speichert_und_neu(self):
        api = FakeKraken(standard_kurse())
        api.jetzt = T0 + 740 * H
        with tempfile.TemporaryDirectory() as tmp:
            import time
            echt = time.time
            time.time = lambda: api.jetzt
            try:
                self.assertEqual(lauf.main(["--daten", tmp], api=api), 0)
                api.jetzt += 300
                self.assertEqual(lauf.main(["--daten", tmp], api=api), 0)
                with open(os.path.join(tmp, "zustand.json")) as f:
                    z = json.load(f)
                self.assertEqual(z["laeufe"], 2)
                self.assertEqual(lauf.main(["--daten", tmp, "--neu", "--startkapital", "50"], api=api), 0)
                with open(os.path.join(tmp, "zustand.json")) as f:
                    z = json.load(f)
                self.assertEqual((z["laeufe"], z["startkapital"]), (1, 50.0))
                self.assertTrue(z["markt"])
                for name in ("KRYPTO-REPORT.md", "verlauf.svg"):
                    self.assertTrue(os.path.exists(os.path.join(tmp, name)))
            finally:
                time.time = echt

    def test_kein_order_endpunkt(self):
        quelltext = "".join(open(os.path.join("krypto", f)).read() for f in os.listdir("krypto") if f.endswith(".py"))
        for verboten in ("AddOrder", "/private/", "API-Sign", "api_secret"):
            self.assertNotIn(verboten, quelltext)


if __name__ == "__main__":
    unittest.main()
