# SPEC: Krypto-Wettrennen mit Spielgeld – von 10 € auf 1.000 €

**Bet:** Wenn mehrere aggressive Krypto-Strategien, darunter eine KI, jede mit 10 € Spielgeld stündlich handeln, zeigt ein ehrlicher Bericht, ob überhaupt eine davon die 1.000 € erreicht, wie schnell, und wie viele vorher pleitegehen.

## Bounded Goal

Ein eigenständiger Bot handelt stündlich und ohne Zutun mit simuliertem Spielgeld Krypto. Mehrere Strategien starten mit je 10 € und versuchen, schnellstmöglich 1.000 € zu erreichen. Ein laufend aktualisierter Bericht zeigt den Stand des Rennens gegen „BTC kaufen und halten“.

- Work scale: capability
- Work shape: feature
- Lenses: product, engineering, security

## Target User

Die Person, der dieses Repo gehört. Nach einer einmaligen Einrichtung (≤ 30 Minuten) muss sie nichts mehr tun. Den Stand liest sie gelegentlich auf Deutsch, vermutlich am Handy.

## Broader Intent

Nutzerziel: „Du hast 10 € zur Verfügung und versuchst schnellstmöglich auf 1.000 € zu kommen“, dazu: aktiver handeln, eine KI entscheidet mit, Krypto statt Aktien, mehrere Strategien im Vergleich. Gewählt ist ausdrücklich Spielgeld.

Ehrliche Einordnung: 1.000 € aus 10 € sind das Hundertfache. Ohne Hebel braucht das eine Kursverhundertfachung, die es bei BTC, ETH und SOL in kurzer Zeit nicht gab. Aggressive Strategien enden meistens deutlich unter dem Startwert. Der Bot misst das, er verspricht es nicht.

## Scope Coverage

- **Included:** Krypto, stündlicher Takt, KI-Strategie, mehrere Strategien im Vergleich, 10 € Start, Ziel 1.000 € als Messlatte, Spielgeld.
- **Deferred:** Echtes Geld. Es kommt erst in Frage, wenn eine Strategie im Spielgeld-Test das Ziel erreicht, und dann als eigene Änderung mit eigener Spezifikation. Ebenso Nachrichten-Auswertung durch die KI.
- **Anti-goals:** Hebel, Margin, Futures und Leerverkäufe (siehe Annahmen). Keine Änderung am bestehenden SPY-Bot auf Branch `claude/lucid-archimedes-729smm`.

## Required Outcome

1. **Automatischer Lauf:** Jede Stunde startet ein Lauf von selbst über GitHub Actions, außerhalb dieses Containers.
2. **Kurse:** Live-Kurse für BTC, ETH und SOL in Euro kommen über eine öffentliche, schlüsselfreie Kurs-Schnittstelle einer Krypto-Börse.
3. **Simuliertes Spielgeld:** Orders, Bestände und Gebühren (0,1 % pro Order) rechnet der Bot selbst. Bruchteile von Coins sind erlaubt. Der Stand jedes Depots liegt als Datei im Repo und überlebt jeden Lauf.
4. **Strategien, je ein eigenes Depot mit 10 €:**
   - **Momentum-Rotation:** hält stets voll den Coin mit dem stärksten Kursanstieg im Rückblickfenster, oder Bargeld, wenn alle fallen.
   - **Trendfolge:** voll investiert in einen Coin, solange dessen Kurs über seinem gleitenden Durchschnitt liegt, sonst Bargeld.
   - **KI-Händler:** Ein kostenloses Sprachmodell erhält Kurse und Kennzahlen und antwortet in festem Format mit „kaufen X / verkaufen / halten“. Ungültige Antworten oder ein Ausfall bedeuten „halten“. Der Bericht vermerkt den Ausfall.
   - **Vergleich:** BTC zum Start kaufen und halten.
   - Die Parameter jeder Strategie stehen schriftlich im Repo und bleiben während eines Rennens gleich. Eine Änderung startet ein neues Rennen mit eigenem Startdatum.
