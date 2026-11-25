"""Tkinter-Oberfläche für 25 gleichzeitig laufende Trading-Bots.

Die GUI liest Bot-Zustände ausschließlich aus einer queue.Queue und
aktualisiert sich per root.after(). Sie ruft keine Bot-Methoden direkt auf,
sondern nur die Thread-sicheren Steuerbefehle der BotAdapter.
"""

import math
import queue
import time
import tkinter as tk
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText

import matplotlib

matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

from bot_adapter import (  # noqa: E402
    GESTOPPT, LAEUFT, PLEITE, STARTKAPITAL, ZIEL, ZIELKAPITAL, menge_text, normalisieren,
)

# Farben der Kacheln
FARBE_PLUS = "#cdeccf"
FARBE_MINUS = "#f6c9cc"
FARBE_ZIEL = "#f5c542"
FARBE_LEER = "#c8c8c8"
FARBE_NEUTRAL = "#eeeeee"
FARBE_AUSWAHL = "#1f5fbf"

QUEUE_TAKT_MS = 100     # wie oft die Queue gelesen wird
QUEUE_BUDGET_S = 0.04   # höchstens so lange pro Takt Nachrichten lesen, damit die GUI flüssig bleibt
LOG_PRO_TAKT = 200      # mehr Ereignisse pro Takt werden zusammengefasst
CHART_TAKT_MS = 700     # wie oft der Chart neu gezeichnet wird
LOG_MAX_ZEILEN = 1000


def euro(betrag):
    """Betrag im deutschen Format, z. B. 1.234,56 €."""
    return f"{betrag:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def prozent(wert):
    return f"{wert:+.1f} %".replace(".", ",")


def fortschritt(saldo):
    """Fortschritt 10 € → 1000 € auf logarithmischer Skala (0–100).

    Linear wären 10 € → 100 € nur 9 % des Balkens; logarithmisch ist jede
    Verzehnfachung gleich lang (10 → 100 € = halber Balken).
    """
    if saldo <= STARTKAPITAL:
        return 0.0
    return min(100.0, 100 * math.log(saldo / STARTKAPITAL) / math.log(ZIELKAPITAL / STARTKAPITAL))


def anzeige_status(zustand, modus):
    """Status für die Anzeige: Endzustände des Bots haben Vorrang vor dem Modus."""
    endstatus = normalisieren(zustand.get("status"))
    return endstatus or modus


def kachel_farbe(zustand, status):
    if status == ZIEL:
        return FARBE_ZIEL
    if status == PLEITE:
        return FARBE_LEER
    saldo = zustand.get("balance", STARTKAPITAL)
    if saldo > STARTKAPITAL + 1e-9:
        return FARBE_PLUS
    if saldo < STARTKAPITAL - 1e-9:
        return FARBE_MINUS
    return FARBE_NEUTRAL


