"""Stundenkerzen von Kraken (öffentliche API, ohne Schlüssel, nur Lesen)."""

import json
import urllib.request

KRAKEN_OHLC = "https://api.kraken.com/0/public/OHLC?pair={paar}&interval=60"
PAARE = {"BTC": "XBTEUR", "ETH": "ETHEUR", "SOL": "SOLEUR"}
ZEITLIMIT = 30


def schlusskurse(antwort):
    """Kraken-OHLC-Antwort → Liste der Schlusskurse, älteste zuerst."""
    if antwort.get("error"):
        raise RuntimeError(f"Kraken-Fehler: {antwort['error']}")
    reihen = [v for k, v in antwort["result"].items() if k != "last"]
    if len(reihen) != 1 or not reihen[0]:
        raise RuntimeError("Kraken-Antwort ohne Kerzen")
    return [float(kerze[4]) for kerze in reihen[0]]


def holen():
    kurse = {}
    for coin, paar in PAARE.items():
        anfrage = urllib.request.Request(KRAKEN_OHLC.format(paar=paar), headers={"User-Agent": "krypto-wettrennen"})
        with urllib.request.urlopen(anfrage, timeout=ZEITLIMIT) as antwort:
            kurse[coin] = schlusskurse(json.load(antwort))
    return kurse
