"""Dummy-Bot mit Zufalls-Trades, damit die GUI ohne echten Bot getestet werden kann.

Er erfüllt dieselbe Schnittstelle wie dein echter Bot: step(), get_state(), reset().
Die Kurse sind erfunden (Zufallsbewegung) und absichtlich sehr schwankend,
damit man in kurzer Zeit Bots sieht, die das Ziel erreichen oder pleitegehen.
"""

import random
import time
import uuid

STARTKAPITAL = 10.0
ZIEL = 1000.0
LEER = 0.10          # unter 10 Cent gilt das Wallet als leer
GEBUEHR = 0.001      # 0,1 % pro Trade
MAX_HISTORIE = 2000  # danach wird die Historie ausgedünnt

ASSETS = {"BTC": 50000.0, "ETH": 1500.0, "SOL": 60.0}


class DummyBot:
    def __init__(self, bot_id, seed=None):
        self.bot_id = bot_id
        self.zufall = random.Random(seed)
        self.reset()

    def reset(self):
        """Neues Wallet mit 10 € Startkapital."""
        self.wallet_id = "W-" + uuid.UUID(int=self.zufall.getrandbits(128)).hex[:8].upper()
        self.preise = {a: p * self.zufall.uniform(0.9, 1.1) for a, p in ASSETS.items()}
        self.bargeld = STARTKAPITAL
        self.asset = None
        self.menge = 0.0
        self.einstand = 0.0
        self.trades = []
        self.status = "läuft"
        self.start = time.time()
        self.history = [(0.0, STARTKAPITAL)]

    # ---------- Schnittstelle ----------

    def step(self):
        """Ein Handelsschritt: Kurse bewegen, zufällig kaufen oder verkaufen."""
        if self.status != "läuft":
            return
        for asset in self.preise:
            # starke Schwankung: ±6 % pro Schritt, leichte Drift
            self.preise[asset] *= max(0.05, self.zufall.gauss(1.001, 0.06))

        if self.asset is None and self.zufall.random() < 0.35:
            self._kaufen(self.zufall.choice(list(self.preise)))
        elif self.asset is not None and self.zufall.random() < 0.25:
            self._verkaufen()

        saldo = self.balance()
        if saldo >= ZIEL:
            if self.asset is not None:
                self._verkaufen()
            self.status = "ziel"
        elif saldo < LEER:
            self.status = "pleite"
        self._historie(saldo)

    def get_state(self):
        return {
            "id": self.bot_id,
            "wallet_id": self.wallet_id,
            "balance": self.balance(),
            "trades": self.trades,
            "status": self.status,
            "history": self.history,
        }

    # ---------- intern ----------

    def balance(self):
        if self.asset is None:
            return self.bargeld
        return self.bargeld + self.menge * self.preise[self.asset]

    def _kaufen(self, asset):
        preis = self.preise[asset]
        betrag = self.bargeld * (1 - GEBUEHR)
        self.menge = betrag / preis
        self.einstand = self.bargeld
        self.asset = asset
        self.bargeld = 0.0
        self._trade("Kauf", asset, self.menge, preis, None)

    def _verkaufen(self):
        preis = self.preise[self.asset]
        erloes = self.menge * preis * (1 - GEBUEHR)
        self._trade("Verkauf", self.asset, self.menge, preis, erloes - self.einstand)
        self.bargeld = erloes
        self.asset = None
        self.menge = 0.0

    def _trade(self, typ, asset, menge, preis, ergebnis):
        self.trades.append({
            "zeit": time.strftime("%H:%M:%S"),
            "typ": typ,
            "asset": asset,
            "menge": menge,
            "preis": preis,
            "ergebnis": ergebnis,
        })

    def _historie(self, saldo):
        self.history.append((time.time() - self.start, saldo))
        if len(self.history) > MAX_HISTORIE:
            # jeden zweiten Punkt verwerfen, Start und Ende bleiben erhalten
            self.history = self.history[:1] + self.history[1:-1:2] + self.history[-1:]
