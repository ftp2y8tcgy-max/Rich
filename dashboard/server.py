"""Kleiner Webserver (nur Standardbibliothek): liefert das Dashboard und eine JSON-Schnittstelle.

GET  /                    Dashboard
GET  /api/zustand?seit=N  Rennstand, Ereignisse ab Nummer N; &verlauf=1 auch die Kontoverläufe
GET  /api/bot/<id>        Details eines Bots (Kerzen des Tages, Trades, Verlauf)
POST /api/steuerung       {"aktion": "start|pause|stop|umschalten|reset|tempo", "bot": id?, "wert": x?}
"""

import json
import mimetypes
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
VERLAUF_PUNKTE = 240


def _duenn(punkte, n=VERLAUF_PUNKTE):
    """Kontoverlauf für die Übertragung ausdünnen (erster und letzter Punkt bleiben)."""
    if len(punkte) <= n:
        return punkte
    schritt = (len(punkte) - 1) / (n - 1)
    return [punkte[round(i * schritt)] for i in range(n)]


def handler_fuer(rennen):
    class Handler(BaseHTTPRequestHandler):
        server_version = "DayTraderRennen/1.0"

        def log_message(self, *args):  # keine Zeile pro Anfrage im Terminal
            pass

        def _json(self, daten, code=200):
            body = json.dumps(daten, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _datei(self, pfad):
            pfad = os.path.normpath(os.path.join(STATIC, pfad))
            if not pfad.startswith(STATIC + os.sep) or not os.path.isfile(pfad):
                self.send_error(404)
                return
            with open(pfad, "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", (mimetypes.guess_type(pfad)[0] or "application/octet-stream")
                             + ("; charset=utf-8" if pfad.endswith((".html", ".css", ".js")) else ""))
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            url = urlparse(self.path)
            q = parse_qs(url.query)
            if url.path in ("/", "/index.html"):
                return self._datei("index.html")
            if url.path.startswith("/static/"):
                return self._datei(url.path[len("/static/"):])
            if url.path == "/api/zustand":
                seit = int((q.get("seit") or ["0"])[0] or 0)
                s = rennen.schnappschuss(seit)
                if (q.get("verlauf") or ["0"])[0] == "1":
                    s["verlauf"] = {bid: _duenn(v) for bid, v in s["verlauf"].items()}
                else:
                    s.pop("verlauf")
                return self._json(s)
            if url.path.startswith("/api/bot/"):
                try:
                    d = rennen.details(int(url.path.rsplit("/", 1)[1]))
                except (ValueError, StopIteration):
                    return self._json({"fehler": "unbekannter Bot"}, 404)
                d["verlauf"] = _duenn(d["verlauf"], 400)
                return self._json(d)
            self.send_error(404)

        def do_POST(self):
            if urlparse(self.path).path != "/api/steuerung":
                return self.send_error(404)
            try:
                laenge = min(int(self.headers.get("Content-Length") or 0), 10000)
                daten = json.loads(self.rfile.read(laenge) or b"{}")
                bot = daten.get("bot")
                rennen.steuern(str(daten.get("aktion")), int(bot) if bot is not None else None, daten.get("wert"))
            except (ValueError, TypeError) as fehler:
                return self._json({"fehler": str(fehler)}, 400)
            return self._json({"ok": True})

    return Handler


def starten(rennen, host, port):
    server = ThreadingHTTPServer((host, port), handler_fuer(rennen))
    server.daemon_threads = True
    return server
