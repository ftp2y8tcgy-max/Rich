"""KI-Händler: ein Sprachmodell entscheidet über eine OpenAI-kompatible Chat-Schnittstelle.

Standard ist Groq (kostenloses Kontingent). Umstellbar über LLM_BASE_URL und LLM_MODEL;
der Schlüssel kommt nur aus der Umgebungsvariable LLM_API_KEY und wird nie ausgegeben.
Ungültige Antwort oder Ausfall bedeutet: halten.
"""

import json
import os
import re
import urllib.request

from krypto.strategien import COINS, TREND_DURCHSCHNITT

HALTEN = "__halten__"
STANDARD_BASIS = "https://api.groq.com/openai/v1"
STANDARD_MODELL = "llama-3.3-70b-versatile"
ZEITLIMIT = 30

SYSTEM = (
    "Du bist ein Krypto-Händler in einem Spielgeld-Wettrennen. Ziel: das Depot so schnell wie möglich "
    "von 10 € auf 1.000 € bringen. Erlaubt ist nur: das ganze Depot in BTC, ETH oder SOL halten oder "
    "Bargeld. Kein Hebel. Jede Order kostet 0,1 % Gebühr. Antworte genau in zwei Zeilen:\n"
    "ENTSCHEIDUNG: kaufen BTC | kaufen ETH | kaufen SOL | verkaufen | halten\n"
    "BEGRÜNDUNG: <ein Satz>"
)


def _prozent(a, b):
    return (a / b - 1) * 100


def eingabe(kurse, depot):
    zeilen = []
    for coin in COINS:
        r = kurse[coin]
        teile = [f"{coin}: {r[-1]:.2f} €"]
        if len(r) > 1:
            teile.append(f"1h {_prozent(r[-1], r[-2]):+.2f} %")
        if len(r) > 6:
            teile.append(f"6h {_prozent(r[-1], r[-7]):+.2f} %")
        if len(r) > 24:
            teile.append(f"24h {_prozent(r[-1], r[-25]):+.2f} %")
        if len(r) >= TREND_DURCHSCHNITT:
            schnitt = sum(r[-TREND_DURCHSCHNITT:]) / TREND_DURCHSCHNITT
            teile.append(f"Abstand zum 48h-Schnitt {_prozent(r[-1], schnitt):+.2f} %")
        zeilen.append(", ".join(teile))
    bestand = depot["coin"] or "Bargeld"
    zeilen.append(f"Dein Depot: {depot['wert']:.2f} €, aktuell in {bestand}.")
    return "\n".join(zeilen)


_ENTSCHEIDUNG = re.compile(r"ENTSCHEIDUNG:\s*(kaufen\s+(BTC|ETH|SOL)|verkaufen|halten)\b", re.IGNORECASE)
_BEGRUENDUNG = re.compile(r"BEGR(?:Ü|UE)NDUNG:\s*(.+)", re.IGNORECASE)


def auswerten(antwort):
    """Antworttext → (gültig, Ziel, Begründung). Ziel: Coin, None (Bargeld) oder HALTEN."""
    m = _ENTSCHEIDUNG.search(antwort or "")
    if not m:
        return False, None, None
    wort = m.group(1).lower()
    if wort.startswith("kaufen"):
        ziel = m.group(2).upper()
    elif wort == "verkaufen":
        ziel = None
    else:
        ziel = HALTEN
    b = _BEGRUENDUNG.search(antwort)
    return True, ziel, (b.group(1).strip()[:300] if b else "")


def http_client(nachrichten):
    schluessel = os.environ.get("LLM_API_KEY")
    if not schluessel:
        raise RuntimeError("kein LLM_API_KEY gesetzt")
    basis = os.environ.get("LLM_BASE_URL") or STANDARD_BASIS
    modell = os.environ.get("LLM_MODEL") or STANDARD_MODELL
    daten = json.dumps({"model": modell, "messages": nachrichten, "temperature": 0}).encode()
    anfrage = urllib.request.Request(
        basis.rstrip("/") + "/chat/completions",
        data=daten,
        headers={"Authorization": f"Bearer {schluessel}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(anfrage, timeout=ZEITLIMIT) as antwort:
        return json.load(antwort)["choices"][0]["message"]["content"]


def entscheiden(kurse, depot, zeit, client=http_client):
    """Liefert Ziel-Coin, None (Bargeld) oder HALTEN und vermerkt die Entscheidung im Depot."""
    nachrichten = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": eingabe(kurse, depot)}]
    try:
        antwort = client(nachrichten)
    except Exception as fehler:  # Netz, HTTP, Kontingent, fehlender Schlüssel: alles heißt halten
        depot["ki_ausfaelle"] += 1
        depot["letzte_entscheidung"] = {"zeit": zeit, "entscheidung": "halten", "begruendung": f"Ausfall: {type(fehler).__name__}"}
        return HALTEN
    gueltig, ziel, begruendung = auswerten(antwort)
    if not gueltig:
        depot["ki_ausfaelle"] += 1
        depot["letzte_entscheidung"] = {"zeit": zeit, "entscheidung": "halten", "begruendung": "Ausfall: ungültige Antwort", "antwort": (antwort or "")[:300]}
        return HALTEN
    text = "halten" if ziel == HALTEN else ("verkaufen" if ziel is None else f"kaufen {ziel}")
    depot["letzte_entscheidung"] = {"zeit": zeit, "entscheidung": text, "begruendung": begruendung}
    return ziel
