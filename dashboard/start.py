"""Startet das Day-Trader-Rennen: 25 Bots, echte Kurse, Web-Dashboard.

    python3 dashboard/start.py                 # http://localhost:8765, auch im WLAN erreichbar
    python3 dashboard/start.py --autostart     # Bots sofort losschicken
    python3 dashboard/start.py --aktien TSLA,NVDA,AMD,META,PLTR --port 8765
    python3 dashboard/start.py --offline       # ohne Internet: Cache oder mitgelieferte TSLA-Kerzen
    python3 dashboard/start.py --nur-lokal     # nur von diesem Rechner aus erreichbar
"""

import argparse
import os
import socket
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import daten  # noqa: E402
import engine  # noqa: E402
import server  # noqa: E402


def lan_adresse():
    """Eigene Adresse im WLAN (es wird nichts gesendet, nur die Route ermittelt)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))
            return s.getsockname()[0]
    except OSError:
        return None


def main():
    p = argparse.ArgumentParser(description="Day-Trader-Rennen: 25 Bots × 10 € → 1.000 €")
    p.add_argument("--aktien", default=",".join(engine.STANDARD_AKTIEN), help="genau 5 Ticker, kommagetrennt")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--nur-lokal", action="store_true", help="nur 127.0.0.1 statt im ganzen WLAN")
    p.add_argument("--offline", action="store_true", help="Yahoo nicht abfragen")
    p.add_argument("--tempo", type=float, default=40, help="Kerzen pro Sekunde (Standard 40)")
    p.add_argument("--autostart", action="store_true")
    a = p.parse_args()

    aktien = [s.strip().upper() for s in a.aktien.split(",") if s.strip()]
    if len(aktien) != 5:
        p.error("--aktien braucht genau 5 Ticker (5 Aktien × 5 Regelprofile = 25 Bots)")

    print("Lade 60 Tage Fünf-Minuten-Kerzen …")
    maerkte = []
    for sym in aktien:
        sitzungen, quelle, daten_sym = daten.sitzungen(sym, offline=a.offline)
        name = sym if daten_sym == sym else f"{sym}→{daten_sym}"
        print(f"  {name:10} {len(sitzungen):3} volle Handelstage ({quelle})")
        maerkte.append(engine.Markt(daten_sym, sitzungen, quelle))

    rennen = engine.Rennen(maerkte)
    rennen.steuern("tempo", wert=a.tempo)
    rennen.starten_thread()
    if a.autostart:
        rennen.steuern("start")

    host = "127.0.0.1" if a.nur_lokal else "0.0.0.0"
    srv = server.starten(rennen, host, a.port)
    print(f"\nDashboard: http://localhost:{a.port}")
    lan = None if a.nur_lokal else lan_adresse()
    if lan:
        print(f"Vom iPad im selben WLAN: http://{lan}:{a.port}")
    print("Beenden mit Strg+C\n")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        rennen.beenden()
        srv.server_close()


if __name__ == "__main__":
    main()
