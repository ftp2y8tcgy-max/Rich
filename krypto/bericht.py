"""Bericht für das iPad: KRYPTO-REPORT.md (auf dem Daten-Branch) und verlauf.svg."""

import datetime

try:
    from zoneinfo import ZoneInfo
    BERLIN = ZoneInfo("Europe/Berlin")
except Exception:
    BERLIN = datetime.timezone.utc

# Freigabe-Ampel: erst wenn alles erfüllt ist, ist Echtgeld überhaupt eine Überlegung
MIN_TAGE = 56
MIN_TRADES = 30
MAX_DD = 0.30


def zeit(ts):
    return datetime.datetime.fromtimestamp(ts, BERLIN).strftime("%d.%m.%Y %H:%M")


def euro(x, vz=False):
    t = f"{abs(x):,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")
    return (("+" if x >= 0 else "−") + t) if vz else t


def pz(x):
    return f"{x * 100:+.1f} %".replace(".", ",")


def kennzahlen(z):
    v = z["verlauf"]
    hoch, dd = 0.0, 0.0
    for _, w, _ in v:
        hoch = max(hoch, w)
        dd = max(dd, 1 - w / hoch) if hoch else dd
    tage = (z["letzter_lauf"] - z["start"]) / 86400
    start = z["startkapital"]
    return {"tage": tage, "dd": dd, "ergebnis": z.get("wert", start) / start - 1,
            "btc": z.get("btc_wert", start) / start - 1,
            "verkaeufe": sum(1 for t in z["trades"] if t["art"] == "Verkauf")}


def ampel(z, k):
    wf = z.get("walk_forward") or {}
    pruefungen = [
        (k["tage"] >= MIN_TAGE, f"Mindestens {MIN_TAGE} Tage Papierhandel", f"{k['tage']:.1f} Tage"),
        (z["anzahl_trades"] >= MIN_TRADES, f"Mindestens {MIN_TRADES} Trades", f"{z['anzahl_trades']} Trades"),
        (k["ergebnis"] > 0, "Nach allen Kosten im Plus", pz(k["ergebnis"])),
        (k["ergebnis"] > k["btc"], "Besser als BTC halten", f"{pz(k['ergebnis'])} gegen {pz(k['btc'])}"),
        (k["dd"] <= MAX_DD, f"Größter Zwischenverlust höchstens {int(MAX_DD * 100)} %", pz(-k["dd"])),
        (bool(wf) and wf.get("btc") is not None and wf["ergebnis"] > wf["btc"],
         "Walk-Forward-Test besser als BTC halten",
         f"{pz(wf['ergebnis'])} gegen {pz(wf['btc'])}" if wf and wf.get("btc") is not None else "noch keine Daten"),
    ]
    return all(p[0] for p in pruefungen), pruefungen


