"""Startet die GUI mit 25 Bots.

    python main.py              # 25 Dummy-Bots
    python main.py --bots 10    # andere Anzahl (Raster bleibt 5 Spalten breit)
    python main.py --autostart  # Bots sofort starten
"""

import argparse
import queue
import tkinter as tk

from bot_adapter import BotAdapter, Einstellungen
from dummy_bot import DummyBot
from gui import TradingGUI


def bots_erzeugen(anzahl):
    """Hier deine echte Bot-Klasse einsetzen (siehe Anleitung in README.md)."""
    return [DummyBot(bot_id=i) for i in range(1, anzahl + 1)]


def main():
    parser = argparse.ArgumentParser(description="Trading-Bot-Dashboard")
    parser.add_argument("--bots", type=int, default=25, help="Anzahl Bots (Standard 25)")
    parser.add_argument("--intervall", type=int, default=100, help="Update-Intervall in ms (Standard 100)")
    parser.add_argument("--autostart", action="store_true", help="alle Bots sofort starten")
    args = parser.parse_args()

    gui_queue = queue.Queue()
    einstellungen = Einstellungen(intervall_ms=args.intervall)
    adapter = [BotAdapter(bot, gui_queue, einstellungen) for bot in bots_erzeugen(args.bots)]

    root = tk.Tk()
    gui = TradingGUI(root, adapter, gui_queue, einstellungen)
    for a in adapter:
        a.thread_starten()
    if args.autostart:
        gui.alle_starten()
    root.mainloop()


if __name__ == "__main__":
    main()
