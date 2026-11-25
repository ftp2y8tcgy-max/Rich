import os
import unittest
import urllib.error
from unittest import mock

from krypto import depot as d
from krypto import ki


def kurse():
    r = [100 * 1.001 ** i for i in range(60)]
    return {"BTC": r, "ETH": [x / 2 for x in r], "SOL": [x / 10 for x in r]}


def antwort(text):
    return lambda nachrichten: text


def schlaegt_fehl(fehler):
    def client(nachrichten):
        raise fehler
    return client


class KiTest(unittest.TestCase):
    def setUp(self):
        self.dep = d.neues_depot("KI-Händler", "t0")

    def test_gueltiger_kauf(self):
        ziel = ki.entscheiden(kurse(), self.dep, "t1", antwort("ENTSCHEIDUNG: kaufen ETH\nBEGRÜNDUNG: Stärkster Trend."))
        self.assertEqual(ziel, "ETH")
        d.umschichten(self.dep, ziel, {c: kurse()[c][-1] for c in kurse()})
        self.assertEqual(self.dep["coin"], "ETH")
        self.assertEqual(self.dep["orders"], 1)
        self.assertEqual(self.dep["letzte_entscheidung"]["begruendung"], "Stärkster Trend.")
        self.assertEqual(self.dep["ki_ausfaelle"], 0)

    def test_verkaufen_und_halten(self):
        self.assertIsNone(ki.entscheiden(kurse(), self.dep, "t1", antwort("entscheidung: Verkaufen\nBegruendung: Risiko.")))
        self.assertEqual(ki.entscheiden(kurse(), self.dep, "t1", antwort("ENTSCHEIDUNG: halten\nBEGRÜNDUNG: abwarten")), ki.HALTEN)
        self.assertEqual(self.dep["ki_ausfaelle"], 0)

    def test_ungueltige_antworten_heissen_halten(self):
        for text in ["Ich kaufe Dogecoin!", "ENTSCHEIDUNG: kaufen DOGE", "", None]:
            self.assertEqual(ki.entscheiden(kurse(), self.dep, "t1", antwort(text)), ki.HALTEN)
        self.assertEqual(self.dep["ki_ausfaelle"], 4)

    def test_ausfaelle_heissen_halten(self):
        fehler = [
            TimeoutError(),
            urllib.error.HTTPError("https://x", 429, "Too Many Requests", {}, None),
            urllib.error.URLError("kein Netz"),
            KeyError("choices"),
        ]
        for f in fehler:
            self.assertEqual(ki.entscheiden(kurse(), self.dep, "t1", schlaegt_fehl(f)), ki.HALTEN)
        self.assertEqual(self.dep["ki_ausfaelle"], 4)
        self.assertTrue(self.dep["letzte_entscheidung"]["begruendung"].startswith("Ausfall"))

    def test_http_code_im_bericht(self):
        f = urllib.error.HTTPError("https://x", 401, "Unauthorized", {}, None)
        ki.entscheiden(kurse(), self.dep, "t1", schlaegt_fehl(f))
        self.assertEqual(self.dep["letzte_entscheidung"]["begruendung"], "Ausfall: HTTP 401")

    def test_fehlender_schluessel_heisst_halten(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(ki.entscheiden(kurse(), self.dep, "t1"), ki.HALTEN)
        self.assertEqual(self.dep["ki_ausfaelle"], 1)
        self.assertIn("kein LLM_API_KEY", self.dep["letzte_entscheidung"]["begruendung"])

    def test_schluessel_nie_im_depot(self):
        geheim = "test-schluessel-nicht-echt-123"
        with mock.patch.dict(os.environ, {"LLM_API_KEY": geheim, "LLM_BASE_URL": "http://127.0.0.1:9"}):
            ki.entscheiden(kurse(), self.dep, "t1")
        self.assertNotIn(geheim, repr(self.dep))
        self.assertEqual(self.dep["ki_ausfaelle"], 1)

    def test_eingabe_enthaelt_kennzahlen(self):
        text = ki.eingabe(kurse(), self.dep)
        for teil in ["BTC:", "ETH:", "SOL:", "24h", "48h-Schnitt", "Bargeld"]:
            self.assertIn(teil, text)


if __name__ == "__main__":
    unittest.main()
