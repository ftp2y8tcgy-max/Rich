"""Echte 5-Minuten-Kurse: Yahoo über die Time Machine des Skill-Pakets, mit Zwischenspeicher.

Reihenfolge je Aktie: frischer Cache (< 12 h) → Yahoo (60 Tage, 5 Minuten) → alter Cache →
mitgelieferte TSLA-Daten (echte Kerzen bis 19.10.2026 aus dem day-trader-skill).
"""

import datetime
import gzip
import os
import time

from skill_bruecke import tm

HIER = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HIER, "cache")
MITGELIEFERT = os.path.join(HIER, "daten", "TSLA-60d5m.json.gz")
CACHE_STUNDEN = 12


def _cache_pfad(sym):
    return os.path.join(CACHE, f"{sym.upper()}-60d5m.json.gz")


def _lesen(pfad):
    with gzip.open(pfad, "rt", encoding="utf-8") as f:
        return f.read()


def rohdaten(sym, offline=False, log=print):
    """Liefert (Yahoo-JSON-Text, Quelle, Symbol der Daten)."""
    sym = sym.upper()
    pfad = _cache_pfad(sym)
    if os.path.exists(pfad) and (offline or time.time() - os.path.getmtime(pfad) < CACHE_STUNDEN * 3600):
        return _lesen(pfad), "Cache", sym
    if not offline:
        try:
            text = tm.fetch_chart(sym)
            tm.chart_result(text, sym)  # prüft, dass Yahoo echte Daten geliefert hat
            os.makedirs(CACHE, exist_ok=True)
            with gzip.open(pfad, "wt", encoding="utf-8") as f:
                f.write(text)
            time.sleep(tm.PAUSE)  # höflich zum kostenlosen Endpunkt, wie im Skill
            return text, "Yahoo", sym
        except tm.TMError as fehler:
            log(f"{sym}: Yahoo nicht erreichbar ({fehler})")
    if os.path.exists(pfad):
        return _lesen(pfad), "alter Cache", sym
    log(f"{sym}: keine Daten, nehme die mitgelieferten TSLA-Kerzen")
    return _lesen(MITGELIEFERT), "mitgeliefert", "TSLA"


def sitzungen(sym, offline=False, log=print):
    """Volle Handelstage (je 78 Kerzen), älteste zuerst: [(datum, [kerze, ...]), ...]."""
    text, quelle, daten_sym = rohdaten(sym, offline, log)
    ergebnis = tm.chart_result(text, daten_sym)
    jetzt = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    _, kerzen, _ = tm.parse_bars(ergebnis, jetzt)
    tage = tm.split_sessions(kerzen)
    voll, _ = tm.full_sessions(tage, before="9999-12-31")
    return voll, quelle, daten_sym
