"""Regel-Strategien. Eingabe: Schlusskurse je Coin (älteste zuerst), Ausgabe: Ziel-Coin oder None (Bargeld).

Die Parameter sind während eines Rennens fest; siehe krypto/STRATEGIEN.md.
"""

COINS = ("BTC", "ETH", "SOL")
MOMENTUM_RUECKBLICK = 24  # Stunden
TREND_DURCHSCHNITT = 48  # Stundenkerzen


def momentum_rotation(kurse):
    besten, beste_rendite = None, 0.0
    for coin in COINS:
        reihe = kurse[coin]
        if len(reihe) <= MOMENTUM_RUECKBLICK:
            continue
        rendite = reihe[-1] / reihe[-1 - MOMENTUM_RUECKBLICK] - 1
        if rendite > beste_rendite:
            besten, beste_rendite = coin, rendite
    return besten


def trendfolge(kurse):
    besten, bester_abstand = None, 0.0
    for coin in COINS:
        reihe = kurse[coin]
        if len(reihe) < TREND_DURCHSCHNITT:
            continue
        schnitt = sum(reihe[-TREND_DURCHSCHNITT:]) / TREND_DURCHSCHNITT
        abstand = reihe[-1] / schnitt - 1
        if abstand > bester_abstand:
            besten, bester_abstand = coin, abstand
    return besten


def btc_halten(kurse):
    return "BTC"


REGEL_STRATEGIEN = {
    "Momentum-Rotation": momentum_rotation,
    "Trendfolge": trendfolge,
    "BTC halten (Vergleich)": btc_halten,
}
