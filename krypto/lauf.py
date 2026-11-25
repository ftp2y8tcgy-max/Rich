"""Ein Lauf (alle 5 Minuten auf GitHub Actions).

1. Kurse aller Kraken-Paare holen (eine Anfrage), Coin-Auswahl alle 6 Stunden erneuern
2. Stundenkerzen der beobachteten Coins stückweise nachladen
3. Stop prüfen: 10 % unter dem Höchststand seit Kauf → verkaufen (jeden Lauf)
4. Zur vollen Stunde: alle Strategien auf 14 Tagen testen, die beste wählen, danach handeln
5. Bewerten, Bericht schreiben, Zustand speichern

Aufruf: python3 -m krypto.lauf [--daten DIR] [--neu] [--startkapital 10]
"""

import argparse
import datetime
import json
import os
import sys
import time

from krypto import backtest, bericht, depot as dp, kraken, markt, strategien, universum

BTC_PAIR = "XXBTZEUR"
UNIVERSUM_ALTER = 6 * 3600
WALK_ALTER = 6 * 3600
NACHLADEN_JE_LAUF = 12
MAX_VERLAUF = 3000


def iso(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).isoformat(timespec="minutes")


def neuer_zustand(jetzt, startkapital):
    return {"version": 2, "start": jetzt, "startkapital": startkapital, "universum": {}, "universum_zeit": 0,
            "markt": {}, "depot": dp.neues_depot(startkapital), "btc_depot": dp.neues_depot(startkapital),
            "auswahl": None, "walk_forward": None, "walk_zeit": 0, "entscheidung_stunde": 0, "trades": [],
            "anzahl_trades": 0, "kosten": 0.0, "verlauf": [], "ereignisse": [], "laeufe": 0, "letzter_lauf": jetzt}


def ereignis(z, jetzt, text):
    print(text)
    z["ereignisse"] = (z["ereignisse"] + [[jetzt, text]])[-40:]


def bid_ask(tick, pair):
    t = tick.get(pair)
    return (float(t["b"][0]), float(t["a"][0])) if t else (None, None)


def buchen(z, trade, jetzt):
    z["trades"] = (z["trades"] + [trade])[-200:]
    z["anzahl_trades"] += 1
    z["kosten"] += trade["gebuehr"]
    if trade["art"] == "Kauf":
        ereignis(z, jetzt, f"Kauf {trade['menge']:g} {trade['coin']} zu {trade['kurs']:.6g} € "
                           f"(Gebühr {trade['gebuehr']:.2f} €)")
    else:
        ereignis(z, jetzt, f"Verkauf {trade['coin']} zu {trade['kurs']:.6g} € – {trade['grund']}, "
                           f"Ergebnis {trade['ergebnis']:+.2f} €")


