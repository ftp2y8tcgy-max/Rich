import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import daten  # noqa: E402
import engine  # noqa: E402
from skill_bruecke import FLAT_SLOT, tm  # noqa: E402


def tsla():
    sitzungen, quelle, sym = daten.sitzungen("TSLA", offline=True, log=lambda *_: None)
    return engine.Markt(sym, sitzungen, quelle)


def rennen_mit(markt, laeufe=True):
    r = engine.Rennen([markt])
    if laeufe:
        r.steuern("start")
    return r


class SkillTreueTest(unittest.TestCase):
    """Die Engine muss auf echten Tagen genau die Trades von tm.history_replay machen."""

    def test_gleiche_trades_wie_history_replay(self):
        markt = tsla()
        self.assertGreaterEqual(len(markt.echt), 50)
        with mock.patch.object(engine, "LETZTER_EINSTIEG", FLAT_SLOT):
            r = rennen_mit(markt)
            for _ in range(len(markt.echt) * (FLAT_SLOT + 1)):
                r.schritt()
        for bot in r.bots:
            erwartet = tm.history_replay(markt.echt, bot.regel, FLAT_SLOT)["trades"]
            mit_ausgang = [t for t in erwartet]
            self.assertEqual(len(bot.trades), len(mit_ausgang), bot.profil["name"])
            for ist, soll in zip(bot.trades, mit_ausgang):
                self.assertEqual(ist["tag"], soll["date"])
                self.assertAlmostEqual(ist["einstieg"], soll["entry"])
                self.assertAlmostEqual(ist["stop"], soll["stop"])
                self.assertAlmostEqual(ist["ziel"], soll["target"])
                grund = {"target": "Ziel", "stop": "Stop", "close": "15:55"}[soll["outcome"]]
                self.assertEqual(ist["grund"], grund)
                self.assertAlmostEqual(ist["r"], soll["R"], places=2)

    def test_vergleich_hat_trades(self):
        markt = tsla()
        for profil in engine.PROFILE:
            regel = {k: profil[k] for k in ("or_minutes", "stop_rule", "target_r", "stop_pct") if k in profil}
            self.assertGreater(tm.history_replay(markt.echt, regel, FLAT_SLOT)["triggered"], 10, profil["name"])


class RennenTest(unittest.TestCase):
    def test_25_bots_fuenf_profile(self):
        r = engine.Rennen([tsla()] * 5)
        self.assertEqual(len(r.bots), 25)
        self.assertEqual(len({b.wallet_id for b in r.bots}), 25)
        self.assertEqual({b.profil["name"] for b in r.bots}, {p["name"] for p in engine.PROFILE})

    def test_pausiert_kein_neuer_einstieg(self):
        r = rennen_mit(tsla(), laeufe=False)
        for _ in range(3 * (FLAT_SLOT + 1)):
            r.schritt()
        self.assertTrue(all(not b.trades and b.wert == 10 for b in r.bots))

    def test_simulierte_tage_nach_echten(self):
        markt = tsla()
        text, echt, kerzen = markt.tag(len(markt.echt) + 2)
        self.assertFalse(echt)
        self.assertTrue(text.startswith("Sim-Tag 3"))
        self.assertEqual(len(kerzen), 78)
        self.assertTrue(all(k["l"] <= min(k["o"], k["c"]) + 1e-9 and k["h"] >= max(k["o"], k["c"]) - 1e-9
                            for k in kerzen))
        # reproduzierbar
        self.assertEqual(markt.tag(len(markt.echt) + 2)[2][10]["c"], tsla().tag(len(markt.echt) + 2)[2][10]["c"])

    def test_pleite_und_ziel(self):
        r = rennen_mit(tsla())
        bot = r.bots[0]
        bot.bargeld = 0.05
        r.schritt()
        self.assertEqual(bot.status, engine.PLEITE)
        bot2 = r.bots[1]
        bot2.position = {"einstieg": 100, "stop": 90, "ziel": 110, "anteile": 20, "kerze": 0, "zeit": "09:30",
                         "tag": "x", "einsatz": 2000.0, "spanne": [0, 0]}
        bot2.bargeld = 0
        kerzen = [{"start": "09:35", "o": 105, "h": 111, "l": 104, "c": 110}]
        ereig = []
        bot2.kerze(0, kerzen, "x", ereig)
        self.assertEqual(bot2.status, engine.ZIEL_ERREICHT)
        self.assertTrue(any(a == "ziel" for a, _, _ in ereig))

    def test_reset_und_schnappschuss(self):
        r = rennen_mit(tsla())
        for _ in range(200):
            r.schritt()
        s = r.schnappschuss()
        self.assertEqual(len(s["bots"]), 5)
        self.assertGreater(s["seq"], 0)
        r.steuern("reset")
        s = r.schnappschuss()
        self.assertEqual(s["rennen"], 2)
        self.assertEqual(s["gesamt"], 50.0)
        self.assertEqual(s["tag"], 1)


if __name__ == "__main__":
    unittest.main()
