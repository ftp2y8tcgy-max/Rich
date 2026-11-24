# PLAN: Test-Trading-Bot mit Spielgeld

## Goal

Siehe [SPEC.md](SPEC.md): Bot handelt täglich automatisch auf einem Paper-Konto mit 10 € und vergleicht sich im Bericht mit „Index kaufen und halten“.

## Architecture Approach

- **Broker: Alpaca Paper.** Geprüft am 2026-11-24: reine Paper-Konten sind weltweit nur mit E-Mail eröffenbar, Bruchstück-Aktien und Orders per Dollar-Betrag (`notional`) gehen auch im Paper-Modus. Quellen: alpaca.markets/learn/live-trading-account-non-us, docs.alpaca.markets/us/docs/trading-api. Gehandelt werden US-ETFs (SPY).
- **Scheduler: GitHub Actions `schedule`.** Kostenlos, läuft ohne Container dieser Sitzung, Secrets eingebaut, meldet fehlgeschlagene Läufe per E-Mail. Einschränkung: `schedule` feuert nur auf dem Default-Branch, daher Slice 4.
- **Eigenes Buch statt Kontostand.** Der Bot führt `bot/state.json` (Cash, Anteile, Gebühren, Orders, Wechselkurs, Startdatum) und rechnet nur mit 10 €. Das Paper-Konto liefert nur Ausführungen und Kurse. Der Workflow committet `state.json` und `REPORT.md` zurück ins Repo.
- **Strategie: Monats-Trendfilter.** Am ersten Handelstag des Monats: Schlusskurs SPY über dem 200-Tage-Durchschnitt → SPY halten, sonst Cash. Order nur bei Signalwechsel. Gewählt, weil sie wenige Orders erzeugt (SPEC-Risiko Gebühren) und vollständig reproduzierbar ist. Andere Tage: nur Bewertung und Bericht.
- **Gebühr:** 1 € pro Order, umgerechnet mit dem EZB-Kurs vom Starttag (einmal abgefragt, in `state.json` fixiert).
- **Vergleichsdepot:** rein rechnerisch: am Starttag SPY für 10 € minus eine Gebühr, danach halten. Keine echte Order.
- **Python 3 nur mit Standardbibliothek** (urllib, json, unittest). Keine Abhängigkeiten, nichts zu installieren.

## Slices

### Slice 1: Kernlogik offline

**Objective:** Buchführung, Strategie, Gebühren, Vergleichsdepot und Berichtserzeugung als reine Funktionen ohne Netzwerk.
**Touches:** `bot/core.py`, `bot/report.py`, `tests/test_core.py`
**Acceptance criteria:**
- Mit festen Beispielkursen (Kurs über/unter SMA200, Monatswechsel, Tage ohne Signal) entstehen genau die erwarteten Orders; mitten im Monat nie.
- Depotwert, Gebührensumme, Max Drawdown und Vergleichsdepot stimmen mit von Hand gerechneten Werten überein (AC-1).
- `REPORT.md` enthält alle Felder aus Required Outcome 4, die Testdauer und den Spielgeld-/keine-Garantie-Hinweis (AC-5).
**Verification:** `python3 -m unittest tests.test_core -v`
**Status:** complete
**Evidence:** `bot/core.py`, `bot/report.py`, `tests/test_core.py`; 13 Tests OK, Werte von Hand gerechnet (1 € = 1,10 $, Kauf 9,90 $, Verkauf 120 $ → Cash 10,78 $, Gebühren 2,20 $).
**Risks / next:** none.

### Slice 2: Alpaca-Anbindung und Tageslauf

