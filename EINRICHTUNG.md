# Einrichtung (einmalig, ca. 20 Minuten)

Danach läuft der Bot jeden Börsentag von selbst. Es geht nur um **Spielgeld**, es wird kein echtes Geld eingezahlt oder gehandelt.

## 1. Alpaca-Spielgeld-Konto anlegen

1. Öffne <https://alpaca.markets> und tippe auf **Sign Up**.
2. E-Mail-Adresse und Passwort eingeben, dann die Bestätigungs-E-Mail öffnen und den Link anklicken.
3. Wenn nach einem echten Konto (Live Account, Ausweis, Adresse) gefragt wird: **überspringen**. Für den Bot reicht das Paper-Konto, das sofort da ist.

## 2. Schlüssel für das Paper-Konto erzeugen

1. Im Alpaca-Dashboard oben links prüfen, dass **Paper** ausgewählt ist (nicht Live).
2. Auf der Startseite rechts den Kasten **API Keys** suchen und **Generate New Keys** (oder **Regenerate**) antippen.
3. Es erscheinen zwei Werte:
   - **Key** (beginnt meist mit `PK`)
   - **Secret** (wird nur einmal angezeigt)
4. Beide kopieren, z. B. in eine Notiz auf dem Handy. **Niemandem schicken, nicht in Chats einfügen.**

## 3. Schlüssel bei GitHub hinterlegen

1. Öffne <https://github.com/ftp2y8tcgy-max/Rich/settings/secrets/actions>.
2. **New repository secret** antippen.
   - Name: `ALPACA_KEY_ID`
   - Secret: der **Key** aus Schritt 2
   - **Add secret**
3. Noch einmal **New repository secret**:
   - Name: `ALPACA_SECRET_KEY`
   - Secret: das **Secret** aus Schritt 2
   - **Add secret**

Die Namen müssen genau so geschrieben sein.

## 4. Dem Bot erlauben, seinen Bericht zu speichern

1. Öffne <https://github.com/ftp2y8tcgy-max/Rich/settings/actions>.
2. Ganz unten bei **Workflow permissions**: **Read and write permissions** wählen.
3. **Save**.

## 5. Ersten Lauf starten

1. Öffne <https://github.com/ftp2y8tcgy-max/Rich/actions/workflows/trading-bot.yml>.
2. Falls ein Hinweis erscheint, dass Workflows deaktiviert sind: **Enable** bzw. **I understand my workflows, go ahead and enable them**.
3. **Run workflow** → **Run workflow** antippen.
4. Nach etwa einer Minute ist der Lauf grün. Falls die US-Börse gerade geschlossen ist (vor 15:30 oder nach 22:00 deutscher Zeit, am Wochenende, an US-Feiertagen), passiert beim ersten Mal noch nichts. Der Bot startet dann beim nächsten geplanten Lauf von selbst.

## Fertig

- Den Stand siehst du jederzeit in [REPORT.md](REPORT.md).
- Schlägt ein Lauf fehl, schickt GitHub dir eine E-Mail.
- Sag Claude danach Bescheid, damit die ersten Läufe geprüft werden.
