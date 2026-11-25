# PLAN: Krypto-Wettrennen mit Spielgeld

**Goal:** see [SPEC.md](SPEC.md): mehrere Strategien handeln je 10 € Spielgeld stündlich mit Krypto und versuchen, 1.000 € zu erreichen; der Bericht zeigt das Rennen.

## Architecture Approach

- **Python 3, nur Standardbibliothek** (`urllib`, `json`, `unittest`). Es gibt keine Abhängigkeiten, die brechen oder installiert werden müssen. Neuer Ordner `krypto/`, Tests in `tests_krypto/`, beides getrennt vom SPY-Bot.
- **Kurse von Kraken** (öffentliche REST-API, ohne Schlüssel, Paare `XBTEUR`, `ETHEUR`, `SOLEUR`, Stundenkerzen über `/0/public/OHLC?interval=60`). Binance scheidet aus, weil die GitHub-Runner in den USA stehen und Binance US-IPs sperrt. Kraken ist aus diesem Container gesperrt (Proxy). Getestet wird deshalb nur mit festen Beispielkursen; der erste Live-Abruf passiert in GitHub Actions (Slice 5).
- **LLM über eine OpenAI-kompatible Chat-Schnittstelle** per `urllib`. Standard ist Groq (kostenloses Kontingent). Basis-URL und Modell sind als Variablen umstellbar, der Schlüssel liegt im Secret `LLM_API_KEY`. Der Client ist in Tests austauschbar, damit AC-2 ohne Netz läuft.
- **Zustand und Bericht auf eigenem Daten-Branch `krypto-daten`**: Jeder Lauf ersetzt dort einen einzigen Commit per Force-Push mit dem Workflow-Token. So wächst der Verlauf nicht um 720 Commits im Monat. `main` bleibt sauber; das README verlinkt den Bericht auf dem Daten-Branch. Nachteil: Der Verlauf des Depotstands steckt nur in einer Verlaufsdatei auf dem Branch (`verlauf.csv`, eine Zeile pro Lauf), nicht in Git.
- **Strategie-Parameter** stehen in `krypto/STRATEGIEN.md` und als Konstanten in `krypto/strategien.py`; eine Rennnummer samt Startdatum steht im Zustand. Startvorschlag: Momentum-Rotation mit 24 h Rückblick; Trendfolge mit gleitendem Durchschnitt über 48 Stundenkerzen, wobei unter den Coins über ihrem Durchschnitt der mit dem größten Abstand gehalten wird.
- **Zeitplan-Hürde:** Das Repo ist öffentlich (Actions-Minuten kostenlos), aber sein Standard-Branch ist `claude/lucid-archimedes-729smm`. GitHub führt geplante Workflows nur vom Standard-Branch aus. Slice 4 endet deshalb mit einem Checkpoint.

## Slices

### Slice 1: Simulationskern, Regel-Strategien, Rennlogik

**Objective:** Offline-Kern, der Depots mit 10 € führt, Orders mit 0,1 % Gebühr simuliert und Momentum-Rotation, Trendfolge und BTC-Halten aus Kursreihen entscheiden lässt.
**Acceptance criteria:**
- Feste Beispielkurse erzeugen die erwarteten Orders, Gebühren und Depotwerte je Strategie (AC-1).
- Ein Depot unter 1 € wird „pleite“ und handelt in Folgeläufen nicht mehr; ein Depot ≥ 1.000 € bekommt einmalig seinen Ziel-Zeitpunkt, der erhalten bleibt (AC-6).
- Gleiche Kurse ergeben gleiche Entscheidungen.
- Zustand lässt sich als JSON speichern und unverändert wieder laden.
**Verification:** `python3 -m unittest discover -s tests_krypto -v`
**Touches:** `krypto/depot.py`, `krypto/strategien.py`, `krypto/STRATEGIEN.md`, `tests_krypto/`
**Status:** complete
**Evidence:** neu `krypto/depot.py`, `krypto/strategien.py`, `krypto/STRATEGIEN.md`, `tests_krypto/test_kern.py`; `python3 -m unittest discover -s tests_krypto -v` → 15 Tests OK (Gebühren, Orders nur bei Wechsel, Ziel bleibt, Pleite stoppt Handel, Drawdown, JSON-Rundreise, Szenario mit erwarteten Orders und Endwert).
**Risks / next:** none

