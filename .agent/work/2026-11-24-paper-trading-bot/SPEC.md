# SPEC: Test-Trading-Bot mit Spielgeld

**Bet:** Ein Bot mit festen Regeln, der täglich ohne Zutun mit Spielgeld handelt, zeigt nach einer Testphase ehrlich, ob er einen einfachen Index-Kauf schlägt, bevor echtes Geld im Spiel ist.

## Bounded Goal

Ein Trading-Bot handelt an jedem Börsentag automatisch auf einem Spielgeld-Konto (Paper Trading) nach festen, dokumentierten Regeln und führt einen laufend aktualisierten Bericht, der sein Ergebnis inklusive geschätzter Gebühren mit „Index kaufen und halten“ vergleicht.

- Work scale: capability
- Work shape: feature
- Lenses: product, engineering, security

## Target User

Die Person, der dieses Repo gehört. Ziel: nach einer einmaligen Einrichtung (≤ 1 Stunde) nichts mehr tun müssen und den Stand nur gelegentlich ansehen. Sprache Deutsch; der Bericht wird vermutlich am Handy gelesen.

## Broader Intent

Ursprünglicher Wunsch: „reich werden, ohne einen Finger zu krümmen, alles automatisch“, mit Aktien-Trading. Vereinbart wurde eine Aufteilung:

- ETF-Sparplan für das eigentliche Geld (läuft beim Broker, kein Code; siehe Deferred).
- Dieser Bot als Experiment mit Spielgeld, das sich gegen den Index beweisen muss.

Eine Gewinnzusage ist ausgeschlossen. Der Bot misst, ob eine Strategie etwas taugt; er macht nicht reich.

## Approved Approach

„Sparplan + Test-Bot“, vom Nutzer gewählt aus: Sparplan + Test-Bot, nur Bot, nur Sparplan.

- Gestützt durch: Die EU-Finanzaufsicht ESMA schreibt CFD-Brokern vor, den Anteil verlierender Privatkonten anzugeben; typische Angaben liegen bei 70–80 %. Für regelbasierte oder KI-Strategien von Privatleuten gibt es keinen belegten Vorteil gegenüber einem Indexkauf nach Gebühren.
- Nicht bewiesen: dass genau diese Strategie verliert. Genau das misst der Test.

## Required Outcome

1. **Automatischer Lauf:** Der Bot startet an jedem Handelstag der gewählten Börse einmal von selbst, ohne dass der Nutzer oder eine Claude-Sitzung ihn anstößt. Der Zeitplan läuft außerhalb des kurzlebigen Containers dieser Sitzung.
2. **Feste Strategie:** Eine regelbasierte Strategie ohne Hebel, nur Kaufen und Verkaufen von Aktien oder ETFs. Die Regeln stehen schriftlich im Repo und ändern sich während einer Testphase nicht. Eine Änderung startet eine neue Testphase mit eigenem Startdatum.
3. **Paper-Konto:** Orders gehen ausschließlich an die Spielgeld-Schnittstelle des Brokers.
4. **Bericht:** Eine Datei im Repo, nach jedem Lauf aktualisiert, auf Deutsch, am Handy lesbar. Inhalt seit Teststart:
   - Depotwert des Bots und eines Vergleichsdepots, das mit demselben Startkapital am Starttag den Index-ETF kauft und hält.
   - Beide nach geschätzten Gebühren pro Order, die Gebührensumme als eigene Zeile.
   - Anzahl Orders, größter Zwischenverlust (Max Drawdown), Datum des letzten erfolgreichen Laufs.
5. **Einrichtungsanleitung:** Schritt für Schritt, was der Nutzer einmalig tun muss: Paper-Konto anlegen, API-Schlüssel erzeugen und sicher hinterlegen. Jeder Klick und jedes Feld ist benannt.
6. **Fehler sichtbar:** Schlägt ein Lauf fehl, ist das ohne Logdateien erkennbar. Der Bericht zeigt dann ein veraltetes Datum des letzten Laufs, und der Scheduler meldet den Fehler über seine Standard-Benachrichtigung.

## Constraints

- **Kein echtes Geld:** Im Code gibt es keinen Pfad zur Echtgeld-Schnittstelle. Die Paper-Adresse ist fest verdrahtet, nicht per Einstellung umschaltbar.
- **Geheimnisse:** API-Schlüssel stehen nie im Repo, in Logs oder im Bericht. Sie liegen als Secrets des Schedulers.
- **Keine laufenden Kosten:** Broker-Paper-Konto, Kursdaten und Scheduler sind kostenlos nutzbar.
- **Broker:** Kostenloses Paper Trading per API, Bruchstück-Aktien (Orders unter dem Preis einer ganzen Aktie) und Kontoeröffnung aus Deutschland möglich. Die Wahl trifft die Planung; Kandidat ist Alpaca (US-Aktien und ETFs). Die Verfügbarkeit für deutsche Nutzer prüft die Planung vor dem Bau.
- **Startkapital 10 €:** Vom Nutzer festgelegt. Der Bot rechnet nur mit diesen 10 € (in Dollar zum festen Kurs des Teststarts), unabhängig davon, wie viel Spielgeld das Paper-Konto des Brokers anzeigt. Das Vergleichsdepot startet mit demselben Betrag.
- **Reproduzierbar:** Dieselben Kursdaten ergeben dieselben Entscheidungen. Kein Zufall und kein Sprachmodell in der Handelsentscheidung.

