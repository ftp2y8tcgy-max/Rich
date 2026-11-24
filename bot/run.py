"""Tageslauf: Uhr prüfen, Kurse holen, ggf. handeln, Zustand und Bericht schreiben.

Aufruf (aus dem Repo-Stamm): python3 -m bot.run
"""

import json
import os
import sys
import time

from bot import core
from bot.report import render

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_PATH = os.path.join(ROOT, "bot", "state.json")
REPORT_PATH = os.path.join(ROOT, "REPORT.md")


def load_state(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save(state, state_path, report_path):
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
        f.write("\n")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(render(state))


def wait_for_fill(client, order_id, sleep, tries=20):
    for _ in range(tries):
        o = client.get_order(order_id)
        if o.get("status") == "filled":
            return float(o["filled_qty"]), float(o["filled_avg_price"])
        if o.get("status") in ("canceled", "expired", "rejected"):
            return None
        sleep(3)
    return None


def run(client, fx, state_path=STATE_PATH, report_path=REPORT_PATH, sleep=time.sleep):
    state = load_state(state_path)
    clock = client.clock()
    today = clock["timestamp"][:10]

    if not clock["is_open"]:
        if state is None:
            print("Markt geschlossen und noch kein Teststart; nichts zu tun.")
            return None
        state["last_run"] = today
        save(state, state_path, report_path)
        print(f"{today}: Markt geschlossen, nur Bericht aktualisiert.")
        return state

    bars = client.daily_closes(core.SYMBOL)
    if not bars:
        raise RuntimeError("Keine Kursdaten erhalten")
    price = bars[-1][1]
    closes = [c for d, c in bars if d < today]  # nur abgeschlossene Tage für das Signal

    if state is None:
        state = core.new_state(today, fx(), price)
        print(f"{today}: Teststart mit {core.START_EUR} € (1 € = {state['eur_usd']} $)")

    order = core.plan_order(state, today, closes)
    if order:
        placed = client.submit(core.SYMBOL, order)
        fill = wait_for_fill(client, placed["id"], sleep)
        if fill:
            qty, fill_price = fill
            core.apply_fill(state, today, order["side"], qty, fill_price)
            price = fill_price
            print(f"{today}: {order['side']} {qty} {core.SYMBOL} zu {fill_price}")
        else:
            state["last_decision_month"] = None  # nächster Lauf versucht es erneut
            state["notes"].append(f"{today}: Order nicht ausgeführt, neuer Versuch beim nächsten Lauf")

    core.record_day(state, today, price)
    save(state, state_path, report_path)
    return state


def main():
    from bot.alpaca import AlpacaPaper, eur_usd

    client = AlpacaPaper.from_env()
    run(client, eur_usd)


if __name__ == "__main__":
    sys.exit(main())
