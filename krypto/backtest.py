"""Test einer Variante auf Stundenkursen mit Kraken-Kosten, Auswahl der besten und Walk-Forward-Prüfung."""

from krypto import strategien

GEBUEHR = 0.004          # Kraken Pro, Taker, unter 10.000 $ Monatsvolumen
TRAILING_STOP = 0.10     # Verkauf 10 % unter dem Höchststand seit Kauf
AUSWAHL_FENSTER = 14 * 24
WALK_SCHRITT = 24


def kosten_je_seite(spread):
    return GEBUEHR + spread / 2


def simulieren(listen, matrix, kosten, von, bis, gehalten=None, wert=1.0, hoch=None):
    """Spielt Stunden von..bis-1 durch. Entscheidung am Schluss von Stunde i mit Daten bis i.

    Gibt (endwert, gehalten, hoch, anzahl_trades, verlauf) zurück.
    """
    trades, verlauf = 0, []
    for i in range(von, bis):
        if gehalten is not None:
            c0, c1 = matrix[gehalten][i - 1], matrix[gehalten][i]
            if c0 and c1:
                wert *= c1 / c0
                hoch = max(hoch or c1, c1)
                if c1 < hoch * (1 - TRAILING_STOP):
                    wert *= 1 - kosten[gehalten]
                    gehalten, hoch, trades = None, None, trades + 1
                    verlauf.append(wert)
                    continue          # nach einem Stop in derselben Stunde nicht sofort wieder kaufen
        neu = strategien.ziel(listen[i], gehalten)
        if neu != gehalten:
            if gehalten is not None:
                wert *= 1 - kosten[gehalten]
                trades += 1
            if neu is not None:
                wert *= 1 - kosten[neu]
                hoch = matrix[neu][i]
                trades += 1
            gehalten = neu
        verlauf.append(wert)
    return wert, gehalten, hoch, trades, verlauf


def max_drawdown(verlauf):
    hoch, dd = 0.0, 0.0
    for w in verlauf:
        hoch = max(hoch, w)
        if hoch > 0:
            dd = max(dd, 1 - w / hoch)
    return dd


def alle_ranglisten(matrix, kosten, btc_pair):
    return {v["id"]: strategien.ranglisten(v, matrix, kosten, btc_pair) for v in strategien.VARIANTEN}


def auswahl(listen_je_variante, matrix, kosten, ende, fenster=AUSWAHL_FENSTER):
    """Testet jede Variante auf den `fenster` Stunden vor `ende`. Beste = höchster Endwert nach Kosten,
    bei Gleichstand die mit kleinerem Zwischenverlust. Bargeld (1,0) ist immer dabei."""
    von = max(1, ende - fenster)
    ergebnisse = []
    for v in strategien.VARIANTEN:
        wert, _, _, trades, verlauf = simulieren(listen_je_variante[v["id"]], matrix, kosten, von, ende)
        ergebnisse.append({"id": v["id"], "name": v["name"], "ergebnis": wert - 1, "trades": trades,
                           "drawdown": max_drawdown(verlauf or [1.0])})
    ergebnisse.sort(key=lambda e: (round(e["ergebnis"], 6), -e["drawdown"]), reverse=True)
    return ergebnisse


def walk_forward(listen_je_variante, matrix, kosten, btc_pair, fenster=AUSWAHL_FENSTER, schritt=WALK_SCHRITT):
    """Ehrliche Prüfung: für jeden Tag die Variante wählen, die in den 14 Tagen davor am besten war,
    und sie dann den Tag lang handeln. Ergebnis im Vergleich zu BTC halten über dieselbe Zeit."""
    n = len(next(iter(matrix.values()))) if matrix else 0
    if n < fenster + schritt + 2:
        return None
    wert, gehalten, hoch, trades, verlauf, gewaehlt = 1.0, None, None, 0, [], []
    for start in range(fenster + 1, n, schritt):
        ende = min(n, start + schritt)
        beste = auswahl(listen_je_variante, matrix, kosten, start, fenster)[0]["id"]
        gewaehlt.append(beste)
        wert, gehalten, hoch, t, v = simulieren(listen_je_variante[beste], matrix, kosten, start, ende,
                                                gehalten, wert, hoch)
        trades += t
        verlauf += v
    btc = matrix.get(btc_pair)
    btc_ergebnis = None
    if btc and btc[fenster] and btc[-1]:
        btc_ergebnis = (btc[-1] / btc[fenster]) * (1 - kosten.get(btc_pair, 0.005)) ** 2 - 1
    return {"ergebnis": wert - 1, "btc": btc_ergebnis, "trades": trades, "drawdown": max_drawdown(verlauf),
            "tage": len(gewaehlt), "gewaehlt": gewaehlt}
