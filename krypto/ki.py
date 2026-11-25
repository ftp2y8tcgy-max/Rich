"""KI-Händler: ein Sprachmodell entscheidet über eine OpenAI-kompatible Chat-Schnittstelle.

Standard ist Groq (kostenloses Kontingent) mit automatischer Modellwahl. Umstellbar über LLM_BASE_URL und LLM_MODEL;
der Schlüssel kommt nur aus der Umgebungsvariable LLM_API_KEY und wird nie ausgegeben.
Ungültige Antwort oder Ausfall bedeutet: halten.
"""

import json
import os
import re
import sys
import urllib.error
import urllib.request

from krypto.strategien import COINS, TREND_DURCHSCHNITT

HALTEN = "__halten__"
STANDARD_BASIS = "https://api.groq.com/openai/v1"
# Ohne LLM_MODEL wählt der Bot aus der Modellliste des Anbieters: erst passende Namen in dieser
# Reihenfolge, sonst das erste Chat-Modell. So überlebt er abgeschaltete Modelle.
MODELL_VORLIEBEN = ("gpt-oss-120b", "llama-4-maverick", "llama-3.3-70b", "70b", "gpt-oss", "llama")
KEIN_CHAT = ("whisper", "tts", "guard", "embed", "playai", "orpheus", "distil", "compound")
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


class KeinSchluessel(Exception):
    pass


def _anfrage(url, schluessel, daten=None):
    anfrage = urllib.request.Request(
        url,
        data=daten,
        headers={
            "Authorization": f"Bearer {schluessel}",
            "Content-Type": "application/json",
            # Cloudflare vor Groq sperrt den Standard-User-Agent von urllib (HTTP 403, error code 1010).
            "User-Agent": "krypto-wettrennen/1.0",
        },
    )
    with urllib.request.urlopen(anfrage, timeout=ZEITLIMIT) as antwort:
        return json.load(antwort)


def modell_waehlen(ids):
    chat = [m for m in ids if not any(w in m.lower() for w in KEIN_CHAT)]
    for vorliebe in MODELL_VORLIEBEN:
        treffer = sorted(m for m in chat if vorliebe in m.lower())
        if treffer:
            return treffer[0]
    if chat:
        return sorted(chat)[0]
    raise RuntimeError("kein Chat-Modell verfügbar")


def http_client(nachrichten):
    schluessel = os.environ.get("LLM_API_KEY")
    if not schluessel:
        raise KeinSchluessel()
    basis = (os.environ.get("LLM_BASE_URL") or STANDARD_BASIS).rstrip("/")
    modell = os.environ.get("LLM_MODEL")
    if not modell:
        liste = _anfrage(basis + "/models", schluessel)
        modell = modell_waehlen([m["id"] for m in liste.get("data", []) if m.get("active", True)])
    print(f"KI-Modell: {modell}", file=sys.stderr)
    daten = json.dumps({"model": modell, "messages": nachrichten, "temperature": 0}).encode()
    return _anfrage(basis + "/chat/completions", schluessel, daten)["choices"][0]["message"]["content"]


def _ausfall_text(fehler):
    """Kurzer Grund für den Bericht. Die Fehlermeldung des Anbieters geht nur ins Log, nie der Schlüssel."""
    if isinstance(fehler, KeinSchluessel):
        return "Ausfall: kein LLM_API_KEY hinterlegt"
    if isinstance(fehler, urllib.error.HTTPError):
        try:
            koerper = fehler.read().decode("utf-8", "replace")[:500]
        except Exception:
            koerper = ""
        print(f"KI-Anbieter antwortet HTTP {fehler.code}: {koerper}", file=sys.stderr)
        return f"Ausfall: HTTP {fehler.code}"
    return f"Ausfall: {type(fehler).__name__}"


def entscheiden(kurse, depot, zeit, client=http_client):
    """Liefert Ziel-Coin, None (Bargeld) oder HALTEN und vermerkt die Entscheidung im Depot."""
    nachrichten = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": eingabe(kurse, depot)}]
    try:
        antwort = client(nachrichten)
    except Exception as fehler:  # Netz, HTTP, Kontingent, fehlender Schlüssel: alles heißt halten
        depot["ki_ausfaelle"] += 1
        depot["letzte_entscheidung"] = {"zeit": zeit, "entscheidung": "halten", "begruendung": _ausfall_text(fehler)}
        return HALTEN
    gueltig, ziel, begruendung = auswerten(antwort)
    if not gueltig:
        depot["ki_ausfaelle"] += 1
        depot["letzte_entscheidung"] = {"zeit": zeit, "entscheidung": "halten", "begruendung": "Ausfall: ungültige Antwort", "antwort": (antwort or "")[:300]}
        return HALTEN
    text = "halten" if ziel == HALTEN else ("verkaufen" if ziel is None else f"kaufen {ziel}")
    depot["letzte_entscheidung"] = {"zeit": zeit, "entscheidung": text, "begruendung": begruendung}
    return ziel