class BotKachel(tk.Frame):
    """Eine Kachel im 5×5-Raster."""

    def __init__(self, master, bot_id, bei_klick, bei_doppelklick, bei_umschalten):
        super().__init__(master, bd=1, relief="solid", highlightthickness=3,
                         highlightbackground=FARBE_NEUTRAL, padx=4, pady=2)
        self.bot_id = bot_id
        self._umschalten = bei_umschalten
        self._letzte = {}  # zuletzt gesetzte Werte, um unnötige Tk-Aufrufe zu sparen

        self.titel = tk.Label(self, text=f"Bot {bot_id}", font=("TkDefaultFont", 10, "bold"))
        self.wallet = tk.Label(self, text="Wallet –", font=("TkDefaultFont", 8))
        self.saldo = tk.Label(self, text=euro(STARTKAPITAL), font=("TkDefaultFont", 12, "bold"))
        self.prozent = tk.Label(self, text=prozent(0), font=("TkDefaultFont", 9))
        self.balken = ttk.Progressbar(self, length=110, maximum=100, mode="determinate")
        self.status = tk.Label(self, text=GESTOPPT, font=("TkDefaultFont", 8))
        self.trades = tk.Label(self, text="0 Trades", font=("TkDefaultFont", 8))
        self.knopf = ttk.Button(self, text="▶ Start", width=8, command=lambda: self._umschalten(self.bot_id))

        self.titel.grid(row=0, column=0, sticky="w")
        self.wallet.grid(row=0, column=1, sticky="e")
        self.saldo.grid(row=1, column=0, sticky="w")
        self.prozent.grid(row=1, column=1, sticky="e")
        self.balken.grid(row=2, column=0, columnspan=2, sticky="ew", pady=2)
        self.status.grid(row=3, column=0, sticky="w")
        self.trades.grid(row=3, column=1, sticky="e")
        self.knopf.grid(row=4, column=0, columnspan=2, sticky="ew")
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)

        # Klick hebt die Linie im Chart hervor, Doppelklick öffnet die Details
        for widget in (self, self.titel, self.wallet, self.saldo, self.prozent,
                       self.balken, self.status, self.trades):
            widget.bind("<Button-1>", lambda e: bei_klick(self.bot_id))
            widget.bind("<Double-Button-1>", lambda e: bei_doppelklick(self.bot_id))

    def aktualisieren(self, zustand, modus, ausgewaehlt):
        saldo = zustand.get("balance", STARTKAPITAL)
        status = anzeige_status(zustand, modus)
        farbe = kachel_farbe(zustand, status)

        self._setzen(self.wallet, "text", zustand.get("wallet_id", "–"))
        self._setzen(self.saldo, "text", euro(saldo))
        self._setzen(self.prozent, "text", prozent((saldo / STARTKAPITAL - 1) * 100))
        self._setzen(self.balken, "value", round(fortschritt(saldo), 1))
        self._setzen(self.status, "text", status)
        self._setzen(self.trades, "text", f"{len(zustand.get('trades', []))} Trades")
        self._setzen(self.knopf, "text", "⏸ Pause" if modus == LAEUFT else "▶ Start")
        self._setzen(self.knopf, "state", "disabled" if status in (ZIEL, PLEITE) else "normal")
        for widget in (self, self.titel, self.wallet, self.saldo, self.prozent, self.status, self.trades):
            self._setzen(widget, "bg", farbe)
        self._setzen(self, "highlightbackground", FARBE_AUSWAHL if ausgewaehlt else farbe)

    def _setzen(self, widget, option, wert):
        """Option nur setzen, wenn sie sich geändert hat (Tk-Aufrufe sind teuer)."""
        schluessel = (id(widget), option)
        if self._letzte.get(schluessel) != wert:
            widget[option] = wert
            self._letzte[schluessel] = wert


