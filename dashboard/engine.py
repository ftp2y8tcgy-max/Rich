"""Das Rennen: 25 Bots handeln nach den Regeln des day-trader-skill auf echten Kursen.

Ablauf pro Handelstag (eine Aktie, 78 Fünf-Minuten-Kerzen):
  1. Eröffnungsspanne aus den ersten 5/15/30 Minuten (tm.opening_range)
  2. Einstieg beim ersten Schlusskurs über dem Hoch der Spanne (wie trader-entry und
     tm.history_replay), keine Einstiege nach 15:30
  3. Stop nach tm.rule_stop (Mitte oder Tief der Spanne oder Prozent), Ziel = Einstieg + R × Risiko
  4. Stop zuerst, dann Ziel, Kerze für Kerze; sonst glattstellen um 15:55 (trader-exit)
  Ein Trade pro Bot und Tag, nur Kauf, kein Hebel.

Abweichungen vom Skill-Paket, weil jedes Wallet nur 10 € hat:
  - Bruchstück-Aktien: der Bot setzt sein ganzes Guthaben ein (trader-budget kauft nur ganze Aktien)
  - Das Wallet rechnet in €, die Kurse sind in US-$; der Wechselkurs bleibt außen vor.
Nach den echten Tagen geht es mit simulierten Tagen weiter, die wie in der Time Machine
aus den eigenen Kerzen der Aktie gezogen werden (tm.build_pool); sie sind als „simuliert“ markiert.
"""

import itertools
import random
import threading
import time
import uuid
from collections import deque

from skill_bruecke import FLAT_SLOT, LETZTER_EINSTIEG, SESSION_BARS, tm

STARTKAPITAL = 10.0
ZIEL = 1000.0
LEER = 0.10
MAX_PUNKTE = 600            # Kontoverlauf je Bot (Tagesend-Werte), danach ausgedünnt
STANDARD_AKTIEN = ("TSLA", "NVDA", "AMD", "META", "PLTR")

# Fünf Regelprofile aus den Optionen von trader-entry und trader-exit
PROFILE = (
    {"name": "Lehrbuch", "kurz": "OR15 · Mitte · 2R", "or_minutes": 15, "stop_rule": "or_mid", "target_r": 2.0},
    {"name": "Reel", "kurz": "OR15 · Mitte · 1R", "or_minutes": 15, "stop_rule": "or_mid", "target_r": 1.0},
    {"name": "Früh", "kurz": "OR5 · Tief · 3R", "or_minutes": 5, "stop_rule": "or_low", "target_r": 3.0},
    {"name": "Geduld", "kurz": "OR30 · Mitte · 2R", "or_minutes": 30, "stop_rule": "or_mid", "target_r": 2.0},
    {"name": "Eng", "kurz": "OR15 · 0,5 % · 4R", "or_minutes": 15, "stop_rule": "pct", "stop_pct": 0.5,
     "target_r": 4.0},
)

LAEUFT, PAUSIERT, GESTOPPT = "Läuft", "Pausiert", "Gestoppt"
_TRADE_NR = itertools.count(1)  # Reihenfolge der Trades über alle Bots (für „Letzte Trades“)
ZIEL_ERREICHT, PLEITE = "Ziel erreicht", "Pleite"


class Markt:
    """Handelstage einer Aktie: zuerst echte, danach simulierte nach Art der Time Machine."""

    def __init__(self, sym, sitzungen, quelle, seed=19):
        if not sitzungen:
            raise ValueError(f"{sym}: keine vollen Handelstage")
        self.sym = sym
        self.quelle = quelle
        self.echt = sitzungen
        self.pool = tm.build_pool(sitzungen)
        # Eröffnungskerze relativ zum Vortagesschluss (die Time Machine startet erst nach dem Einstieg)
        self.luecken = [(d[0]["o"] / v[-1]["c"], d[0]["h"] / v[-1]["c"], d[0]["l"] / v[-1]["c"], d[0]["c"] / v[-1]["c"])
                        for (_, v), (_, d) in zip(sitzungen, sitzungen[1:])] or [(1, 1, 1, 1)]
        self.seed = seed
        self._sim = {}

    def tag(self, index):
        """(Bezeichnung, echt?, Kerzen) für Handelstag index (0 = erster echter Tag)."""
        if index < len(self.echt):
            datum, kerzen = self.echt[index]
            return datum, True, kerzen
        if index not in self._sim:
            vortag = self.tag(index - 1)[2]
            rng = random.Random(f"{self.seed}-{self.sym}-{index}")
            preis = vortag[-1]["c"]
            kerzen = []
            for i in range(SESSION_BARS):
                o, h, lo, c = rng.choice(self.luecken if i == 0 else self.pool[i])
                kerzen.append({"slot": i, "start": _uhr(i), "o": preis * o, "h": preis * h, "l": preis * lo,
                               "c": preis * c, "v": 0})
                preis = preis * c
            self._sim = {k: v for k, v in self._sim.items() if k >= index - 1}  # nur Vortag behalten
            self._sim[index] = kerzen
        return f"Sim-Tag {index - len(self.echt) + 1}", False, self._sim[index]


