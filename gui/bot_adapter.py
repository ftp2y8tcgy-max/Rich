"""Schnittstelle zwischen einer Bot-Klasse und der GUI.

Jeder Bot läuft in einem eigenen Thread. Die GUI ruft den Bot nie direkt auf:
Befehle (Start, Pause, Stopp, Zurücksetzen) setzen nur Thread-sichere Flags, und
Zustände kommen ausschließlich über eine queue.Queue zur GUI.

Eine Bot-Klasse passt, wenn sie drei Methoden hat:
    step()      -> führt genau einen Handelsschritt aus
    get_state() -> dict mit id, wallet_id, balance, trades, status, history
    reset()     -> setzt das Wallet auf 10 € zurück (optional)

Heißen die Methoden bei deinem Bot anders, leite von BotAdapter ab und
überschreibe _schritt(), _zustand() und _zuruecksetzen().
"""

import threading
import time

# Status, die der Adapter selbst vergibt
LAEUFT = "Läuft"
PAUSIERT = "Pausiert"
GESTOPPT = "Gestoppt"
# Status, die der Bot selbst meldet (Endzustände)
ZIEL = "Ziel erreicht"
PLEITE = "Pleite"

STARTKAPITAL = 10.0
ZIELKAPITAL = 1000.0

# Statuswerte deines Bots, die auf die GUI-Endzustände abgebildet werden
_ZIEL_WOERTER = {"ziel", "ziel erreicht", "goal", "target", "won"}
_PLEITE_WOERTER = {"pleite", "bankrott", "broke", "bankrupt", "leer"}


class Einstellungen:
    """Gemeinsame Einstellungen aller Bots (z. B. Update-Intervall)."""

    def __init__(self, intervall_ms=300):
        self._lock = threading.Lock()
        self._intervall_ms = intervall_ms

    @property
    def intervall_ms(self):
        with self._lock:
            return self._intervall_ms

    @intervall_ms.setter
    def intervall_ms(self, wert):
        with self._lock:
            self._intervall_ms = max(10, int(wert))


