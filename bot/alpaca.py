"""Minimaler Client für Alpaca Paper Trading (nur Standardbibliothek).

Sicherheitsregel: Orders gehen ausschließlich an die Paper-Adresse.
Die Adresse ist fest verdrahtet und nicht per Einstellung änderbar.
"""

import json
import os
import urllib.parse
import urllib.request
from datetime import date, timedelta

TRADING_URL = "https://paper-api.alpaca.markets"
DATA_URL = "https://data.alpaca.markets"
FX_URL = "https://api.frankfurter.app/latest?from=EUR&to=USD"


class MissingKeys(SystemExit):
    pass


def _get_json(url, headers=None, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def eur_usd():
    """Aktueller EZB-Referenzkurs: 1 € = x $."""
    return float(_get_json(FX_URL)["rates"]["USD"])


class AlpacaPaper:
    def __init__(self, key_id, secret):
        self._headers = {"APCA-API-KEY-ID": key_id, "APCA-API-SECRET-KEY": secret}

    @classmethod
    def from_env(cls):
        key_id = os.environ.get("ALPACA_KEY_ID", "").strip()
        secret = os.environ.get("ALPACA_SECRET_KEY", "").strip()
        if not key_id or not secret:
            raise MissingKeys(
                "Fehlende Zugangsdaten: ALPACA_KEY_ID und ALPACA_SECRET_KEY als "
                "GitHub-Secrets anlegen (siehe EINRICHTUNG.md)."
            )
        return cls(key_id, secret)

    def _trading(self, path, method="GET", body=None):
        return _get_json(TRADING_URL + path, self._headers, method, body)

    def clock(self):
        """{'is_open': bool, 'timestamp': ISO-Zeit in New York}"""
        return self._trading("/v2/clock")

    def daily_closes(self, symbol, days=420):
        """Liste von (Datum, Schlusskurs), älteste zuerst, dividenden-/splitbereinigt."""
        start = (date.today() - timedelta(days=days)).isoformat()
        params = {"timeframe": "1Day", "start": start, "limit": 10000, "feed": "iex", "adjustment": "all"}
        url = f"{DATA_URL}/v2/stocks/{symbol}/bars?" + urllib.parse.urlencode(params)
        out = []
        while url:
            data = _get_json(url, self._headers)
            out += [(b["t"][:10], float(b["c"])) for b in data.get("bars") or []]
            token = data.get("next_page_token")
            url = None
            if token:
                params["page_token"] = token
                url = f"{DATA_URL}/v2/stocks/{symbol}/bars?" + urllib.parse.urlencode(params)
        return out

    def submit(self, symbol, order):
        body = {"symbol": symbol, "side": order["side"], "type": "market", "time_in_force": "day"}
        if "notional" in order:
            body["notional"] = f"{order['notional']:.2f}"
        else:
            body["qty"] = f"{order['qty']:.9f}"
        return self._trading("/v2/orders", "POST", body)

    def get_order(self, order_id):
        return self._trading(f"/v2/orders/{order_id}")
