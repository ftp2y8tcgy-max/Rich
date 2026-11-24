"""Erzeugt REPORT.md auf Deutsch aus dem Bot-Zustand."""

from datetime import date as _date

from bot.core import max_drawdown


def _eur(usd, eur_usd):
    return f"{usd / eur_usd:.2f} €".replace(".", ",")


def _pct(x):
    return f"{x * 100:+.1f} %".replace(".", ",")


def _days_between(a, b):
    return (_date.fromisoformat(b) - _date.fromisoformat(a)).days


def render(state):
    r = state["eur_usd"]
    start = state["capital_usd"]
    hist = state["history"]
    last = hist[-1] if hist else None
    lines = [
        "# Bericht: Test-Trading-Bot",
        "",
        "> **Spielgeld.** Dieser Bot handelt auf einem Alpaca-Paper-Konto, nicht mit echtem Geld.",
        "> Vergangene Ergebnisse garantieren nichts für die Zukunft. Paper-Ausführungen sind idealisiert.",
        "",
        f"- Letzter erfolgreicher Lauf: **{state['last_run'] or '—'}**",
        f"- Teststart: {state['start_date']} (seit {_days_between(state['start_date'], state['last_run'] or state['start_date'])} Tagen)",
        f"- Startkapital: {_eur(start, r)} (= {start:.2f} $ zum Kurs 1 € = {r:.4f} $)",
        f"- Strategie: {state['symbol']} halten, wenn über dem 200-Tage-Durchschnitt, sonst Bargeld; Entscheidung einmal im Monat",
        "",
    ]
    if last is None:
        lines += ["Noch keine Tageswerte.", ""]
    else:
        bot_vals = [h["bot"] for h in hist]
        bench_vals = [h["bench"] for h in hist]
        bench_fees = state["benchmark"]["fees_paid"]
        lines += [
            "| | Bot | Index kaufen und halten |",
            "| --- | --- | --- |",
            f"| Depotwert | {_eur(last['bot'], r)} | {_eur(last['bench'], r)} |",
            f"| Veränderung seit Start | {_pct(last['bot'] / start - 1)} | {_pct(last['bench'] / start - 1)} |",
            f"| Gebühren gesamt | {_eur(state['fees_paid'], r)} | {_eur(bench_fees, r)} |",
            f"| Veränderung ohne Gebühren | {_pct((last['bot'] + state['fees_paid']) / start - 1)} | {_pct((last['bench'] + bench_fees) / start - 1)} |",
            f"| Anzahl Orders | {len(state['orders'])} | 1 |",
            f"| Größter Zwischenverlust | {_pct(-max_drawdown(bot_vals))} | {_pct(-max_drawdown(bench_vals))} |",
            "",
            f"Aktuell: {'SPY gehalten' if state['shares'] > 0 else 'Bargeld'}. Letzter SPY-Kurs: {last['price']:.2f} $.",
            "",
            "Gebühr pro Order: 1 € (geschätzt wie bei deutschen Neobrokern; Alpaca Paper berechnet keine).",
            "",
        ]
    if state["orders"]:
        lines += ["## Orders", "", "| Datum | Art | Anteile | Kurs | Gebühr |", "| --- | --- | --- | --- | --- |"]
        for o in state["orders"]:
            art = "Kauf" if o["side"] == "buy" else "Verkauf"
            lines.append(f"| {o['date']} | {art} | {o['qty']:.6f} | {o['price']:.2f} $ | {_eur(o['fee'], r)} |")
        lines.append("")
    if state["notes"]:
        lines += ["## Hinweise", ""] + [f"- {n}" for n in state["notes"][-10:]] + [""]
    return "\n".join(lines)