class BotAdapter:
    """Hängt einen Bot in einen Thread und meldet seinen Zustand an die GUI-Queue.

    Nachrichten in der Queue sind Tupel:
        ("zustand", bot_id, zustand_dict)
        ("ereignis", bot_id, text)
    """

    def __init__(self, bot, gui_queue, einstellungen):
        self.bot = bot
        self.queue = gui_queue
        self.einstellungen = einstellungen
        self.bot_id = self._zustand()["id"]

        self._laeuft = threading.Event()      # gesetzt = Bot handelt
        self._beenden = threading.Event()     # gesetzt = Thread endet
        self._reset_angefordert = threading.Event()
        self._modus = GESTOPPT                # Läuft / Pausiert / Gestoppt
        self._modus_lock = threading.Lock()
        self._thread = threading.Thread(target=self._schleife, name=f"Bot-{self.bot_id}", daemon=True)

    # ---------- Anpassungspunkte für deine Bot-Klasse ----------

    def _schritt(self):
        """Einen Handelsschritt deines Bots ausführen."""
        self.bot.step()

    def _zustand(self):
        """Zustand deines Bots als dict liefern."""
        return self.bot.get_state()

    def _zuruecksetzen(self):
        """Wallet deines Bots auf 10 € zurücksetzen."""
        if hasattr(self.bot, "reset"):
            self.bot.reset()

    # ---------- Steuerung (aus dem GUI-Thread aufrufbar) ----------

    def thread_starten(self):
        """Startet den Hintergrund-Thread einmalig (der Bot handelt erst nach starten())."""
        self._thread.start()
        self._melden()

    def starten(self):
        self._modus_setzen(LAEUFT)
        self._laeuft.set()

    def pausieren(self):
        self._modus_setzen(PAUSIERT)
        self._laeuft.clear()

    def stoppen(self):
        self._modus_setzen(GESTOPPT)
        self._laeuft.clear()

    def zuruecksetzen(self):
        """Fordert ein Zurücksetzen an; ausgeführt wird es im Bot-Thread."""
        self._reset_angefordert.set()

    def beenden(self):
        """Beendet den Thread endgültig (beim Schließen des Fensters)."""
        self._beenden.set()
        self._laeuft.set()  # aus dem Warten wecken

    @property
    def modus(self):
        with self._modus_lock:
            return self._modus

    # ---------- intern ----------

    def _modus_setzen(self, modus):
        with self._modus_lock:
            self._modus = modus
        self._melden_modus()

    def _melden_modus(self):
        self.queue.put(("modus", self.bot_id, self.modus))

    def _schleife(self):
        trades_bisher = len(self._zustand().get("trades", []))
        endstatus_gemeldet = None
        while not self._beenden.is_set():
            if self._reset_angefordert.is_set():
                self._reset_angefordert.clear()
                self._zuruecksetzen()
                trades_bisher = 0
                endstatus_gemeldet = None
                text = f"Bot {self.bot_id} wurde auf 10 € zurückgesetzt."
                self.queue.put(("ereignis", self.bot_id, text))
                self._melden()

            # Warten, bis der Bot laufen soll (kurzes Timeout, damit Reset/Beenden ankommen)
            if not self._laeuft.wait(timeout=0.2):
                continue
            if self._beenden.is_set():
                break

            zustand = self._zustand()
            endstatus = normalisieren(zustand.get("status"))
            if endstatus in (ZIEL, PLEITE):
                # Endzustand: nicht weiter handeln, aber den Thread für Reset offen halten
                time.sleep(self.einstellungen.intervall_ms / 1000)
                continue

            try:
                self._schritt()
            except Exception as fehler:  # ein abstürzender Bot darf die anderen nicht stören
                text = f"Bot {self.bot_id}: Fehler {type(fehler).__name__}: {fehler}"
                self.queue.put(("ereignis", self.bot_id, text))
                self.pausieren()
                continue

            zustand = self._melden()
            trades = zustand.get("trades", [])
            for trade in trades[trades_bisher:]:
                self.queue.put(("ereignis", self.bot_id, trade_text(self.bot_id, trade)))
            trades_bisher = len(trades)

            endstatus = normalisieren(zustand.get("status"))
            if endstatus != endstatus_gemeldet and endstatus == ZIEL:
                self.queue.put(("ereignis", self.bot_id, f"🏁 Bot {self.bot_id} hat 1000 € erreicht!"))
            elif endstatus != endstatus_gemeldet and endstatus == PLEITE:
                self.queue.put(("ereignis", self.bot_id, f"💀 Bot {self.bot_id} ist pleite."))
            endstatus_gemeldet = endstatus

            time.sleep(self.einstellungen.intervall_ms / 1000)

    def _melden(self):
        """Kopie des Zustands an die GUI schicken (die GUI bekommt nie das Original).

        Bewusst flach kopiert statt deepcopy: Listen werden neu angelegt, die
        Einträge (Trade-Dicts, Historien-Tupel) geteilt. Dein Bot darf deshalb
        einen einmal angehängten Trade nicht nachträglich verändern.
        """
        original = self._zustand()
        zustand = dict(original)
        zustand["trades"] = list(original.get("trades", []))
        zustand["history"] = list(original.get("history", []))
        self.queue.put(("zustand", self.bot_id, zustand))
        return zustand


def normalisieren(status):
    """Statuswort deines Bots auf ZIEL / PLEITE abbilden, sonst None."""
    wort = str(status or "").strip().lower()
    if wort in _ZIEL_WOERTER:
        return ZIEL
    if wort in _PLEITE_WOERTER:
        return PLEITE
    return None


def trade_text(bot_id, trade):
    """Lesbarer Log-Text für einen Trade."""
    typ = trade.get("typ", "?")
    verb = "kauft" if typ.lower().startswith("kauf") else "verkauft"
    menge = menge_text(trade.get("menge", 0))
    text = f"Bot {bot_id} {verb} {menge} {trade.get('asset', '?')} zu {_euro(trade.get('preis', 0))}"
    if trade.get("ergebnis") is not None:
        text += f" (Ergebnis {'+' if trade['ergebnis'] >= 0 else '−'}{_euro(abs(trade['ergebnis']))})"
    return text


def menge_text(menge):
    """Menge ohne wissenschaftliche Schreibweise, deutsches Komma, z. B. 0,00007722."""
    text = f"{menge:.8f}".rstrip("0").rstrip(".") if menge < 1000 else f"{menge:,.2f}"
    return text.replace(",", "X").replace(".", ",").replace("X", ".")


def _euro(betrag):
    return f"{betrag:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")