class DetailFenster(tk.Toplevel):
    """Detailansicht eines Bots: Trade-Historie und Einzelchart."""

    SPALTEN = (("zeit", "Zeit", 70), ("typ", "Kauf/Verkauf", 90), ("asset", "Asset", 60),
               ("menge", "Menge", 110), ("preis", "Preis", 110), ("ergebnis", "Ergebnis", 90))

    def __init__(self, master, bot_id, beim_schliessen):
        super().__init__(master)
        self.bot_id = bot_id
        self.title(f"Bot {bot_id} – Details")
        self.geometry("720x620")
        self._beim_schliessen = beim_schliessen
        self._angezeigte_trades = 0
        self.protocol("WM_DELETE_WINDOW", self.schliessen)

        self.kopf = tk.Label(self, text=f"Bot {bot_id}", font=("TkDefaultFont", 12, "bold"), anchor="w")
        self.kopf.pack(fill="x", padx=8, pady=(8, 4))

        # Einzelchart des Kontostands
        self.figur = Figure(figsize=(6.5, 2.6), dpi=100)
        self.achse = self.figur.add_subplot(111)
        self.linie, = self.achse.plot([], [], color=FARBE_AUSWAHL)
        self.achse.axhline(ZIELKAPITAL, color="goldenrod", linestyle="--", linewidth=1)
        self.achse.set_ylim(0.1, 2000)
        self.achse.set_yscale("log")
        self.achse.set_ylabel("Kontostand (€)")
        self.achse.set_xlabel("Sekunden seit Start")
        self.figur.tight_layout()
        self.canvas = FigureCanvasTkAgg(self.figur, master=self)
        self.canvas.get_tk_widget().pack(fill="x", padx=8)

        # Trade-Historie als Tabelle
        rahmen = ttk.Frame(self)
        rahmen.pack(fill="both", expand=True, padx=8, pady=8)
        self.tabelle = ttk.Treeview(rahmen, columns=[s[0] for s in self.SPALTEN], show="headings")
        for schluessel, titel, breite in self.SPALTEN:
            self.tabelle.heading(schluessel, text=titel)
            rechts = schluessel in ("menge", "preis", "ergebnis")
            self.tabelle.column(schluessel, width=breite, anchor="e" if rechts else "w")
        rollbalken = ttk.Scrollbar(rahmen, orient="vertical", command=self.tabelle.yview)
        self.tabelle.configure(yscrollcommand=rollbalken.set)
        self.tabelle.pack(side="left", fill="both", expand=True)
        rollbalken.pack(side="right", fill="y")
        self.tabelle.tag_configure("plus", foreground="#1b7a33")
        self.tabelle.tag_configure("minus", foreground="#b3261e")

    def aktualisieren(self, zustand, modus):
        saldo = zustand.get("balance", STARTKAPITAL)
        self.kopf.config(text=f"Bot {self.bot_id} · {zustand.get('wallet_id', '–')} · {euro(saldo)} · "
                              f"{anzeige_status(zustand, modus)}")

        trades = zustand.get("trades", [])
        if len(trades) < self._angezeigte_trades:  # nach Zurücksetzen neu aufbauen
            self.tabelle.delete(*self.tabelle.get_children())
            self._angezeigte_trades = 0
        for trade in trades[self._angezeigte_trades:]:
            ergebnis = trade.get("ergebnis")
            tag = () if ergebnis is None else (("plus",) if ergebnis >= 0 else ("minus",))
            self.tabelle.insert("", 0, tags=tag, values=(
                trade.get("zeit", ""),
                trade.get("typ", ""),
                trade.get("asset", ""),
                menge_text(trade.get("menge", 0)),
                euro(trade.get("preis", 0)),
                "–" if ergebnis is None else euro(ergebnis),
            ))
        self._angezeigte_trades = len(trades)

        historie = zustand.get("history", [])
        if historie:
            xs, ys = zip(*historie)
            self.linie.set_data(xs, [max(y, 0.01) for y in ys])
            self.achse.relim()
            self.achse.autoscale_view()
            self.canvas.draw_idle()

    def schliessen(self):
        self._beim_schliessen(self.bot_id)
        self.destroy()


