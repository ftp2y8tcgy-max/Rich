"""Simuliertes Spielgeld-Depot. Keine Börse, keine echten Orders."""

GEBUEHR = 0.001  # 0,1 % pro Order
STARTKAPITAL = 10.0
ZIEL = 1000.0
PLEITE = 1.0

LAEUFT = "läuft"
ZIEL_ERREICHT = "ziel"
BANKROTT = "pleite"


def neues_depot(name, zeit):
    return {
        "name": name,
        "bargeld": STARTKAPITAL,
        "coin": None,
        "menge": 0.0,
        "status": LAEUFT,
        "ziel_zeit": None,
        "pleite_zeit": None,
        "gebuehren": 0.0,
        "orders": 0,
        "hoechstwert": STARTKAPITAL,
        "max_drawdown": 0.0,
        "wert": STARTKAPITAL,
        "ki_ausfaelle": 0,
        "letzte_entscheidung": None,
        "start": zeit,
    }


def wert(depot, preise):
    if depot["coin"] is None:
        return depot["bargeld"]
    return depot["bargeld"] + depot["menge"] * preise[depot["coin"]]


def _verkaufen(depot, preise):
    erloes = depot["menge"] * preise[depot["coin"]]
    gebuehr = erloes * GEBUEHR
    depot["bargeld"] += erloes - gebuehr
    depot["gebuehren"] += gebuehr
    depot["orders"] += 1
    depot["coin"] = None
    depot["menge"] = 0.0


def _kaufen(depot, coin, preise):
    gebuehr = depot["bargeld"] * GEBUEHR
    depot["menge"] = (depot["bargeld"] - gebuehr) / preise[coin]
    depot["gebuehren"] += gebuehr
    depot["orders"] += 1
    depot["coin"] = coin
    depot["bargeld"] = 0.0


def umschichten(depot, ziel_coin, preise):
    """Setzt das ganze Depot auf ziel_coin (None = Bargeld). Orders nur bei Wechsel."""
    if depot["status"] == BANKROTT or depot["coin"] == ziel_coin:
        return
    if depot["coin"] is not None:
        _verkaufen(depot, preise)
    if ziel_coin is not None:
        _kaufen(depot, ziel_coin, preise)


def bewerten(depot, preise, zeit):
    """Aktualisiert Wert, Zwischenverlust und Rennstatus nach einem Lauf."""
    w = wert(depot, preise)
    depot["wert"] = w
    depot["hoechstwert"] = max(depot["hoechstwert"], w)
    if depot["hoechstwert"] > 0:
        depot["max_drawdown"] = max(depot["max_drawdown"], 1 - w / depot["hoechstwert"])
    if w >= ZIEL and depot["ziel_zeit"] is None:
        depot["ziel_zeit"] = zeit
        if depot["status"] == LAEUFT:
            depot["status"] = ZIEL_ERREICHT
    if w < PLEITE and depot["status"] != BANKROTT:
        depot["status"] = BANKROTT
        depot["pleite_zeit"] = zeit
    return w
