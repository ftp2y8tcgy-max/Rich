"""Tests der Browser-Engine (dashboard/static/engine.js) gegen die Time Machine von day-trader-skill.

Braucht Node.js zum Ausführen von engine.js; ohne Node werden die Tests übersprungen.
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HIER = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HIER))
sys.path.insert(0, os.path.dirname(HIER))

from skill_bruecke import FLAT_SLOT, tm  # noqa: E402


def ipad_modul():
    spec = importlib.util.spec_from_file_location("dtr", os.path.join(REPO, "ipad", "day_trader_rennen.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


DTR = ipad_modul()
PAKET = DTR.daten_paket(["TSLA"] * 5, offline=True, log=lambda *a: None)


def als_sessions(tage):
    """Eingebettete Tage → Format der Time Machine (Liste von (datum, [kerze...]))."""
    return [(d, [{"o": b[0], "h": b[1], "l": b[2], "c": b[3]} for b in k]) for d, k in tage]


@unittest.skipUnless(shutil.which("node"), "Node.js nicht installiert")
class EngineTest(unittest.TestCase):
    def lauf(self, paket, broker, schritte, letzter=None):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(paket, f)
        try:
            args = ["node", os.path.join(HIER, "lauf.js"), f.name, broker, str(schritte)]
            if letzter is not None:
                args.append(str(letzter))
            return json.loads(subprocess.run(args, check=True, capture_output=True, text=True).stdout)
        finally:
            os.unlink(f.name)

    def test_ohne_kosten_gleich_history_replay(self):
        tage = PAKET["aktien"][0]["tage"]
        ergebnis = self.lauf(PAKET, "ideal", len(tage) * (FLAT_SLOT + 1), letzter=FLAT_SLOT)
        sessions = als_sessions(tage)
        for bot in ergebnis["bots"][:5]:
            regel = {k: bot["regel"][k] for k in ("or_minutes", "stop_rule", "target_r", "stop_pct") if k in bot["regel"]}
            soll = tm.history_replay(sessions, regel, FLAT_SLOT)["trades"]
            ist = bot["trades"]
            self.assertEqual(len(ist), len(soll), bot["profil"])
            for a, b in zip(ist, soll):
                self.assertEqual(a["tag"], b["date"])
                self.assertAlmostEqual(a["einstieg"], b["entry"], places=6)
                self.assertAlmostEqual(a["stop"], b["stop"], places=6)
                self.assertAlmostEqual(a["ziel"], b["target"], places=6)
                self.assertEqual({"Ziel": "target", "Stop": "stop", "15:55": "close"}[a["grund"]], b["outcome"])
                self.assertAlmostEqual(a["r"], b["R"], places=2)
        reel = next(b for b in ergebnis["bots"] if b["profil"] == "Reel")
        gruende = [t["grund"] for t in reel["trades"]]
        self.assertEqual((len(gruende), gruende.count("Ziel"), gruende.count("Stop")), (33, 13, 15))

    def test_alpaca_kosten_und_naechster_open(self):
        tage = PAKET["aktien"][0]["tage"]
        ergebnis = self.lauf(PAKET, "alpaca", 20 * (FLAT_SLOT + 1))
        bot = ergebnis["bots"][0]
        self.assertGreater(len(bot["trades"]), 3)
        self.assertGreater(bot["kosten"], 0.05)       # 0,5 % Wechselgebühr + Slippage + SEC/TAF
        for t in bot["trades"]:
            self.assertNotEqual(t["einstieg"], t["plan"])   # Ausführung zum nächsten Open, nicht zum Signal
            self.assertGreater(t["kosten"], 0)
        self.assertTrue(tage)

    def test_neobroker_zu_wenig_fuer_eine_aktie(self):
        ergebnis = self.lauf(PAKET, "neobroker", 3 * (FLAT_SLOT + 1))
        self.assertTrue(all(not b["trades"] for b in ergebnis["bots"]))
        self.assertTrue(any("reichen nicht für 1 Aktie" in e for e in ergebnis["ereignisse"]))
        self.assertAlmostEqual(ergebnis["gesamt"], 250.0)

    def test_luecke_unter_den_stop(self):
        """Echtgeld: öffnet die Kerze unter dem Stop, wird zum Eröffnungskurs verkauft (nicht zum Stop)."""
        k = [[100, 101, 99, 100]] * 3 + [[100, 102.5, 100, 102]] + [[102, 102, 102, 102]] \
            + [[95, 96, 94, 95]] + [[95, 95, 95, 95]] * 72
        paket = {"aktien": [{"sym": "TEST", "quelle": "Test", "tage": [["2026-01-05", k], ["2026-01-06", k]]}] * 5,
                 "fx": {"kurse": {}, "quelle": "Test", "annahme": 1.0}}
        ergebnis = self.lauf(paket, "alpaca", FLAT_SLOT + 1)
        t = ergebnis["bots"][0]["trades"][0]   # Lehrbuch: Signal bei 102, Stop = Mitte 100, Kauf zum Open 102
        self.assertEqual(t["grund"], "Stop (Lücke)")
        self.assertAlmostEqual(t["ausstieg"], 95 * (1 - 0.0005), places=6)
        self.assertLess(t["r"], -1.0)
        ideal = self.lauf(paket, "ideal", FLAT_SLOT + 1)["bots"][0]["trades"][0]
        self.assertEqual(ideal["grund"], "Stop")
        self.assertAlmostEqual(ideal["r"], -1.0)


class PaketTest(unittest.TestCase):
    def test_seite_ist_eigenstaendig(self):
        html = DTR.seite_bauen(PAKET)
        self.assertNotIn("/static/", html)
        self.assertIn("window.DTR_DATEN=", html)
        self.assertNotIn("fetch(", html)
        self.assertEqual(len(PAKET["aktien"]), 5)
        self.assertGreater(len(PAKET["aktien"][0]["tage"]), 50)


if __name__ == "__main__":
    unittest.main()