class TradingGUI:
    """Hauptfenster mit Gesamtübersicht, 5×5-Kacheln, Live-Chart, Steuerung und Log."""

    def __init__(self, root, adapter, gui_queue, einstellungen):
        self.root = root
        self.adapter = {a.bot_id: a for a in adapter}
        self.queue = gui_queue
        self.einstellungen = einstellungen

        self.zustaende = {}                       # bot_id -> letzter Zustand
        self.modi = {bid: GESTOPPT for bid in self.adapter}
        self.geaendert = set()                    # Bots mit neuem Zustand seit der letzten Anzeige
        self.chart_geaendert = False
        self.ausgewaehlt = None
        self.details = {}                         # bot_id -> DetailFenster
        self.laufzeit = 0.0                       # Sekunden, in denen mindestens ein Bot lief
        self._laufzeit_seit = None

        root.title("Trading-Bots: 25 × 10 € → 1.000 €")
        root.geometry("1450x930")
        root.protocol("WM_DELETE_WINDOW", self.beenden)

        self._uebersicht_bauen()
        self._mitte_bauen()
        self._steuerung_bauen()
        self._log_bauen()

        self.root.after(QUEUE_TAKT_MS, self._queue_abarbeiten)
        self.root.after(CHART_TAKT_MS, self._chart_zeichnen)
        self.root.after(500, self._uhr)

    # ---------- Aufbau ----------

    def _uebersicht_bauen(self):
        rahmen = ttk.Frame(self.root, padding=(10, 6))
        rahmen.pack(fill="x")
        self.ue = {}
        felder = [("gesamt", "Gesamtkapital"), ("bester", "Bester Bot"), ("schlechtester", "Schlechtester Bot"),
                  ("ziel", "Ziel erreicht"), ("pleite", "Pleite"), ("laufzeit", "Laufzeit")]
        for spalte, (schluessel, titel) in enumerate(felder):
            feld = ttk.Frame(rahmen, padding=(12, 0))
            feld.grid(row=0, column=spalte, sticky="w")
            ttk.Label(feld, text=titel, foreground="#555").pack(anchor="w")
            self.ue[schluessel] = ttk.Label(feld, text="–", font=("TkDefaultFont", 13, "bold"))
            self.ue[schluessel].pack(anchor="w")

    def _mitte_bauen(self):
        mitte = ttk.PanedWindow(self.root, orient="horizontal")
        mitte.pack(fill="both", expand=True, padx=8)

        raster = ttk.Frame(mitte)
        self.kacheln = {}
        for index, bot_id in enumerate(self.adapter):
            kachel = BotKachel(raster, bot_id, self.auswaehlen, self.details_oeffnen, self.umschalten)
            kachel.grid(row=index // 5, column=index % 5, padx=3, pady=3, sticky="nsew")
            self.kacheln[bot_id] = kachel
        for i in range(5):
            raster.columnconfigure(i, weight=1)
            raster.rowconfigure(i, weight=1)
        mitte.add(raster, weight=3)

        chart_rahmen = ttk.Frame(mitte)
        self.figur = Figure(figsize=(6, 5), dpi=100)
        self.achse = self.figur.add_subplot(111)
        self.achse.set_title("Kontoverlauf aller Bots")
        self.achse.set_ylim(0.1, 2000)
        self.achse.set_yscale("log")
        self.achse.set_ylabel("Kontostand (€, log)")
        self.achse.set_xlabel("Sekunden seit Start")
        self.achse.axhline(ZIELKAPITAL, color="goldenrod", linestyle="--", linewidth=1.5, label="Ziel 1.000 €")
        self.achse.axhline(STARTKAPITAL, color="#888", linestyle=":", linewidth=1)
        self.linien = {}
        farben = matplotlib.colormaps["tab20"].colors + matplotlib.colormaps["tab20b"].colors
        for index, bot_id in enumerate(self.adapter):
            self.linien[bot_id], = self.achse.plot([], [], linewidth=1, alpha=0.8,
                                                   color=farben[index % len(farben)])
        self.achse.legend(loc="upper left", fontsize=8)
        self.figur.tight_layout()
        self.canvas = FigureCanvasTkAgg(self.figur, master=chart_rahmen)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        mitte.add(chart_rahmen, weight=2)

    def _steuerung_bauen(self):
        rahmen = ttk.Frame(self.root, padding=(10, 6))
        rahmen.pack(fill="x")
        ttk.Button(rahmen, text="▶ Alle starten", command=self.alle_starten).pack(side="left", padx=3)
        ttk.Button(rahmen, text="⏸ Alle pausieren", command=self.alle_pausieren).pack(side="left", padx=3)
        ttk.Button(rahmen, text="⏹ Alle stoppen", command=self.alle_stoppen).pack(side="left", padx=3)
        ttk.Button(rahmen, text="↺ Zurücksetzen", command=self.alle_zuruecksetzen).pack(side="left", padx=3)

        self.intervall_text = ttk.Label(rahmen, width=26)
        self.intervall_text.pack(side="right", padx=6)
        self.regler = tk.Scale(rahmen, from_=20, to=2000, orient="horizontal", length=260, showvalue=False,
                               command=self._intervall_geaendert)
        self.regler.set(self.einstellungen.intervall_ms)
        self.regler.pack(side="right")
        ttk.Label(rahmen, text="schnell").pack(side="right", padx=(10, 2))

    def _log_bauen(self):
        rahmen = ttk.Frame(self.root, padding=(10, 0, 10, 8))
        rahmen.pack(fill="x")
        ttk.Label(rahmen, text="Ereignisse").pack(anchor="w")
        self.log = ScrolledText(rahmen, height=8, state="disabled", font=("TkFixedFont", 9))
        self.log.pack(fill="x")

    # ---------- Steuerung ----------

    def alle_starten(self):
        for a in self.adapter.values():
            a.starten()
        self.log_schreiben("Alle Bots gestartet.")

    def alle_pausieren(self):
        for a in self.adapter.values():
            a.pausieren()
        self.log_schreiben("Alle Bots pausiert.")

    def alle_stoppen(self):
        for a in self.adapter.values():
            a.stoppen()
        self.log_schreiben("Alle Bots gestoppt.")

    def alle_zuruecksetzen(self):
        if not messagebox.askyesno("Zurücksetzen", "Alle Bots auf 10 € zurücksetzen? Die Historie geht verloren."):
            return
        for a in self.adapter.values():
            a.zuruecksetzen()
        self.laufzeit = 0.0
        self._laufzeit_seit = time.time() if self._laeuft_einer() else None
        self.log_schreiben("Alle Bots werden auf 10 € zurückgesetzt.")

    def umschalten(self, bot_id):
        adapter = self.adapter[bot_id]
        if adapter.modus == LAEUFT:
            adapter.pausieren()
        else:
            adapter.starten()

    def _intervall_geaendert(self, wert):
        self.einstellungen.intervall_ms = int(float(wert))
        self.intervall_text.config(text=f"Update-Intervall: {self.einstellungen.intervall_ms} ms")

    # ---------- Auswahl und Details ----------

    def auswaehlen(self, bot_id):
        self.ausgewaehlt = None if self.ausgewaehlt == bot_id else bot_id
        for bid, linie in self.linien.items():
            if self.ausgewaehlt is None:
                linie.set_linewidth(1)
                linie.set_alpha(0.8)
            elif bid == self.ausgewaehlt:
                linie.set_linewidth(3)
                linie.set_alpha(1.0)
                linie.set_zorder(10)
            else:
                linie.set_linewidth(0.8)
                linie.set_alpha(0.15)
                linie.set_zorder(1)
        self.geaendert.update(self.adapter)  # Rahmen der Kacheln neu setzen
        self.canvas.draw_idle()              # Hervorhebung sofort zeigen

    def details_oeffnen(self, bot_id):
        fenster = self.details.get(bot_id)
        if fenster is not None:
            fenster.lift()
            return
        fenster = DetailFenster(self.root, bot_id, self.details.pop)
        self.details[bot_id] = fenster
        if bot_id in self.zustaende:
            fenster.aktualisieren(self.zustaende[bot_id], self.modi[bot_id])

    # ---------- Takt ----------

    def _queue_abarbeiten(self):
        """Nachrichten der Bot-Threads lesen (nie blockierend) und die Anzeige aktualisieren."""
        ereignisse = []
        frist = time.monotonic() + QUEUE_BUDGET_S
        try:
            while time.monotonic() < frist:
                art, bot_id, inhalt = self.queue.get_nowait()
                if art == "zustand":
                    self.zustaende[bot_id] = inhalt
                    self.geaendert.add(bot_id)
                    self.chart_geaendert = True
                elif art == "modus":
                    self.modi[bot_id] = inhalt
                    self.geaendert.add(bot_id)
                    self._laufzeit_pruefen()
                elif art == "ereignis":
                    ereignisse.append(inhalt)
        except queue.Empty:
            pass
        if ereignisse:
            self.log_schreiben(*ereignisse)

        for bot_id in self.geaendert:
            if bot_id in self.zustaende:
                self.kacheln[bot_id].aktualisieren(self.zustaende[bot_id], self.modi[bot_id],
                                                   bot_id == self.ausgewaehlt)
                if bot_id in self.details:
                    self.details[bot_id].aktualisieren(self.zustaende[bot_id], self.modi[bot_id])
        if self.geaendert:
            self._uebersicht_aktualisieren()
        self.geaendert.clear()
        self.root.after(QUEUE_TAKT_MS, self._queue_abarbeiten)

    def _chart_zeichnen(self):
        if self.chart_geaendert:
            x_max = 1.0
            for bot_id, zustand in self.zustaende.items():
                historie = zustand.get("history", [])
                if historie:
                    xs, ys = zip(*historie)
                    # log-Skala verträgt keine 0: leere Wallets bei 0,1 € zeichnen
                    self.linien[bot_id].set_data(xs, [max(y, 0.1) for y in ys])
                    x_max = max(x_max, xs[-1])
            self.achse.set_xlim(0, x_max * 1.02)
            self.canvas.draw_idle()
            self.chart_geaendert = False
        self.root.after(CHART_TAKT_MS, self._chart_zeichnen)

    def _uebersicht_aktualisieren(self):
        if not self.zustaende:
            return
        salden = {bid: z.get("balance", 0.0) for bid, z in self.zustaende.items()}
        gesamt = sum(salden.values())
        start = STARTKAPITAL * len(self.adapter)
        bester = max(salden, key=salden.get)
        schlechtester = min(salden, key=salden.get)
        ziele = sum(1 for z in self.zustaende.values() if normalisieren(z.get("status")) == ZIEL)
        pleiten = sum(1 for z in self.zustaende.values() if normalisieren(z.get("status")) == PLEITE)

        self.ue["gesamt"].config(text=f"{euro(gesamt)} ({prozent((gesamt / start - 1) * 100)})",
                                 foreground="#1b7a33" if gesamt >= start else "#b3261e")
        self.ue["bester"].config(text=f"Bot {bester}: {euro(salden[bester])}")
        self.ue["schlechtester"].config(text=f"Bot {schlechtester}: {euro(salden[schlechtester])}")
        self.ue["ziel"].config(text=f"{ziele} / {len(self.adapter)}")
        self.ue["pleite"].config(text=f"{pleiten} / {len(self.adapter)}")

    def _laeuft_einer(self):
        return any(m == LAEUFT for m in self.modi.values())

    def _laufzeit_pruefen(self):
        """Timer läuft nur, solange mindestens ein Bot läuft."""
        if self._laeuft_einer() and self._laufzeit_seit is None:
            self._laufzeit_seit = time.time()
        elif not self._laeuft_einer() and self._laufzeit_seit is not None:
            self.laufzeit += time.time() - self._laufzeit_seit
            self._laufzeit_seit = None

    def _uhr(self):
        sekunden = self.laufzeit + (time.time() - self._laufzeit_seit if self._laufzeit_seit else 0)
        s = int(sekunden)
        self.ue["laufzeit"].config(text=f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}")
        self.root.after(500, self._uhr)

    # ---------- Log ----------

    def log_schreiben(self, *texte):
        """Ereignisse gesammelt anhängen (ein Einfügen und ein Scrollen pro Takt)."""
        zeit = time.strftime("%H:%M:%S")
        if len(texte) > LOG_PRO_TAKT:
            weggelassen = len(texte) - LOG_PRO_TAKT
            texte = (f"… {weggelassen} weitere Ereignisse (schneller als die Anzeige)",) + texte[-LOG_PRO_TAKT:]
        self.log.config(state="normal")
        self.log.insert("end", "".join(f"{zeit}  {t}\n" for t in texte))
        zeilen = int(self.log.index("end-1c").split(".")[0])
        if zeilen > LOG_MAX_ZEILEN:
            self.log.delete("1.0", f"{zeilen - LOG_MAX_ZEILEN}.0")
        self.log.see("end")
        self.log.config(state="disabled")

    # ---------- Ende ----------

    def beenden(self):
        for a in self.adapter.values():
            a.beenden()
        self.root.destroy()
