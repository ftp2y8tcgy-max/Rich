"""Öffentliche Kraken-REST-API (nur Lesen, kein Schlüssel). Keine Order-Endpunkte."""

import json
import time
import urllib.error
import urllib.parse
import urllib.request

BASIS = "https://api.kraken.com/0/public/"
UA = "krypto-scanner/2.0 (+https://github.com/ftp2y8tcgy-max/Rich)"
PAUSE = 1.1          # Sekunden zwischen Anfragen: höflich zum öffentlichen Limit
ZEITLIMIT = 20


class KrakenFehler(Exception):
    pass


_letzte_anfrage = [0.0]


def _get(pfad, params=None, versuche=3):
    url = BASIS + pfad + ("?" + urllib.parse.urlencode(params) if params else "")
    for versuch in range(versuche):
        warten = _letzte_anfrage[0] + PAUSE - time.monotonic()
        if warten > 0:
            time.sleep(warten)
        _letzte_anfrage[0] = time.monotonic()
        try:
            anfrage = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(anfrage, timeout=ZEITLIMIT) as r:
                daten = json.load(r)
        except (urllib.error.URLError, TimeoutError, ValueError) as fehler:
            if versuch == versuche - 1:
                raise KrakenFehler(f"{pfad}: {fehler}")
            time.sleep(3)
            continue
        fehler = daten.get("error") or []
        if any("Rate limit" in f or "Too many" in f for f in fehler) and versuch < versuche - 1:
            time.sleep(6)
            continue
        if fehler:
            raise KrakenFehler(f"{pfad}: {fehler}")
        return daten["result"]
    raise KrakenFehler(f"{pfad}: keine Antwort")


def asset_pairs():
    return _get("AssetPairs")


def ticker():
    """Kurse aller handelbaren Paare in einer Anfrage."""
    return _get("Ticker")


def ohlc(pair, interval=60, since=None):
    """Kerzen als [(zeit, schluss), ...], älteste zuerst. Die letzte Kerze läuft noch."""
    params = {"pair": pair, "interval": interval}
    if since:
        params["since"] = int(since)
    ergebnis = _get("OHLC", params)
    reihe = next(v for k, v in ergebnis.items() if k != "last")
    return [(int(z[0]), float(z[4])) for z in reihe]