def schritt(z, api, jetzt):
    """Ein Lauf auf dem Zustand z. api stellt asset_pairs, ticker und ohlc bereit (im Test ein Nachbau)."""
    tick = api.ticker()
    # 1) Coin-Auswahl
    if not z["universum"] or jetzt - z["universum_zeit"] > UNIVERSUM_ALTER:
        neu = universum.waehlen(api.asset_pairs(), tick)
        for pflicht in {BTC_PAIR, z["depot"]["pair"]} - {None}:
            if pflicht not in neu and pflicht in z["universum"]:
                neu[pflicht] = z["universum"][pflicht]
        if neu:
            z["universum"], z["universum_zeit"] = neu, jetzt
            ereignis(z, jetzt, f"Beobachte {len(neu)} Coins (Kraken, Euro, liquide)")
    for pair, info in z["universum"].items():
        b, a = bid_ask(tick, pair)
        if b and a:
            info["spread"] = (a - b) / ((a + b) / 2)
    # 2) Stundenkerzen nachladen (die ältesten zuerst; beim ersten Lauf alle)
    volle_stunde = int(jetzt // markt.STUNDE) * markt.STUNDE - markt.STUNDE   # letzte abgeschlossene Stunde
    veraltet = sorted((markt.letzte_stunde(z["markt"], p) or 0, p) for p in z["universum"])
    veraltet = [p for t, p in veraltet if t < volle_stunde]
    grenze = len(veraltet) if not z["markt"] else NACHLADEN_JE_LAUF
    for pair in veraltet[:grenze]:
        try:
            markt.einpflegen(z["markt"], pair, api.ohlc(pair, 60, markt.letzte_stunde(z["markt"], pair)), jetzt)
        except kraken.KrakenFehler as fehler:
            print(f"{pair}: {fehler}", file=sys.stderr)
    for alt in [p for p in z["markt"] if p not in z["universum"] and p != z["depot"]["pair"]]:
        del z["markt"][alt]
    # 3) Benchmark: BTC beim ersten Lauf kaufen und halten
    d, bd = z["depot"], z["btc_depot"]
    if not bd["pair"] and bd["bargeld"] == z["startkapital"] and BTC_PAIR in z["universum"]:
        _, a = bid_ask(tick, BTC_PAIR)
        if a:
            dp.kaufen(bd, BTC_PAIR, z["universum"][BTC_PAIR], a, iso(jetzt))
    # 4) Stop jeden Lauf
    if d["pair"]:
        b, _ = bid_ask(tick, d["pair"])
        if b:
            d["hoch"] = max(d["hoch"] or b, b)
            if b < d["hoch"] * (1 - backtest.TRAILING_STOP):
                buchen(z, dp.verkaufen(d, b, iso(jetzt), f"Stop 10 % unter Hoch ({d['hoch']:.6g} €)"), jetzt)
                z["entscheidung_stunde"] = volle_stunde      # in dieser Stunde nicht sofort wieder kaufen
    # 5) Zur vollen Stunde: Strategie wählen und handeln
    if z["entscheidung_stunde"] < volle_stunde:
        frisch = [p for p in z["universum"] if markt.letzte_stunde(z["markt"], p) == volle_stunde]
        if d["pair"] and d["pair"] not in frisch and d["pair"] in z["markt"]:
            frisch.append(d["pair"])
        if BTC_PAIR in frisch and len(frisch) >= 3:
            zeiten, matrix = markt.raster(z["markt"], frisch, volle_stunde)
            kosten = {p: backtest.kosten_je_seite(z["universum"].get(p, {}).get("spread", 0.004)) for p in matrix}
            listen = backtest.alle_ranglisten(matrix, kosten, BTC_PAIR)
            n = len(zeiten)
            tabelle = backtest.auswahl(listen, matrix, kosten, n)
            beste = tabelle[0]
            z["auswahl"] = {"id": beste["id"], "name": beste["name"], "zeit": volle_stunde, "tabelle": tabelle,
                            "coins": len(matrix)}
            if jetzt - z["walk_zeit"] > WALK_ALTER:
                z["walk_forward"] = backtest.walk_forward(listen, matrix, kosten, BTC_PAIR)
                z["walk_zeit"] = jetzt
            ziel = strategien.ziel(listen[beste["id"]][n - 1], d["pair"])
            if ziel != d["pair"]:
                if d["pair"]:
                    b, _ = bid_ask(tick, d["pair"])
                    if b:
                        buchen(z, dp.verkaufen(d, b, iso(jetzt), f"Wechsel ({beste['name']})"), jetzt)
                if ziel and not d["pair"]:
                    _, a = bid_ask(tick, ziel)
                    if a:
                        trade, grund = dp.kaufen(d, ziel, z["universum"][ziel], a, iso(jetzt))
                        if trade:
                            buchen(z, trade, jetzt)
                        else:
                            ereignis(z, jetzt, grund)
            z["entscheidung_stunde"] = volle_stunde
    # 6) Bewertung
    wert = dp.wert(d, bid_ask(tick, d["pair"])[0] if d["pair"] else None)
    btc_wert = dp.wert(bd, bid_ask(tick, BTC_PAIR)[0]) if bd["pair"] else bd["bargeld"]
    z["verlauf"].append([int(jetzt), round(wert, 4), round(btc_wert, 4)])
    if len(z["verlauf"]) > MAX_VERLAUF:
        v = z["verlauf"]
        z["verlauf"] = v[:1] + v[1:-1:2] + v[-1:]
    z["wert"], z["btc_wert"] = wert, btc_wert
    z["laeufe"] += 1
    z["letzter_lauf"] = jetzt
    return z


def laden(pfad):
    if os.path.exists(pfad):
        with open(pfad, encoding="utf-8") as f:
            return json.load(f)
    return None


def speichern(verzeichnis, z):
    os.makedirs(verzeichnis, exist_ok=True)
    for name, inhalt in (("zustand.json", json.dumps(z, separators=(",", ":"))),
                         ("KRYPTO-REPORT.md", bericht.markdown(z)), ("verlauf.svg", bericht.svg(z))):
        tmp = os.path.join(verzeichnis, name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(inhalt)
        os.replace(tmp, os.path.join(verzeichnis, name))


def main(argv=None, api=kraken):
    p = argparse.ArgumentParser()
    p.add_argument("--daten", default="daten")
    p.add_argument("--neu", action="store_true", help="neues Depot mit Startkapital (Kursdaten bleiben)")
    p.add_argument("--startkapital", type=float, default=float(os.environ.get("STARTKAPITAL") or 10))
    a = p.parse_args(argv)
    jetzt = time.time()
    pfad = os.path.join(a.daten, "zustand.json")
    z = laden(pfad)
    if z is None or z.get("version") != 2:
        z = neuer_zustand(jetzt, a.startkapital)
    elif a.neu:
        markt_alt, uni = z["markt"], z["universum"]
        z = neuer_zustand(jetzt, a.startkapital)
        z["markt"], z["universum"], z["universum_zeit"] = markt_alt, uni, jetzt
    try:
        schritt(z, api, jetzt)
    except kraken.KrakenFehler as fehler:
        print(f"Kraken nicht erreichbar: {fehler}", file=sys.stderr)
        return 1
    speichern(a.daten, z)
    print(f"Lauf {iso(jetzt)}: Wert {z['wert']:.2f} €, BTC halten {z['btc_wert']:.2f} €, "
          f"{len(z['universum'])} Coins, Strategie {z['auswahl']['name'] if z['auswahl'] else '–'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