def markdown(z):
    k = kennzahlen(z)
    frei, pruefungen = ampel(z, k)
    d, a = z["depot"], z.get("auswahl")
    zeilen = [
        "# Krypto-Scanner (Papiergeld, Kraken-Regeln)",
        "",
        "> **Kein echtes Geld.** Gerechnet wie bei Kraken: Kauf zum Briefkurs, Verkauf zum Geldkurs, "
        "0,40 % Gebühr, Mindestordergrößen. Vergangene Ergebnisse garantieren nichts.",
        "",
        f"**Letzter Lauf:** {zeit(z['letzter_lauf'])} · **seit** {zeit(z['start'])} ({k['tage']:.1f} Tage, "
        f"{z['laeufe']} Läufe)",
        "",
        "## Stand",
        "",
        "| | Bot | BTC halten |",
        "| --- | --- | --- |",
        f"| Wert | **{euro(z.get('wert', 0))}** | {euro(z.get('btc_wert', 0))} |",
        f"| seit Start ({euro(z['startkapital'])}) | **{pz(k['ergebnis'])}** | {pz(k['btc'])} |",
        f"| Gebühren bisher | {euro(z['kosten'])} | |",
        f"| Trades | {z['anzahl_trades']} | 1 |",
        f"| größter Zwischenverlust | {pz(-k['dd'])} | |",
        "",
        "![Verlauf](verlauf.svg)",
        "",
        "## Jetzt",
        "",
    ]
    if d["pair"]:
        zeilen.append(f"Hält **{d['menge']:g} {d['coin']}**, gekauft {d['kauf_zeit'][:16].replace('T', ' ')} UTC "
                      f"zu {d['kauf_kurs']:.6g} €. Stop bei {d['hoch'] * 0.9:.6g} € (10 % unter dem Höchststand).")
    else:
        zeilen.append(f"**Bargeld** ({euro(d['bargeld'])}): Gerade erfüllt kein Coin die Kaufregel nach Kosten.")
    zeilen += ["", "## Gewählte Strategie", ""]
    if a:
        zeilen += [f"**{a['name']}**, gewählt {zeit(a['zeit'] + 3600)} aus {a['coins']} Coins. Test der letzten "
                   "14 Tage nach Kosten:", "", "| Strategie | Ergebnis | Trades | Zwischenverlust |",
                   "| --- | --- | --- | --- |"]
        for e in a["tabelle"]:
            fett = "**" if e["id"] == a["id"] else ""
            zeilen.append(f"| {fett}{e['name']}{fett} | {pz(e['ergebnis'])} | {e['trades']} | {pz(-e['drawdown'])} |")
    else:
        zeilen.append("Noch nicht genug Stundenkurse geladen.")
    wf = z.get("walk_forward")
    zeilen += ["", "## Ehrliche Prüfung (Walk-Forward)", ""]
    if wf:
        zeilen.append(f"Jeden Tag die Strategie gewählt, die in den 14 Tagen davor am besten war, und sie den Tag "
                      f"gehandelt ({wf['tage']} Tage, {wf['trades']} Trades): **{pz(wf['ergebnis'])}** gegen "
                      f"BTC halten {pz(wf['btc']) if wf['btc'] is not None else '–'}, größter Zwischenverlust "
                      f"{pz(-wf['drawdown'])}.")
    else:
        zeilen.append("Noch nicht genug Daten (braucht gut 15 Tage Stundenkurse).")
    zeilen += ["", f"## Echtgeld-Freigabe: {'🟢 erfüllt' if frei else '🔴 noch nicht'}", ""]
    for ok, text, wert in pruefungen:
        zeilen.append(f"- {'✅' if ok else '❌'} {text}: {wert}")
    zeilen += ["", "Auch bei Grün: nur Geld einsetzen, dessen Verlust du verkraftest, klein anfangen und weiter "
               "mitschreiben. Echte Orders sind nicht eingebaut.", ""]
    zeilen += ["## Letzte Trades", ""]
    verkaeufe = [t for t in z["trades"] if t["art"] == "Verkauf"][-8:]
    if verkaeufe:
        zeilen += ["| Verkauf | Coin | Kauf → Verkauf | Grund | Ergebnis |", "| --- | --- | --- | --- | --- |"]
        for t in reversed(verkaeufe):
            zeilen.append(f"| {t['zeit'][5:16].replace('T', ' ')} | {t['coin']} | {t['kauf_kurs']:.6g} → "
                          f"{t['kurs']:.6g} | {t['grund']} | {euro(t['ergebnis'], True)} |")
    else:
        zeilen.append("Noch keine abgeschlossenen Trades.")
    zeilen += ["", "## Ereignisse", ""]
    for ts, text in reversed(z["ereignisse"][-10:]):
        zeilen.append(f"- {zeit(ts)}: {text}")
    top = sorted(z["universum"].values(), key=lambda i: -i["umsatz"])[:12]
    zeilen += ["", f"## Beobachtete Coins ({len(z['universum'])})", "",
               ", ".join(f"{i['coin']}" for i in top) + (" …" if len(z["universum"]) > 12 else ""), "",
               "Alle Kraken-Paare in Euro mit mindestens 250.000 € Tagesumsatz und höchstens 0,5 % Spread, "
               "ohne Stablecoins. Regeln: [krypto/STRATEGIEN.md](https://github.com/ftp2y8tcgy-max/Rich/blob/main/"
               "krypto/STRATEGIEN.md)", ""]
    return "\n".join(zeilen)


def svg(z, breite=640, hoehe=240):
    v = z["verlauf"]
    rand = 36
    teile = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {breite} {hoehe}" font-family="sans-serif" '
             f'font-size="11"><rect width="100%" height="100%" fill="#0d0c0a"/>']
    if len(v) >= 2:
        werte = [w for _, a, b in v for w in (a, b)] + [z["startkapital"]]
        lo, hi = min(werte) * 0.98, max(werte) * 1.02
        t0, t1 = v[0][0], v[-1][0] or 1

        def x(t):
            return rand + (t - t0) / max(1, t1 - t0) * (breite - 2 * rand)

        def y(w):
            return hoehe - rand + 10 - (w - lo) / (hi - lo or 1) * (hoehe - 2 * rand)

        start = z["startkapital"]
        teile.append(f'<line x1="{rand}" x2="{breite - rand}" y1="{y(start):.1f}" y2="{y(start):.1f}" '
                     f'stroke="#555" stroke-dasharray="3 4"/>')
        for idx, farbe, name in ((2, "#8a8a8a", "BTC halten"), (1, "#f4b740", "Bot")):
            pfad = " ".join(f"{'M' if i == 0 else 'L'}{x(p[0]):.1f},{y(p[idx]):.1f}" for i, p in enumerate(v))
            teile.append(f'<path d="{pfad}" fill="none" stroke="{farbe}" stroke-width="{2.4 if idx == 1 else 1.4}"/>')
        teile.append(f'<text x="{rand}" y="16" fill="#f4b740">— Bot {euro(v[-1][1])}</text>'
                     f'<text x="{rand + 150}" y="16" fill="#8a8a8a">— BTC halten {euro(v[-1][2])}</text>'
                     f'<text x="{breite - rand}" y="16" fill="#888" text-anchor="end">Start {euro(start)}</text>')
        for w in (lo, hi):
            teile.append(f'<text x="4" y="{y(w):.1f}" fill="#777">{w:.2f}</text>')
    else:
        teile.append('<text x="20" y="40" fill="#999">Noch zu wenig Daten</text>')
    teile.append("</svg>")
    return "".join(teile)