### Slice 2: KI-Händler

**Objective:** Strategie, die einem LLM Kurse und Kennzahlen gibt und dessen Antwort im festen Format in eine Order übersetzt.
**Acceptance criteria:**
- Gültige Antwort („kaufen ETH“, „verkaufen“, „halten“ plus Begründung) führt zur passenden Order (AC-2).
- Ungültige Antwort, Zeitüberschreitung, HTTP-Fehler oder fehlender Schlüssel führen zu „halten“ und erhöhen einen Ausfallzähler (AC-2).
- Antwort und Begründung werden im Zustand gespeichert. Der Schlüssel erscheint in keiner Ausgabe.
**Verification:** `python3 -m unittest discover -s tests_krypto -v` (Tests mit vorgegebenen LLM-Antworten, ohne Netz)
**Depends on:** Slice 1
**Touches:** `krypto/ki.py`, `tests_krypto/test_ki.py`
**Status:** complete
**Evidence:** neu `krypto/ki.py`, `tests_krypto/test_ki.py`; `python3 -m unittest discover -s tests_krypto -v` → 22 Tests OK (gültige Kauf-/Verkauf-/Halten-Antworten, 4 ungültige Antworten und 4 Ausfallarten → halten mit Zähler, fehlender Schlüssel → halten, Schlüssel nicht im Depotzustand).
**Risks / next:** Modellname `llama-3.3-70b-versatile` ist Groq-Standard; über `LLM_MODEL` umstellbar, falls Groq ihn abschafft.

### Slice 3: Stündlicher Lauf und Bericht

**Objective:** Ein Einstiegspunkt `python3 -m krypto.lauf` holt Kraken-Kurse, lädt den Zustand, lässt alle Strategien entscheiden, speichert den Zustand, hängt an `verlauf.csv` an und schreibt `KRYPTO-REPORT.md`.
**Acceptance criteria:**
- Mit Beispielkursen statt Kraken (Testmodus) entsteht ein Bericht mit allen Angaben aus Required Outcome 6: Rangliste, Fortschritt bis 1.000 € in %, Status, Gebühren, Orders, größter Zwischenverlust, Renndauer, letzter Lauf, letzte KI-Entscheidung, Spielgeld-Hinweis, Hinweis auf idealisierte Fills (AC-5).
- Zwei aufeinanderfolgende Testläufe setzen auf dem gespeicherten Zustand auf, statt neu zu starten.
- Fehlschlag beim Kursabruf beendet den Lauf mit Fehlercode, ohne den Zustand zu verändern.
- Der Code enthält keinen Order-Endpunkt einer Börse und keinen Börsen-Schlüssel (AC-3, Code-Teil).
**Verification:** `python3 -m unittest discover -s tests_krypto -v && grep -rniE "AddOrder|/private/|api_secret" krypto/ ; test $? -eq 1`
**Depends on:** Slice 2
**Touches:** `krypto/kurse.py`, `krypto/lauf.py`, `krypto/bericht.py`, `tests_krypto/`
**Status:** complete
**Evidence:** neu `krypto/kurse.py`, `krypto/lauf.py`, `krypto/bericht.py`, `tests_krypto/test_lauf.py`; kleine Ergänzung in `krypto/ki.py` (fehlender Schlüssel erscheint im Bericht als „kein LLM_API_KEY hinterlegt“). `python3 -m unittest discover -s tests_krypto -v` → 30 Tests OK (zwei Läufe setzen auf Zustand auf, Bericht enthält alle Angaben aus Outcome 6, Ziel/Pleite im Bericht, Kursfehler → Exit 1 ohne Dateiänderung, Kraken-Antwort-Parsing); Order-Endpunkt-Suche leer. Probelauf mit Beispielkursen erzeugt lesbaren Bericht.
**Risks / next:** Kraken ist aus diesem Container gesperrt; der echte Abruf wird erst in Slice 5 belegt.

