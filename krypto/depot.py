"""Papierdepot nach Kraken-Regeln: Kauf zum Briefkurs (Ask), Verkauf zum Geldkurs (Bid),
0,40 % Taker-Gebühr, Mindestmenge (ordermin), Mindestwert (costmin), Mengen auf lot_decimals abgerundet.
Es wird nie eine echte Order geschickt."""

import math

from krypto.backtest import GEBUEHR


def neues_depot(startkapital):
    return {"bargeld": startkapital, "pair": None, "coin": None, "menge": 0.0, "einsatz": 0.0, "hoch": None,
            "kauf_zeit": None, "kauf_kurs": None}


def abrunden(x, stellen):
    f = 10 ** stellen
    return math.floor(x * f) / f


def kaufen(depot, pair, info, ask, zeit):
    """Kauft für das ganze Bargeld. Gibt (trade oder None, grund) zurück."""
    menge = abrunden(depot["bargeld"] / (1 + GEBUEHR) / ask, info.get("lot_decimals", 8))
    wert = menge * ask
    if menge <= 0 or menge < info.get("ordermin", 0) or wert < info.get("costmin", 0):
        return None, (f"{info['coin']}: {depot['bargeld']:.2f} € reichen nicht für die Kraken-Mindestorder "
                      f"({info.get('ordermin', 0)} {info['coin']} ≈ {info.get('ordermin', 0) * ask:.2f} €)")
    gebuehr = wert * GEBUEHR
    depot.update(bargeld=depot["bargeld"] - wert - gebuehr, pair=pair, coin=info["coin"], menge=menge,
                 einsatz=wert + gebuehr, hoch=ask, kauf_zeit=zeit, kauf_kurs=ask)
    return {"art": "Kauf", "coin": info["coin"], "pair": pair, "menge": menge, "kurs": ask, "wert": wert,
            "gebuehr": gebuehr, "zeit": zeit}, None


def verkaufen(depot, bid, zeit, grund):
    erloes = depot["menge"] * bid
    gebuehr = erloes * GEBUEHR
    trade = {"art": "Verkauf", "coin": depot["coin"], "pair": depot["pair"], "menge": depot["menge"], "kurs": bid,
             "wert": erloes, "gebuehr": gebuehr, "zeit": zeit, "grund": grund,
             "ergebnis": erloes - gebuehr - depot["einsatz"], "kauf_kurs": depot["kauf_kurs"],
             "kauf_zeit": depot["kauf_zeit"]}
    depot.update(bargeld=depot["bargeld"] + erloes - gebuehr, pair=None, coin=None, menge=0.0, einsatz=0.0,
                 hoch=None, kauf_zeit=None, kauf_kurs=None)
    return trade


def wert(depot, bid):
    return depot["bargeld"] + (depot["menge"] * bid if depot["pair"] and bid else 0.0)
