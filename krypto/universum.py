"""Welche Coins der Bot beobachtet: alle Kraken-Paare in Euro, die echt handelbar sind."""

STABIL = {"USDT", "USDC", "DAI", "EURT", "PYUSD", "TUSD", "USDG", "RLUSD", "USDQ", "EURQ", "EURR", "USDR", "UST",
          "USDD", "FDUSD", "EUROP", "USD1", "EURC", "USDS", "GUSD", "PAXG", "XAUT", "TBTC", "WBTC", "LSETH", "CMETH",
          "METH", "STETH"}
FIAT = {"USD", "GBP", "EUR", "CHF", "AUD", "CAD", "JPY", "ZUSD", "ZGBP", "ZEUR", "ZCAD", "ZJPY", "ZCHF", "ZAUD"}
UMBENENNEN = {"XBT": "BTC", "XDG": "DOGE"}

MAX_COINS = 40
MIN_VOLUMEN_EUR = 250_000     # 24-h-Umsatz: darunter wären echte Orders schwer zu füllen
MAX_SPREAD = 0.005            # 0,5 %


def coin_name(paar):
    ws = paar.get("wsname") or ""
    basis = ws.split("/")[0] if "/" in ws else paar.get("base", "?")
    return UMBENENNEN.get(basis, basis)


def waehlen(paare, ticker, max_coins=MAX_COINS, min_volumen=MIN_VOLUMEN_EUR, max_spread=MAX_SPREAD):
    """Liefert {pair: info} der liquidesten Euro-Paare, sortiert nach Umsatz."""
    kandidaten = []
    for name, p in paare.items():
        if p.get("quote") not in ("ZEUR", "EUR") or name.endswith(".d"):
            continue
        if p.get("status", "online") != "online":
            continue
        coin = coin_name(p)
        if coin in STABIL or coin in FIAT or p.get("base") in FIAT:
            continue
        t = ticker.get(name)
        if not t:
            continue
        try:
            ask, bid = float(t["a"][0]), float(t["b"][0])
            umsatz = float(t["v"][1]) * float(t["p"][1])
        except (KeyError, ValueError, IndexError):
            continue
        if ask <= 0 or bid <= 0:
            continue
        spread = (ask - bid) / ((ask + bid) / 2)
        if umsatz < min_volumen or spread > max_spread:
            continue
        kandidaten.append((umsatz, name, {
            "coin": coin, "umsatz": round(umsatz), "spread": round(spread, 6),
            "ordermin": float(p.get("ordermin") or 0), "costmin": float(p.get("costmin") or 0),
            "lot_decimals": int(p.get("lot_decimals", 8)),
        }))
    kandidaten.sort(reverse=True)
    return {name: info for _, name, info in kandidaten[:max_coins]}