## Risks

- **Broker nicht verfügbar** oder Bedingungen geändert: Die Planung prüft das zuerst; ohne passenden Broker stoppt die Änderung vor dem Bau.
- **Scheduler fällt still aus:** Abgedeckt durch das Datum des letzten Laufs im Bericht und die Fehlermeldung des Schedulers.
- **Schönfärberei im Bericht:** Paper-Fills sind idealisiert und Alpaca nimmt keine Gebühren. Deshalb rechnet der Bericht Gebühren pro Order ein und nennt das Paper-Trading als Einschränkung.
- **Gebühren fressen das Kapital:** Bei 10 € kostet jede Order mit 1 € Gebühr 10 % des Depots, das Vergleichsdepot zahlt sie nur einmal. Die Planung wählt deshalb eine Strategie mit wenigen Orders. Der Bericht zeigt die Gebühren getrennt, damit sichtbar ist, ob die Strategie oder die Gebühren das Ergebnis bestimmen.
- **Zu kurze Testphase täuscht:** Wenige Wochen sagen wenig über eine Strategie. Der Bericht zeigt die Testdauer neben dem Ergebnis.

## Acceptance Criteria

| ID | Prüfung |
| --- | --- |
| AC-1 | Ein automatischer Test führt Strategie, Orderlogik und Berichtserzeugung mit festen Beispielkursen aus. Er prüft erwartete Orders, Depotwerte, Gebührenabzug und Vergleichsdepot. Die Testsuite läuft grün. |
| AC-2 | Ein Test schlägt fehl, wenn die Order-Schnittstelle auf eine andere als die Paper-Adresse zeigt. Der Code enthält keine Echtgeld-Adresse. |
| AC-3 | Eine Suche im Repo und in der Git-Historie findet keine API-Schlüssel. |
| AC-4 | Nach der Einrichtung durch den Nutzer laufen mindestens zwei aufeinanderfolgende geplante Läufe ohne manuellen Eingriff erfolgreich. Jeder aktualisiert den Bericht mit neuem Laufdatum. |
| AC-5 | Der Bericht enthält alle Angaben aus Required Outcome 4 und einen sichtbaren Hinweis, dass es Spielgeld ist und vergangene Ergebnisse nichts garantieren. |
| AC-6 | Die Einrichtungsanleitung führt den Nutzer bis zum ersten erfolgreichen Lauf. Nachweis: AC-4 wurde mit genau dieser Anleitung erreicht. |

## Anti-Goals

- Kein Handel mit echtem Geld, auch nicht als versteckte Option.
- Kein Hebel, keine CFDs, Optionen, Leerverkäufe oder Kryptowährungen.
- Kein Sprachmodell, das Kauf- oder Verkaufsentscheidungen trifft.
- Keine Gewinnversprechen oder Renditeprognosen in Bericht, Anleitung oder README.
- Keine Aufgabe, die der Nutzer nach der Einrichtung regelmäßig erledigen muss.
- Keine kostenpflichtigen Dienste oder Server.

## Deferred / Not in Scope

- **ETF-Sparplan-Anleitung:** Kleine Einzelaufgabe ohne Code. Sie braucht keine Spezifikation und wird direkt erledigt.
- **Umstieg auf echtes Geld:** Eigene, spätere Entscheidung des Nutzers nach der Testphase. Sie braucht eine eigene Änderung mit Broker-Prüfung, Steuerfragen (Abgeltungsteuer, ausländischer Broker) und Verlustgrenzen.
- **Strategien mit Sprachmodell** (z. B. über die kostenlosen APIs aus `free-llm-apis`): Ohne belegten Vorteil, und sie machen Ergebnisse schwer reproduzierbar. Sie können später als zweite Paper-Strategie gegen denselben Vergleich antreten.
- **„Und so“ jenseits von Aktien und ETFs** (Krypto, Rohstoffe): Andere Schnittstellen und mehr Schwankung. Als spätere Paper-Strategie möglich.

## Assumptions

Annahmen, die der Nutzer jetzt ablehnen kann:

- **Geschätzte Gebühr pro Order:** 1 €, typisch für deutsche Neobroker. Im Bericht in Dollar umgerechnet zum festen Kurs des Teststarts.
- **Vergleichsindex:** ein breiter US-Index-ETF beim selben Broker, z. B. auf den S&P 500. Grund: Er ist über die Paper-Schnittstelle handelbar und liefert Kurse aus derselben Quelle.
