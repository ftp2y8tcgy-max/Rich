"""Strategie-Varianten. Jede liefert pro Stunde eine Rangliste von Coins, die sie kaufen würde.

Eine Variante kauft nur, wenn die Bewegung die Kosten deutlich übersteigt (Hürde = 2 × Hin- und
Rückweg-Kosten). Gehalten wird immer höchstens ein Coin; gewechselt wird nur mit klarem Vorsprung.
"""

import math

VARIANTEN = (
    {"id": "mom6", "name": "Momentum 6 h", "art": "momentum", "L": 6},
    {"id": "mom24", "name": "Momentum 24 h", "art": "momentum", "L": 24},
    {"id": "mom72", "name": "Momentum 72 h", "art": "momentum", "L": 72},
    {"id": "aus24", "name": "Ausbruch 24 h", "art": "ausbruch", "L": 24},
    {"id": "aus72", "name": "Ausbruch 72 h", "art": "ausbruch", "L": 72},
    {"id": "btc", "name": "BTC halten", "art": "halten"},
    {"id": "bar", "name": "Bargeld", "art": "bargeld"},
)
NACH_ID = {v["id"]: v for v in VARIANTEN}
VOL_FENSTER = 24
WECHSEL_VORSPRUNG = 0.5      # neuer Coin braucht so viel mehr Punkte als der gehaltene
HUERDE_FAKTOR = 2.0


def ranglisten(variante, matrix, kosten, btc_pair):
    """Für jede Stunde i: [(punkte, pair), ...] absteigend, nur Coins mit Kaufsignal.

    matrix: {pair: [schluss oder None]} auf gemeinsamem Raster. Benutzt an Stunde i nur
    Kurse bis einschließlich i (kein Blick in die Zukunft).
    """
    n = len(next(iter(matrix.values()))) if matrix else 0
    art = variante["art"]
    if art == "bargeld":
        return [[] for _ in range(n)]
    if art == "halten":
        reihe = matrix.get(btc_pair, [None] * n)
        return [[(1.0, btc_pair)] if reihe[i] is not None else [] for i in range(n)]
    L = variante["L"]
    listen = [[] for _ in range(n)]
    for pair, c in matrix.items():
        huerde = HUERDE_FAKTOR * 2 * kosten.get(pair, 0.006)
        # gleitender Mittelwert der absoluten Stundenrenditen (Schwankung)
        absr = [None] + [abs(c[i] / c[i - 1] - 1) if c[i] and c[i - 1] else None for i in range(1, n)]
        for i in range(max(L, VOL_FENSTER) + 1, n):
            if c[i] is None or c[i - L] is None:
                continue
            fenster = [a for a in absr[i - VOL_FENSTER + 1:i + 1] if a is not None]
            if len(fenster) < VOL_FENSTER // 2:
                continue
            vol = sum(fenster) / len(fenster) or 1e-9
            r = c[i] / c[i - L] - 1
            if r <= huerde:
                continue
            if art == "momentum":
                punkte = r / (vol * math.sqrt(L))
            else:
                vorher = [x for x in c[i - L:i] if x is not None]
                if not vorher or c[i] <= max(vorher):
                    continue
                punkte = (c[i] / max(vorher) - 1) / vol
            listen[i].append((punkte, pair))
    for liste in listen:
        liste.sort(reverse=True)
    return listen


def ziel(rangliste, gehalten):
    """Welcher Coin gehalten werden soll (None = Bargeld), mit Wechsel-Hysterese."""
    if not rangliste:
        return None
    bester_punkte, bester = rangliste[0]
    if gehalten is None or bester == gehalten:
        return bester
    eigene = next((p for p, pair in rangliste if pair == gehalten), None)
    if eigene is None:
        return bester
    return bester if bester_punkte > eigene + WECHSEL_VORSPRUNG else gehalten