### Slice 4: Zeitplan, Daten-Branch, Einrichtungsanleitung

**Objective:** Workflow `.github/workflows/krypto-bot.yml` läuft stündlich (und manuell startbar), führt Tests und Lauf aus und veröffentlicht Zustand, `verlauf.csv` und Bericht als einzelnen Commit auf `krypto-daten`.
**Acceptance criteria:**
- Workflow hat `schedule` (stündlich), `workflow_dispatch`, `permissions: contents: write`, eine `concurrency`-Gruppe gegen überlappende Läufe und reicht `LLM_API_KEY` nur als Umgebungsvariable weiter.
- Beim ersten Lauf ohne Daten-Branch startet das Rennen neu; danach lädt der Lauf den Zustand vom Daten-Branch.
- `EINRICHTUNG-KRYPTO.md` benennt jeden Klick: kostenlosen Groq-Schlüssel anlegen, Secret `LLM_API_KEY` hinterlegen, Standard-Branch umstellen, ersten Lauf manuell starten, Bericht öffnen.
- README verlinkt Bericht und Anleitung.
- Suche in Repo und Git-Verlauf findet keine API-Schlüssel (AC-3).
**Verification:** `python3 -c "import yaml,sys; d=yaml.safe_load(open('.github/workflows/krypto-bot.yml')); assert d[True]['schedule'] and 'workflow_dispatch' in d[True]" && bash krypto/veroeffentlichen.sh --trockenlauf && git log -p --all | grep -niE "gsk_[A-Za-z0-9]{20}|sk-[A-Za-z0-9]{20}" ; test $? -eq 1`
**Depends on:** Slice 3
**Touches:** `.github/workflows/krypto-bot.yml`, `krypto/veroeffentlichen.sh`, `EINRICHTUNG-KRYPTO.md`, `README.md`
**Checkpoint after:** human-action
**Checkpoint reason:** Der Nutzer muss (1) einen kostenlosen LLM-Schlüssel anlegen und als Secret `LLM_API_KEY` hinterlegen und (2) den Standard-Branch des Repos auf `main` umstellen, nachdem dieser PR gemergt ist. Achtung: Mit der Umstellung stoppt der Zeitplan des SPY-Bots auf `claude/lucid-archimedes-729smm`, bis dieser ebenfalls nach `main` kommt. Ohne Schlüssel läuft das Rennen trotzdem, der KI-Händler hält dann nur.

### Slice 5: Live-Nachweis

**Objective:** Belegen, dass zwei aufeinanderfolgende geplante Läufe ohne Eingriff durchlaufen.
**Acceptance criteria:**
- Zwei geplante Workflow-Läufe hintereinander sind erfolgreich (AC-4).
- `krypto-daten` zeigt nach jedem Lauf einen neuen Laufzeitpunkt im Bericht und eine weitere Zeile in `verlauf.csv`.
- Der Bericht zeigt echte Kraken-Kurse und, falls der Schlüssel hinterlegt ist, eine KI-Entscheidung statt nur Ausfällen.
**Verification:** GitHub-Actions-Läufe des Workflows `krypto-bot.yml` über die GitHub-Tools auflisten (zwei aufeinanderfolgende `schedule`-Läufe mit `success`) und `KRYPTO-REPORT.md` sowie `verlauf.csv` auf `krypto-daten` lesen.
**Depends on:** Slice 4

## Execution Routing and Topology

Default: direct, serial, continuation after verification. Slices 1 bis 4 laufen ohne Pause durch.

**Parallel-safe groups:** none (jede Slice baut auf der vorigen auf)

Checkpoints:
- Slice 4: human-action (LLM-Secret und Standard-Branch kann nur der Nutzer einstellen)

## Requirement Traceability

| AC | Slice |
| --- | --- |
| AC-1 | 1 |
| AC-2 | 2 |
| AC-3 | 3 (Code), 4 (Repo und Verlauf) |
| AC-4 | 5 |
| AC-5 | 3 |
| AC-6 | 1 |