**Objective:** Paper-Client und `bot/run.py`, der Uhr, Kurse und Orders über den Client holt und Slice 1 aufruft.
**Depends on:** Slice 1
**Touches:** `bot/alpaca.py`, `bot/run.py`, `tests/test_run.py`
**Acceptance criteria:**
- Basis-URL ist die Konstante `https://paper-api.alpaca.markets`; die Echtgeld-Adresse kommt im Code nicht vor. Ein Test schlägt fehl, wenn das nicht stimmt (AC-2).
- Mit einem Fake-Client: geschlossener Markt → kein Handel, Bericht mit Lauf-Datum; Signalwechsel → genau eine `notional`-Order, Ausführungspreis landet im Buch; erster Lauf → Teststart, EZB-Kurs fixiert, Vergleichsdepot angelegt.
- Schlüssel nur aus Umgebungsvariablen `ALPACA_KEY_ID` / `ALPACA_SECRET_KEY`; fehlen sie, bricht der Lauf mit klarer Meldung ab, ohne sie auszugeben.
**Verification:** `python3 -m unittest discover -s tests -v && ! grep -rn "api.alpaca.markets" bot/ | grep -v paper-api`
**Status:** complete
**Evidence:** `bot/alpaca.py`, `bot/run.py`, `tests/test_run.py`, `.gitignore`; 22 Tests OK; grep findet keine Echtgeld-Adresse. Fake-Client deckt ab: Teststart, Kauf, geschlossener Markt, kein Handel mitten im Monat, Verkauf im Folgemonat, nicht ausgeführte Order mit erneutem Versuch.
**Risks / next:** Alpaca und der Wechselkurs-Dienst sind aus dieser Sandbox gesperrt; echte Antwortformate werden erst in Slice 4 auf GitHub bestätigt.

### Slice 3: Workflow und Einrichtungsanleitung

**Objective:** GitHub-Actions-Workflow für den täglichen Lauf und Anleitung für die einmalige Einrichtung.
**Depends on:** Slice 2
**Touches:** `.github/workflows/trading-bot.yml`, `EINRICHTUNG.md`, `README.md`
**Acceptance criteria:**
- Workflow: Montag–Freitag während der US-Handelszeit plus manueller Start (`workflow_dispatch`); führt die Tests und dann `bot/run.py` aus; committet nur `bot/state.json` und `REPORT.md`; Secrets nur als Umgebungsvariablen.
- `EINRICHTUNG.md` benennt jeden Schritt: Alpaca-Paper-Konto, Paper-API-Schlüssel, die zwei Repository-Secrets, Workflow-Schreibrechte, erster manueller Start.
- Keine Schlüssel im Repo oder in der Git-Historie (AC-3).
**Verification:** `python3 -c "import yaml,sys; yaml.safe_load(open('.github/workflows/trading-bot.yml'))" && ! git log -p --all | grep -En "(PK|AK)[A-Z0-9]{16,}"`
**Checkpoint after:** human-action
**Checkpoint reason:** Alpaca-Konto, API-Schlüssel und GitHub-Secrets kann nur der Nutzer anlegen. Außerdem muss der Workflow auf den Default-Branch (Merge), damit `schedule` feuert.

### Slice 4: Erste echte Läufe

**Objective:** Nachweis, dass der Bot nach der Einrichtung unbeaufsichtigt läuft.
**Depends on:** Slice 3 und Checkpoint
**Acceptance criteria:**
- Der manuelle Start läuft grün und erzeugt `REPORT.md` mit Teststart.
- Zwei aufeinanderfolgende geplante Läufe laufen grün, jeder mit neuem Lauf-Datum im Bericht (AC-4, AC-6).
**Verification:** GitHub-Actions-Läufe des Workflows und Commit-Historie von `REPORT.md` prüfen.

## Execution Routing and Topology

- Serielle Reihenfolge 1 → 2 → 3 → Checkpoint → 4. Nach Slice 1 und 2 ohne Pause weiter.
- Alle Slices `direct`.
- Einziger Halt: human-action nach Slice 3.
- **Parallel-safe groups:** none

## Requirement Traceability

| SPEC | Slice |
| --- | --- |
| AC-1, AC-5 | 1 |
| AC-2 | 2 |
| AC-3 | 3 |
| AC-4, AC-6 | 4 |