def _uhr(slot):
    m = tm.OPEN_MIN + 5 * slot
    return f"{m // 60:02d}:{m % 60:02d}"


class Bot:
    def __init__(self, bot_id, markt, profil, rng):
        self.id = bot_id
        self.markt = markt
        self.profil = profil
        self.regel = {k: profil[k] for k in ("or_minutes", "stop_rule", "target_r", "stop_pct") if k in profil}
        self._rng = rng
        self.zuruecksetzen()

    def zuruecksetzen(self):
        self.wallet_id = "W-" + uuid.UUID(int=self._rng.getrandbits(128)).hex[:8].upper()
        self.bargeld = STARTKAPITAL
        self.position = None
        self.trades = []
        self.status = None          # None, ZIEL_ERREICHT oder PLEITE
        self.modus = GESTOPPT
        self.wert = STARTKAPITAL
        self.verlauf = [(0, STARTKAPITAL)]
        self.tag_gehandelt = False
        self.spanne = None

    # ---------- Handel ----------

    def neuer_tag(self):
        self.tag_gehandelt = False
        self.spanne = None

    def kerze(self, k, kerzen, tag_text, ereignisse):
        """Verarbeitet Kerze k des Tages. Gibt nichts zurück; Ereignisse werden angehängt."""
        if self.status:
            return
        n = self.regel["or_minutes"] // 5
        b = kerzen[k]
        if self.position:
            p = self.position
            if b["l"] <= p["stop"]:
                self._schliessen(p["stop"], "Stop", b, tag_text, ereignisse)
            elif b["h"] >= p["ziel"]:
                self._schliessen(p["ziel"], "Ziel", b, tag_text, ereignisse)
            elif k >= FLAT_SLOT:
                self._schliessen(b["c"], "15:55", b, tag_text, ereignisse)
        elif (self.modus == LAEUFT and not self.tag_gehandelt and n <= k <= LETZTER_EINSTIEG):
            if self.spanne is None:
                self.spanne = tm.opening_range(kerzen, n)
            oh, ol = self.spanne
            if b["c"] > oh:
                self._eroeffnen(k, kerzen, oh, ol, tag_text, ereignisse)
        self.wert = self.bargeld + (self.position["anteile"] * b["c"] if self.position else 0.0)
        if self.wert < LEER and not self.position:
            self.status = PLEITE
            ereignisse.append(("pleite", self.id, f"💀 Bot {self.id} ist pleite."))

    def _eroeffnen(self, k, kerzen, oh, ol, tag_text, ereignisse):
        self.tag_gehandelt = True
        e = round(kerzen[k]["c"], 2)
        stop = tm.rule_stop(self.regel, oh, ol, e, True)
        risiko = e - stop
        if risiko <= 0:
            return
        ziel = round(e + self.regel["target_r"] * risiko, 2)
        anteile = self.bargeld / e
        self.position = {"einstieg": e, "stop": stop, "ziel": ziel, "anteile": anteile, "kerze": k,
                         "zeit": _uhr(k + 1), "tag": tag_text, "einsatz": self.bargeld,
                         "spanne": [round(oh, 2), round(ol, 2)]}
        self.bargeld = 0.0
        text = (f"Bot {self.id} kauft {_menge(anteile)} {self.markt.sym} zu {_usd(e)} "
                f"(Stop {_usd(stop)}, Ziel {_usd(ziel)})")
        ereignisse.append(("kauf", self.id, text))

    def _schliessen(self, preis, grund, b, tag_text, ereignisse):
        p = self.position
        erloes = p["anteile"] * preis
        ergebnis = erloes - p["einsatz"]
        r = (preis - p["einstieg"]) / (p["einstieg"] - p["stop"])
        self.bargeld = erloes
        self.position = None
        ende = _uhr(b["slot"] + 1) if "slot" in b else b["start"]
        self.trades.append({"nr": next(_TRADE_NR), "tag": tag_text, "zeit": p["zeit"], "ende": ende,
                            "aktie": self.markt.sym,
                            "menge": p["anteile"], "einstieg": p["einstieg"], "stop": p["stop"], "ziel": p["ziel"],
                            "ausstieg": preis, "grund": grund, "ergebnis": ergebnis, "r": round(r, 2),
                            "saldo": erloes})
        zeichen = "🏁" if grund == "Ziel" else ("🛑" if grund == "Stop" else "⏰")
        text = (f"{zeichen} Bot {self.id} verkauft {self.markt.sym} zu {_usd(preis)} "
                f"({grund}, {r:+.2f} R, {_eur(ergebnis, True)})")
        ereignisse.append(("verkauf", self.id, text))
        if erloes >= ZIEL:
            self.status = ZIEL_ERREICHT
            ereignisse.append(("ziel", self.id, f"🏆 Bot {self.id} hat 1.000 € erreicht!"))

    def tag_ende(self, tag_index):
        self.verlauf.append((tag_index + 1, round(self.wert, 4)))
        if len(self.verlauf) > MAX_PUNKTE:
            self.verlauf = self.verlauf[:1] + self.verlauf[1:-1:2] + self.verlauf[-1:]

    # ---------- Ausgabe ----------

    def anzeige_status(self):
        return self.status or self.modus

    def kompakt(self):
        return {"id": self.id, "wallet": self.wallet_id, "aktie": self.markt.sym, "profil": self.profil["name"],
                "regel": self.profil["kurz"], "saldo": round(self.wert, 4), "status": self.anzeige_status(),
                "modus": self.modus, "trades": len(self.trades), "offen": self.position is not None,
                "gewinner": sum(1 for t in self.trades if t["ergebnis"] > 0)}


