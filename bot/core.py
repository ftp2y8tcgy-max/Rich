"""Buchführung, Strategie und Vergleichsdepot. Reine Funktionen, kein Netzwerk.

Strategie (fest während einer Testphase, siehe STRATEGIE in README.md):
Am ersten Lauf eines Kalendermonats wird entschieden. Liegt der letzte
Schlusskurs von SPY über seinem 200-Tage-Durchschnitt, hält der Bot SPY,
sonst Bargeld. Eine Order gibt es nur, wenn sich die Position ändern muss.
"""

SYMBOL = "SPY"
START_EUR = 10.0
FEE_EUR = 1.0
SMA_DAYS = 200
MIN_NOTIONAL_USD = 1.0  # kleinste Dollar-Order bei Alpaca


def new_state(start_date, eur_usd, price):
    """Legt den Teststart an: Bot-Depot in bar, Vergleichsdepot kauft sofort."""
    capital = round(START_EUR * eur_usd, 4)
    fee = round(FEE_EUR * eur_usd, 4)
    return {
        "symbol": SYMBOL,
        "start_date": start_date,
        "eur_usd": eur_usd,
        "capital_usd": capital,
        "fee_usd": fee,
        "cash": capital,
        "shares": 0.0,
        "fees_paid": 0.0,
        "orders": [],
        "history": [],
        "last_decision_month": None,
        "last_run": None,
        "notes": [],
        "benchmark": {
            "shares": (capital - fee) / price,
            "fees_paid": fee,
            "start_price": price,
        },
    }


def signal(closes):
    """'hold' wenn letzter Schluss > SMA200, sonst 'cash'. None bei zu wenig Daten."""
    if len(closes) < SMA_DAYS:
        return None
    window = closes[-SMA_DAYS:]
    sma = sum(window) / SMA_DAYS
    return "hold" if closes[-1] > sma else "cash"


def is_decision_day(state, today):
    return state["last_decision_month"] != today[:7]


def plan_order(state, today, closes):
    """Gibt die nötige Order zurück oder None.

    Order: {"side": "buy", "notional": usd} oder {"side": "sell", "qty": anteile}.
    Markiert den Monat als entschieden, sobald ein Signal vorliegt.
    """
    if not is_decision_day(state, today):
        return None
    target = signal(closes)
    if target is None:
        state["notes"].append(f"{today}: zu wenig Kursdaten für den 200-Tage-Durchschnitt")
        return None
    state["last_decision_month"] = today[:7]
    if target == "hold" and state["shares"] == 0:
        notional = round(state["cash"] - state["fee_usd"], 2)
        if notional < MIN_NOTIONAL_USD:
            state["notes"].append(f"{today}: Kauf übersprungen, nach Gebühr zu wenig Geld ({notional} $)")
            return None
        return {"side": "buy", "notional": notional}
    if target == "cash" and state["shares"] > 0:
        return {"side": "sell", "qty": state["shares"]}
    return None


def apply_fill(state, date, side, qty, price):
    """Bucht eine ausgeführte Order inklusive Gebühr ins Bot-Depot."""
    fee = state["fee_usd"]
    amount = qty * price
    if side == "buy":
        state["cash"] = round(state["cash"] - amount - fee, 6)
        state["shares"] += qty
    else:
        state["cash"] = round(state["cash"] + amount - fee, 6)
        state["shares"] = max(0.0, state["shares"] - qty)
        if state["shares"] < 1e-9:
            state["shares"] = 0.0
    state["fees_paid"] = round(state["fees_paid"] + fee, 6)
    state["orders"].append(
        {"date": date, "side": side, "qty": qty, "price": price, "fee": fee}
    )


def record_day(state, date, price):
    """Hält Tageswerte von Bot und Vergleichsdepot fest (einmal pro Datum)."""
    bot = state["cash"] + state["shares"] * price
    bench = state["benchmark"]["shares"] * price
    entry = {"date": date, "price": price, "bot": round(bot, 4), "bench": round(bench, 4)}
    if state["history"] and state["history"][-1]["date"] == date:
        state["history"][-1] = entry
    else:
        state["history"].append(entry)
    state["last_run"] = date
    return entry


def max_drawdown(values):
    """Größter Rückgang vom bisherigen Höchststand, als Anteil (0.25 = 25 %)."""
    peak = None
    worst = 0.0
    for v in values:
        if peak is None or v > peak:
            peak = v
        if peak and peak > 0:
            worst = max(worst, (peak - v) / peak)
    return worst