5. **Rennende pro Strategie:** Bei ≥ 1.000 € ist das Ziel erreicht, und der Zeitpunkt wird festgehalten. Fällt ein Depot unter 1 €, gilt die Strategie als „pleite“ und handelt nicht mehr. Die übrigen Strategien laufen weiter.
6. **Bericht `KRYPTO-REPORT.md`:** auf Deutsch, am Handy lesbar, nach jedem Lauf aktualisiert. Er zeigt eine Rangliste mit Depotwert, Fortschritt bis 1.000 € in Prozent, Status (läuft / Ziel erreicht am … / pleite am …), Gebührensumme, Anzahl Orders, größtem Zwischenverlust, Renndauer und Zeitpunkt des letzten Laufs. Dazu kommen die letzte Entscheidung samt Begründung des KI-Händlers und der Hinweis „Spielgeld, keine Gewinnzusage“.
7. **Einrichtungsanleitung:** benennt Schritt für Schritt, wie der LLM-Schlüssel angelegt und als GitHub-Secret hinterlegt wird und wie der Zeitplan aktiviert wird.
8. **Fehler sichtbar:** Ein fehlgeschlagener Lauf zeigt sich ohne Logdateien am veralteten Laufzeitpunkt im Bericht und an der Standard-Fehlermail von GitHub Actions.

## Constraints

- **Kein echtes Geld:** Es wird keine Börse mit Handelsrechten angebunden, es gibt keinen Börsen-API-Schlüssel und keinen Order-Endpunkt im Code.
- **Geheimnisse:** Der LLM-Schlüssel steht nie im Repo, in Logs oder im Bericht, sondern nur als GitHub-Secret.
- **Keine laufenden Kosten:** Kurs-Schnittstelle, LLM-Kontingent und GitHub Actions bleiben im kostenlosen Rahmen. Stündliche Läufe müssen ins Gratis-Kontingent passen; die Planung prüft das für die Sichtbarkeit des Repos.
- **Reproduzierbar außer KI:** Die Regel-Strategien entscheiden bei gleichen Kursen gleich. Die KI-Entscheidung wird samt Antwort gespeichert, damit sie nachvollziehbar ist.
- **Getrennt vom SPY-Bot:** eigener Code-Ordner, eigener Workflow, eigener Bericht.

## Assumptions (vom Nutzer nicht einzeln bestätigt, bitte jetzt ablehnen, falls falsch)

- Spielgeld, selbst simuliert, statt eines Testkontos einer Börse. Du brauchst kein Börsenkonto.
- Coins BTC, ETH, SOL gegen Euro, 0,1 % Gebühr pro Order.
- **Kein Hebel.** Das ist die folgenreichste Annahme: Mit Hebel wäre das Hundertfache schneller denkbar, aber pleite zu gehen wahrscheinlicher. Wer Hebel will, ändert das vor der Planung.
- Pleite-Grenze 1 €.

## Risks

- **Kurs-Schnittstelle blockiert GitHub-Server oder ändert sich:** Die Planung wählt eine Schnittstelle, die von GitHub Actions aus erreichbar ist. Ein Fehlschlag wird sichtbar (Outcome 8).
- **Kostenloses LLM fällt aus oder ändert Bedingungen:** Dann hält der KI-Händler, und der Bericht zählt die Ausfälle.
- **Kein Ziel erreicht:** Das ist das wahrscheinlichste Ergebnis und kein Fehler des Bots. Der Bericht zeigt es ehrlich.
- **Idealisierte Fills:** Die Simulation kennt keinen Slippage und keine Mindestordergrößen. Der Bericht nennt das als Einschränkung.
- **Git-Verlauf wächst:** Stündliche Commits von Bericht und Zustand blähen den Verlauf auf. Die Planung wählt einen Weg, der das begrenzt.

## Acceptance Criteria

| ID | Prüfung |
| --- | --- |
| AC-1 | Ein automatischer Test spielt alle Regel-Strategien mit festen Beispielkursen durch. Er prüft erwartete Orders, Gebührenabzug, Depotwerte, Ziel-erreicht- und Pleite-Erkennung. Die Testsuite läuft grün. |
| AC-2 | Ein Test mit vorgegebenen LLM-Antworten prüft: Eine gültige Antwort führt zur Order, eine ungültige Antwort oder ein Fehler führt zu „halten“ und wird gezählt. |
| AC-3 | Der Code enthält keinen Order-Endpunkt einer Börse und keinen Börsen-Schlüssel. Eine Suche in Repo und Git-Verlauf findet keine API-Schlüssel. |
| AC-4 | Nach der Einrichtung laufen mindestens zwei aufeinanderfolgende geplante Läufe ohne Eingriff durch. Jeder aktualisiert Depotstand und Bericht mit neuem Laufzeitpunkt. |
| AC-5 | Der Bericht enthält alle Angaben aus Required Outcome 6. |
| AC-6 | Ein Depot unter 1 € handelt in Folgeläufen nicht mehr. Ein Depot ab 1.000 € behält seinen Ziel-Zeitpunkt. Beides wird per Test geprüft. |
