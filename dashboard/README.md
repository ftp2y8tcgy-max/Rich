# Day-Trader-Rennen

25 Bots starten mit je 10 € Spielgeld und handeln US-Aktien nach den Regeln aus
[day-trader-skill](https://github.com/Jakeschincariol/day-trader-skill) (MIT). Ziel: 1.000 €.
Die Oberfläche läuft im Browser, auch auf dem iPad.

![Dashboard](bilder/dashboard.png)

## Starten

Python 3.8 oder neuer, nichts zu installieren.

```bash
python3 dashboard/start.py --autostart
```

Dann im Browser `http://localhost:8765` öffnen. Für das iPad im selben WLAN zeigt das Terminal die Adresse an, z. B. `http://192.168.178.23:8765`.

| Option | Wirkung |
| --- | --- |
| `--aktien TSLA,NVDA,AMD,META,PLTR` | genau 5 Aktien (5 Aktien × 5 Regelprofile = 25 Bots) |
| `--tempo 40` | Kerzen pro Sekunde (im Dashboard per Regler änderbar, 1–1000) |
| `--offline` | Yahoo nicht abfragen: Cache oder die mitgelieferten TSLA-Kerzen |
| `--nur-lokal` | nur von diesem Rechner aus erreichbar, nicht im WLAN |
| `--port 8765` | anderer Port |

Beim Start lädt der Server für jede Aktie 60 Tage Fünf-Minuten-Kerzen von Yahoo (wie die Time Machine des Skills) und speichert sie 12 Stunden in `dashboard/cache/`.

## Wie die Bots handeln

Jeder Bot ist eine Aktie plus ein Regelprofil. Jeder Handelstag läuft Kerze für Kerze ab, mit genau den Funktionen der installierten Time Machine (`.claude/skills/trader-timemachine/timemachine.py`):

1. **Eröffnungsspanne:** Hoch und Tief der ersten 5, 15 oder 30 Minuten (`opening_range`).
2. **Einstieg:** die erste Kerze, die **über** dem Hoch der Spanne schließt, zu ihrem Schlusskurs; nicht nach 15:30 Uhr New York.
3. **Stop:** Mitte oder Tief der Spanne oder ein Prozentwert (`rule_stop`); **Ziel:** Einstieg + R × Risiko.
4. **Ausstieg:** Stop zuerst, dann Ziel, Kerze für Kerze; sonst glattstellen um 15:55 Uhr.
5. Ein Trade pro Tag, nur Kauf, kein Hebel.

| Profil | Spanne | Stop | Ziel |
| --- | --- | --- | --- |
| Lehrbuch | 15 min | Mitte | 2R (Standard von trader-exit) |
| Reel | 15 min | Mitte | 1R (das Beispiel aus dem README des Skills) |
| Früh | 5 min | Tief | 3R |
| Geduld | 30 min | Mitte | 2R |
| Eng | 15 min | 0,5 % | 4R |

Ein Test prüft, dass die Engine auf echten Tagen **genau** dieselben Trades macht wie `history_replay` der Time Machine. Für das Profil „Reel“ auf den TSLA-Daten des Skills ergibt das 33 Trades: 13 am Ziel, 15 am Stop, 5 zum Schluss, also die Zahlen aus dem README des Skills.

**Nach den echten Tagen** (rund 59) geht es mit simulierten Tagen weiter. Sie werden wie in der Time Machine aus den eigenen Kerzen der Aktie zur selben Tageszeit gezogen (`build_pool`) und sind im Dashboard als „Sim-Tag“ bzw. „simuliert“ markiert.

## Abweichungen vom Skill-Paket (wegen 10 € pro Wallet)

- **Bruchstück-Aktien, alles im Einsatz:** trader-budget kauft nur ganze Aktien und begrenzt den Verlust pro Trade. Mit 10 € ginge das nicht, also setzt jeder Bot sein ganzes Guthaben ein, ohne Hebel.
- **Euro statt Dollar:** Das Wallet zählt in €, die Kurse sind in $, ein Wechselkurs wird nicht berücksichtigt.
- **Keine Gebühren, kein Slippage:** wie in der Time Machine. Echte Ergebnisse wären schlechter.
- **Nichts geht an einen Broker.** Es ist eine Simulation; trader-broker wird nicht benutzt.

Ehrlich: Ohne Hebel braucht das Hundertfache sehr viele gute Tage. Die Time Machine des Skills nennt diese Ausbruchsregel auf TSLA „close to a coin flip“. Das Rennen zeigt, was daraus wird.

## Bedienung

- **Start, Pause, Stopp, Reset** oben; **Tempo** per Regler.
- **Bot antippen:** Die Linie im Kontoverlauf wird hervorgehoben. **⤢ oder Doppelklick:** Detailansicht mit den Kerzen des Tages, Eröffnungsspanne, Einstieg, Stop, Ziel, Kontostand und Trade-Historie.
- **▶/❚❚ in der Kachel:** einzelnen Bot starten oder pausieren. Ein pausierter Bot steigt nicht neu ein, ein offener Trade läuft aber nach Plan zu Ende.
- Kachelfarben: grün im Plus, rot im Minus, gold 1.000 € erreicht, grau leer (unter 0,10 €).

## Dateien

| Datei | Inhalt |
| --- | --- |
| `start.py` | lädt Kurse, baut 25 Bots, startet Rennen und Webserver |
| `engine.py` | Markt (echte und simulierte Tage), Bot (Regeln, Wallet), Rennen (Takt, Steuerung) |
| `skill_bruecke.py` | lädt die Time Machine aus `.claude/skills/` |
| `daten.py` | Yahoo-Abruf über die Time Machine, Cache, Rückfall auf mitgelieferte Daten |
| `server.py` | Webserver und JSON-Schnittstelle (`/api/zustand`, `/api/bot/<id>`, `/api/steuerung`) |
| `static/` | Dashboard (HTML, CSS, JavaScript, ohne externe Bibliotheken) |
| `daten/TSLA-60d5m.json.gz` | echte TSLA-Kerzen aus den Testdaten des Skills (MIT, siehe `daten/LICENSE-day-trader-skill`) |
| `tests/` | `python3 -m unittest discover -s dashboard/tests -t dashboard` |

Keine Anlageberatung. Spielgeld.
