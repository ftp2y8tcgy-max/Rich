"""Erzeugt KRYPTO-REPORT.md aus dem Rennzustand."""

from datetime import datetime, timezone

from krypto import depot as d

try:
    from zoneinfo import ZoneInfo
    BERLIN = ZoneInfo("Europe/Berlin")
except Exception:  # ohne Zeitzonendaten: UTC
    BERLIN = timezone.utc


def _zeit(iso):
    return datetime.fromisoformat(iso).astimezone(BERLIN).strftime("%d.%m.%Y %H:%M")


def _euro(x):
    return f"{x:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def _prozent(x):
    return f"{x * 100:.1f} %".replace(".", ",")


def _dauer(start, jetzt):
    sekunden = (datetime.fromisoformat(jetzt) - datetime.fromisoformat(start)).total_seconds()
    tage, rest = divmod(int(sekunden), 86400)
    return f"{tage} Tage, {rest // 3600} Stunden"


def _status(dep):
    if dep["status"] == d.BANKROTT:
        return f"💀 pleite am {_zeit(dep['pleite_zeit'])}"
    if dep["ziel_zeit"]:
        return f"🏁 Ziel erreicht am {_zeit(dep['ziel_zeit'])}"
    return "läuft"


def erzeugen(zustand):
    jetzt = zustand["letzter_lauf"]
    depots = sorted(zustand["depots"].values(), key=lambda x: x["wert"], reverse=True)
    z = [
        "# Krypto-Wettrennen: von 10 € auf 1.000 €",
        "",
        "> **Spielgeld.** Kein echtes Geld, keine echten Orders. Vergangene Ergebnisse garantieren nichts.",
        "",
        f"**Letzter Lauf:** {_zeit(jetzt)} Uhr  ",
        f"**Rennen Nr. {zustand['rennen']}** seit {_zeit(zustand['start'])} Uhr ({_dauer(zustand['start'], jetzt)})  ",
        "**Ziel:** 1.000 € · **Pleite:** unter 1 €",
        "",
        "## Rangliste",
        "",
        "| # | Strategie | Wert | bis 1.000 € | Status |",
        "| --- | --- | --- | --- | --- |",
    ]
    for i, dep in enumerate(depots, 1):
        z.append(f"| {i} | {dep['name']} | {_euro(dep['wert'])} | {_prozent(dep['wert'] / d.ZIEL)} | {_status(dep)} |")
    z += ["", "## Details", ""]
    for dep in depots:
        bestand = dep["coin"] or "Bargeld"
        z += [
            f"**{dep['name']}**",
            f"- Bestand: {bestand}",
            f"- Gebühren gesamt: {_euro(dep['gebuehren'])}",
            f"- Orders: {dep['orders']}",
            f"- Größter Zwischenverlust: {_prozent(dep['max_drawdown'])}",
        ]
        if dep["letzte_entscheidung"] is not None or dep["ki_ausfaelle"]:
            e = dep["letzte_entscheidung"] or {}
            z.append(f"- Letzte KI-Entscheidung: {e.get('entscheidung', '–')} ({_zeit(e['zeit']) if e.get('zeit') else '–'}): {e.get('begruendung', '')}")
            z.append(f"- KI-Ausfälle (dann: halten): {dep['ki_ausfaelle']}")
        z.append("")
    preise = zustand.get("preise", {})
    if preise:
        z += ["## Kurse beim letzten Lauf", "", " · ".join(f"{c}: {_euro(p)}" for c, p in preise.items()), ""]
    z += [
        "## Einschränkungen",
        "",
        "- Simulierte Orders zum letzten Kurs: kein Slippage, keine Mindestordergröße. Echte Ergebnisse wären schlechter.",
        "- Gebühr 0,1 % pro Order ist eingerechnet.",
        "- Eine kurze Renndauer sagt wenig über eine Strategie.",
        "- Regeln: [krypto/STRATEGIEN.md](https://github.com/ftp2y8tcgy-max/Rich/blob/main/krypto/STRATEGIEN.md)",
        "",
    ]
    return "\n".join(z)
