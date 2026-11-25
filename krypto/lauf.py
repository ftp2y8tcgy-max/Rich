"""Ein stündlicher Lauf: Kurse holen, alle Strategien handeln lassen, Zustand und Bericht schreiben.

Aufruf: python3 -m krypto.lauf [--daten DIR] [--kurse-datei DATEI] [--zeit ISO]
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

from krypto import bericht, depot as d, ki, kurse as kurs_api
from krypto.strategien import COINS, REGEL_STRATEGIEN

KI_NAME = "KI-Händler"
REIHENFOLGE = ["Momentum-Rotation", "Trendfolge", KI_NAME, "BTC halten (Vergleich)"]


def neues_rennen(zeit, nummer=1):
    return {"rennen": nummer, "start": zeit, "letzter_lauf": zeit, "depots": {n: d.neues_depot(n, zeit) for n in REIHENFOLGE}}


def handeln(zustand, kurse, zeit, ki_client=ki.http_client):
    preise = {c: kurse[c][-1] for c in COINS}
    for name in REIHENFOLGE:
        dep = zustand["depots"][name]
        if dep["status"] != d.BANKROTT:
            if name == KI_NAME:
                ziel = ki.entscheiden(kurse, dep, zeit, ki_client)
            else:
                ziel = REGEL_STRATEGIEN[name](kurse)
            if ziel != ki.HALTEN:
                d.umschichten(dep, ziel, preise)
        d.bewerten(dep, preise, zeit)
    zustand["letzter_lauf"] = zeit
    zustand["preise"] = preise
    return zustand


def _schreiben(pfad, text):
    tmp = pfad + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, pfad)


def speichern(verzeichnis, zustand):
    os.makedirs(verzeichnis, exist_ok=True)
    _schreiben(os.path.join(verzeichnis, "zustand.json"), json.dumps(zustand, ensure_ascii=False, indent=1))
    verlauf = os.path.join(verzeichnis, "verlauf.csv")
    neu = not os.path.exists(verlauf)
    with open(verlauf, "a", encoding="utf-8") as f:
        if neu:
            f.write("zeit,rennen," + ",".join(REIHENFOLGE) + "\n")
        f.write(f"{zustand['letzter_lauf']},{zustand['rennen']}," + ",".join(f"{zustand['depots'][n]['wert']:.4f}" for n in REIHENFOLGE) + "\n")
    _schreiben(os.path.join(verzeichnis, "KRYPTO-REPORT.md"), bericht.erzeugen(zustand))


def laden(verzeichnis):
    pfad = os.path.join(verzeichnis, "zustand.json")
    if not os.path.exists(pfad):
        return None
    with open(pfad, encoding="utf-8") as f:
        return json.load(f)


def main(argv=None, ki_client=ki.http_client):
    p = argparse.ArgumentParser()
    p.add_argument("--daten", default="daten")
    p.add_argument("--kurse-datei", help="Testmodus: Kurse aus JSON-Datei statt von Kraken")
    p.add_argument("--zeit", help="Zeitpunkt (ISO), Standard: jetzt")
    a = p.parse_args(argv)
    zeit = a.zeit or datetime.now(timezone.utc).replace(second=0, microsecond=0).isoformat()
    try:
        if a.kurse_datei:
            with open(a.kurse_datei, encoding="utf-8") as f:
                kurse = json.load(f)
        else:
            kurse = kurs_api.holen()
    except Exception as fehler:
        print(f"Kursabruf fehlgeschlagen: {type(fehler).__name__}: {fehler}", file=sys.stderr)
        return 1
    zustand = laden(a.daten) or neues_rennen(zeit)
    handeln(zustand, kurse, zeit, ki_client)
    speichern(a.daten, zustand)
    print(f"Lauf {zeit}: " + ", ".join(f"{n} {zustand['depots'][n]['wert']:.2f} €" for n in REIHENFOLGE))
    return 0


if __name__ == "__main__":
    sys.exit(main())