class Rennen:
    """25 Bots, eine gemeinsame Uhr. Ein Schritt = eine Fünf-Minuten-Kerze für alle Aktien."""

    def __init__(self, maerkte, seed=7):
        self.maerkte = maerkte
        rng = random.Random(seed)
        self.bots = []
        for i, markt in enumerate(maerkte):
            for j, profil in enumerate(PROFILE):
                self.bots.append(Bot(i * len(PROFILE) + j + 1, markt, profil, rng))
        self.lock = threading.RLock()
        self.tempo = 40.0           # Kerzen pro Sekunde
        self.ereignisse = deque(maxlen=400)
        self.seq = 0
        self._zustand_neu()
        self._ende = threading.Event()
        self._thread = threading.Thread(target=self._schleife, daemon=True, name="Rennen")

    def _zustand_neu(self):
        self.tag_index = 0
        self.slot = 0
        self.laufzeit = 0.0
        self._seit = None
        self.rennen_nr = getattr(self, "rennen_nr", 0) + 1

    # ---------- Steuerung ----------

    def starten_thread(self):
        self._thread.start()

    def beenden(self):
        self._ende.set()

    def steuern(self, aktion, bot_id=None, wert=None):
        with self.lock:
            ziele = [b for b in self.bots if bot_id is None or b.id == bot_id]
            if aktion in ("start", "pause", "stop"):
                modus = {"start": LAEUFT, "pause": PAUSIERT, "stop": GESTOPPT}[aktion]
                for b in ziele:
                    b.modus = modus
                self._log("info", None, f"{'Alle Bots' if bot_id is None else f'Bot {bot_id}'}: {modus}")
            elif aktion == "umschalten" and bot_id is not None:
                for b in ziele:
                    b.modus = PAUSIERT if b.modus == LAEUFT else LAEUFT
            elif aktion == "reset":
                for b in self.bots:
                    b.zuruecksetzen()
                self._zustand_neu()
                self._log("info", None, f"Neues Rennen Nr. {self.rennen_nr}: alle Wallets wieder 10 €")
            elif aktion == "tempo" and wert is not None:
                self.tempo = max(1.0, min(2000.0, float(wert)))
            else:
                raise ValueError(f"unbekannte Aktion {aktion!r}")
            self._uhr()

    def _uhr(self):
        aktiv = any(b.modus == LAEUFT and not b.status for b in self.bots)
        if aktiv and self._seit is None:
            self._seit = time.time()
        elif not aktiv and self._seit is not None:
            self.laufzeit += time.time() - self._seit
            self._seit = None

    def aktiv(self):
        return any(b.modus == LAEUFT and not b.status for b in self.bots) or any(b.position for b in self.bots)

    # ---------- Takt ----------

    def schritt(self):
        """Eine Kerze für alle Bots. Nach der 15:55-Kerze beginnt der nächste Handelstag."""
        neu = []
        with self.lock:
            zeit = self.uhrzeit_text()  # Zeit der Kerze, bevor die Uhr weiterspringt
            tage = {m.sym: m.tag(self.tag_index) for m in self.maerkte}
            for bot in self.bots:
                text, _, kerzen = tage[bot.markt.sym]
                bot.kerze(self.slot, kerzen, text, neu)
            self.slot += 1
            if self.slot > FLAT_SLOT:
                for bot in self.bots:
                    bot.tag_ende(self.tag_index)
                    bot.neuer_tag()
                self.tag_index += 1
                self.slot = 0
            for art, bid, text in neu:
                self._log(art, bid, text, zeit)
            self._uhr()

    def _schleife(self):
        naechster = time.monotonic()
        while not self._ende.is_set():
            if not self.aktiv():
                time.sleep(0.1)
                naechster = time.monotonic()
                continue
            # bei hohem Tempo mehrere Kerzen pro Durchlauf, damit der Thread nicht nur schläft
            pro_schritt = max(1, int(self.tempo / 50))
            for _ in range(pro_schritt):
                self.schritt()
            naechster += pro_schritt / self.tempo
            pause = naechster - time.monotonic()
            if pause > 0:
                time.sleep(pause)
            else:
                naechster = time.monotonic()

    def _log(self, art, bot_id, text, zeit=None):
        self.seq += 1
        self.ereignisse.append({"seq": self.seq, "art": art, "bot": bot_id, "text": text,
                                "zeit": zeit or self.uhrzeit_text()})

    # ---------- Ausgabe ----------

    def uhrzeit_text(self):
        text, echt, _ = self.maerkte[0].tag(self.tag_index)
        return f"{text} {_uhr(self.slot + 1)}"

    def laufzeit_s(self):
        return self.laufzeit + (time.time() - self._seit if self._seit else 0)

    def schnappschuss(self, seit_seq=0):
        with self.lock:
            bots = [b.kompakt() for b in self.bots]
            salden = [b["saldo"] for b in bots]
            text, echt, kerzen = self.maerkte[0].tag(self.tag_index)
            profile = {}
            for b in self.bots:
                profile.setdefault(b.profil["name"], []).append(b.wert)
            return {
                "rennen": self.rennen_nr,
                "tag": self.tag_index + 1, "tag_text": text, "echt": echt,
                "echte_tage": min(len(m.echt) for m in self.maerkte),
                "uhr": _uhr(min(self.slot, SESSION_BARS - 1)), "slot": self.slot,
                "laufzeit": round(self.laufzeit_s()), "tempo": self.tempo,
                "gesamt": round(sum(salden), 2), "start": STARTKAPITAL * len(bots),
                "ziel": sum(1 for b in self.bots if b.status == ZIEL_ERREICHT),
                "pleite": sum(1 for b in self.bots if b.status == PLEITE),
                "offen": sum(1 for b in self.bots if b.position),
                "aktien": [{"sym": m.sym, "quelle": m.quelle, "echte_tage": len(m.echt),
                            "kurs": round(m.tag(self.tag_index)[2][min(self.slot, SESSION_BARS - 1)]["c"], 2)}
                           for m in self.maerkte],
                "profile": [{"name": p["name"], "kurz": p["kurz"],
                             "schnitt": round(sum(profile[p["name"]]) / len(profile[p["name"]]), 4)} for p in PROFILE],
                "bots": bots,
                "verlauf": {b.id: b.verlauf for b in self.bots},
                "trades": sorted((dict(t, bot=b.id) for b in self.bots for t in b.trades[-3:]),
                                 key=lambda t: t["nr"])[-8:],
                "ereignisse": [e for e in self.ereignisse if e["seq"] > seit_seq],
                "seq": self.seq,
            }

    def details(self, bot_id):
        with self.lock:
            bot = next(b for b in self.bots if b.id == bot_id)
            text, echt, kerzen = bot.markt.tag(self.tag_index)
            bis = min(self.slot, SESSION_BARS)
            return dict(bot.kompakt(), profil_kurz=bot.profil["kurz"], quelle=bot.markt.quelle,
                        tag_text=text, echt=echt, kerzen=[{k: (round(v, 2) if isinstance(v, float) else v)
                                                           for k, v in b.items()} for b in kerzen[:bis]],
                        position=bot.position, spanne=bot.spanne and [round(x, 2) for x in bot.spanne],
                        trades=bot.trades[-200:], verlauf=bot.verlauf)


def _menge(x):
    return f"{x:.4f}".replace(".", ",")


def _usd(x):
    return f"${x:,.2f}"


def _eur(x, vorzeichen=False):
    text = f"{abs(x):,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")
    return (("+" if x >= 0 else "−") + text) if vorzeichen else text
