import json
import os
import tempfile
import unittest
from unittest import mock

from krypto import kurse as kurs_api
from krypto import lauf


def kurse(n, faktor=1.002):
    r = [100 * faktor ** i for i in range(n)]
    return {"BTC": r, "ETH": [x / 2 * (1.001 ** i) for i, x in enumerate(r)], "SOL": [x / 10 for x in r]}


def ki_antwort(text):
    return lambda nachrichten: text


class LaufTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.daten = os.path.join(self.tmp.name, "daten")
        self.kursdatei = os.path.join(self.tmp.name, "kurse.json")

    def tearDown(self):
        self.tmp.cleanup()

    def lauf(self, k, zeit, ki=ki_antwort("ENTSCHEIDUNG: kaufen SOL\nBEGRÜNDUNG: Test.")):
        with open(self.kursdatei, "w") as f:
            json.dump(k, f)
        return lauf.main(["--daten", self.daten, "--kurse-datei", self.kursdatei, "--zeit", zeit], ki_client=ki)

    def zustand(self):
        with open(os.path.join(self.daten, "zustand.json")) as f:
            return json.load(f)

    def test_zwei_laeufe_setzen_auf_zustand_auf(self):
        self.assertEqual(self.lauf(kurse(60), "2026-11-25T10:00:00+00:00"), 0)
        erster = self.zustand()
        self.assertEqual(erster["depots"]["BTC halten (Vergleich)"]["coin"], "BTC")
        self.assertEqual(erster["depots"]["KI-Händler"]["coin"], "SOL")
        self.assertEqual(self.lauf(kurse(61), "2026-11-25T11:00:00+00:00"), 0)
        zweiter = self.zustand()
        self.assertEqual(zweiter["start"], "2026-11-25T10:00:00+00:00")
        self.assertEqual(zweiter["letzter_lauf"], "2026-11-25T11:00:00+00:00")
        self.assertEqual(zweiter["depots"]["BTC halten (Vergleich)"]["orders"], 1)
        with open(os.path.join(self.daten, "verlauf.csv")) as f:
            zeilen = f.read().strip().splitlines()
        self.assertEqual(len(zeilen), 3)
        self.assertTrue(zeilen[0].startswith("zeit,rennen,Momentum-Rotation"))

    def test_bericht_enthaelt_alle_angaben(self):
        self.lauf(kurse(60), "2026-11-25T10:00:00+00:00")
        self.lauf(kurse(61), "2026-11-26T13:00:00+00:00")
        with open(os.path.join(self.daten, "KRYPTO-REPORT.md")) as f:
            b = f.read()
        for teil in [
            "Spielgeld", "garantieren nichts", "Rangliste", "bis 1.000 €", "Status",
            "Gebühren gesamt", "Orders:", "Größter Zwischenverlust", "Rennen Nr. 1",
            "1 Tage, 3 Stunden", "Letzter Lauf:** 26.11.2026 14:00",
            "Letzte KI-Entscheidung: kaufen SOL", "KI-Ausfälle", "Slippage",
            "Momentum-Rotation", "Trendfolge", "KI-Händler", "BTC halten (Vergleich)",
        ]:
            self.assertIn(teil, b, teil)

    def test_status_ziel_und_pleite_im_bericht(self):
        self.lauf(kurse(60), "2026-11-25T10:00:00+00:00")
        k = kurse(60)
        k["SOL"] = k["SOL"][:-1] + [k["SOL"][-1] * 200]
        self.lauf(k, "2026-11-25T11:00:00+00:00", ki=ki_antwort("ENTSCHEIDUNG: halten"))
        k["SOL"] = k["SOL"][:-1] + [k["SOL"][-1] / 20000]
        self.lauf(k, "2026-11-25T12:00:00+00:00", ki=ki_antwort("ENTSCHEIDUNG: halten"))
        z = self.zustand()["depots"]["KI-Händler"]
        self.assertEqual(z["ziel_zeit"], "2026-11-25T11:00:00+00:00")
        self.assertEqual(z["status"], "pleite")
        with open(os.path.join(self.daten, "KRYPTO-REPORT.md")) as f:
            b = f.read()
        self.assertIn("pleite am 25.11.2026 13:00", b)

    def test_neues_rennen(self):
        self.lauf(kurse(60), "2026-11-25T10:00:00+00:00")
        self.lauf(kurse(61), "2026-11-25T11:00:00+00:00")
        with open(self.kursdatei, "w") as f:
            json.dump(kurse(62), f)
        lauf.main(["--daten", self.daten, "--kurse-datei", self.kursdatei, "--zeit", "2026-11-25T12:00:00+00:00", "--neues-rennen"],
                  ki_client=ki_antwort("ENTSCHEIDUNG: halten"))
        z = self.zustand()
        self.assertEqual(z["rennen"], 2)
        self.assertEqual(z["start"], "2026-11-25T12:00:00+00:00")
        self.assertEqual(z["depots"]["KI-Händler"]["orders"], 0)
        self.assertEqual(z["depots"]["KI-Händler"]["ki_ausfaelle"], 0)
        self.assertEqual(z["depots"]["BTC halten (Vergleich)"]["orders"], 1)
        with open(os.path.join(self.daten, "verlauf.csv")) as f:
            self.assertTrue(f.read().strip().splitlines()[-1].split(",")[1] == "2")

    def test_kursfehler_aendert_nichts(self):
        self.lauf(kurse(60), "2026-11-25T10:00:00+00:00")
        vorher = {n: open(os.path.join(self.daten, n)).read() for n in os.listdir(self.daten)}
        with mock.patch.object(kurs_api, "holen", side_effect=OSError("kein Netz")):
            code = lauf.main(["--daten", self.daten, "--zeit", "2026-11-25T11:00:00+00:00"], ki_client=ki_antwort("x"))
        self.assertEqual(code, 1)
        nachher = {n: open(os.path.join(self.daten, n)).read() for n in os.listdir(self.daten)}
        self.assertEqual(vorher, nachher)

    def test_ki_ausfall_haelt(self):
        def kaputt(nachrichten):
            raise TimeoutError()
        self.lauf(kurse(60), "2026-11-25T10:00:00+00:00", ki=kaputt)
        z = self.zustand()["depots"]["KI-Händler"]
        self.assertIsNone(z["coin"])
        self.assertEqual(z["ki_ausfaelle"], 1)


class KrakenTest(unittest.TestCase):
    def test_schlusskurse(self):
        antwort = {"error": [], "result": {"XXBTZEUR": [[1, "1", "2", "0.5", "1.5", "1", "3", 4], [2, "1.5", "2", "1", "1.75", "1", "3", 4]], "last": 2}}
        self.assertEqual(kurs_api.schlusskurse(antwort), [1.5, 1.75])

    def test_fehler_wird_gemeldet(self):
        with self.assertRaises(RuntimeError):
            kurs_api.schlusskurse({"error": ["EQuery:Unknown asset pair"], "result": {}})

    def test_paare(self):
        self.assertEqual(set(kurs_api.PAARE), {"BTC", "ETH", "SOL"})


if __name__ == "__main__":
    unittest.main()
