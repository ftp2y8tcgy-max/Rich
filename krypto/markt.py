"""Stundenkurse je Coin: gespeichert im Zustand, Kraken-Kerzen werden stückweise nachgeladen."""

STUNDE = 3600
MAX_STUNDEN = 720            # 30 Tage, so viel liefert Kraken in einem Abruf


def einpflegen(speicher, pair, kerzen, jetzt):
    """Kraken-Kerzen [(zeit, schluss)] in speicher[pair] = {"t0": zeit, "c": [schluss, ...]} übernehmen.

    Nur abgeschlossene Stunden (die laufende Kerze bleibt draußen). Lücken werden mit dem
    letzten Schlusskurs gefüllt, damit alle Coins auf demselben Stundenraster liegen.
    """
    fertig = {t: c for t, c in kerzen if t + STUNDE <= jetzt}
    if not fertig:
        return
    alt = speicher.get(pair)
    reihe = {}
    if alt:
        for i, c in enumerate(alt["c"]):
            reihe[alt["t0"] + i * STUNDE] = c
    reihe.update(fertig)
    zeiten = sorted(reihe)
    start = max(zeiten[0], zeiten[-1] - (MAX_STUNDEN - 1) * STUNDE)
    werte, letzter = [], None
    for t in range(start, zeiten[-1] + 1, STUNDE):
        letzter = reihe.get(t, letzter)
        werte.append(letzter)
    while werte and werte[0] is None:
        werte.pop(0)
        start += STUNDE
    speicher[pair] = {"t0": start, "c": werte}


def letzte_stunde(speicher, pair):
    s = speicher.get(pair)
    return s["t0"] + (len(s["c"]) - 1) * STUNDE if s and s["c"] else None


def raster(speicher, pairs, ende=None):
    """Gemeinsames Stundenraster: (zeiten, {pair: [schluss oder None]}) bis zur Stunde `ende`."""
    enden = [letzte_stunde(speicher, p) for p in pairs if letzte_stunde(speicher, p)]
    if not enden:
        return [], {}
    ende = ende or max(enden)
    zeiten = list(range(ende - (MAX_STUNDEN - 1) * STUNDE, ende + 1, STUNDE))
    matrix = {}
    for p in pairs:
        s = speicher.get(p)
        if not s:
            continue
        zeile = []
        for t in zeiten:
            i = (t - s["t0"]) // STUNDE
            zeile.append(s["c"][i] if 0 <= i < len(s["c"]) else None)
        matrix[p] = zeile
    return zeiten, matrix
