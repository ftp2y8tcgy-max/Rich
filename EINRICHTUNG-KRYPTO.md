# Einrichtung: Krypto-Wettrennen

Dauer: etwa 15 Minuten, einmalig. Danach läuft der Bot jede Stunde von selbst. Kein Börsenkonto nötig, es ist Spielgeld.

## 1. Standard-Branch auf `main` stellen

GitHub startet Zeitpläne nur vom Standard-Branch aus. Der steht noch auf `claude/lucid-archimedes-729smm`.

1. Öffne https://github.com/ftp2y8tcgy-max/Rich/settings
2. Abschnitt **Default branch**: Klick auf das Symbol mit den zwei Pfeilen (⇄, „Switch to another branch“).
3. Wähle **main**, dann **Update**.
4. Bestätige mit **I understand, update the default branch.**

> **Achtung:** Der Zeitplan des SPY-Bots liegt auf `claude/lucid-archimedes-729smm`. Nach der Umstellung läuft er nicht mehr, bis er auch auf `main` liegt.

## 2. Kostenlosen KI-Schlüssel anlegen (Groq)

Ohne Schlüssel läuft das Rennen trotzdem, nur der KI-Händler hält dann jede Stunde. Der Bericht zeigt das als „Ausfall: kein LLM_API_KEY hinterlegt“.

1. Öffne https://console.groq.com und melde dich an (Google, GitHub oder E-Mail).
2. Links **API Keys**, dann **Create API Key**.
3. Name: `krypto-bot`, dann **Submit**.
4. Kopiere den Schlüssel (beginnt mit `gsk_`). Er wird nur einmal angezeigt. Nicht in einen Chat oder eine Datei einfügen.

## 3. Schlüssel in GitHub hinterlegen

1. Öffne https://github.com/ftp2y8tcgy-max/Rich/settings/secrets/actions
2. **New repository secret**.
3. **Name:** `LLM_API_KEY`
4. **Secret:** den kopierten Schlüssel einfügen.
5. **Add secret**.

Optional, für einen anderen Anbieter mit OpenAI-kompatibler Schnittstelle: Im Reiter **Variables** derselben Seite `LLM_BASE_URL` (z. B. `https://openrouter.ai/api/v1`) und `LLM_MODEL` anlegen. Ohne diese Variablen nutzt der Bot Groq und wählt selbst ein verfügbares Chat-Modell (welches, steht im Actions-Log unter „KI-Modell“).

## 4. Ersten Lauf starten

1. Öffne https://github.com/ftp2y8tcgy-max/Rich/actions/workflows/krypto-bot.yml
2. **Run workflow**, Branch **main**, nochmals **Run workflow**.
3. Nach etwa einer Minute erscheint ein grüner Haken. Ab dann läuft der Bot stündlich um Minute 7.

## 5. Stand ansehen

**Bericht:** https://github.com/ftp2y8tcgy-max/Rich/blob/krypto-daten/KRYPTO-REPORT.md

Am Handy am besten als Lesezeichen speichern. Der Branch `krypto-daten` enthält nur den neuesten Stand. Den Verlauf aller Läufe zeigt `verlauf.csv` auf demselben Branch.

## Wenn etwas schiefgeht

- **Veraltete Zeit bei „Letzter Lauf“:** Läufe schlagen fehl oder sind gestoppt. GitHub schickt bei fehlgeschlagenen geplanten Läufen eine E-Mail. Details unter **Actions**.
- **E-Mail „scheduled workflow disabled“:** GitHub pausiert Zeitpläne in öffentlichen Repos nach 60 Tagen ohne Aktivität. Unter **Actions → Krypto-Wettrennen** auf **Enable workflow** klicken.
- **Neues Rennen starten:** Branch `krypto-daten` löschen (https://github.com/ftp2y8tcgy-max/Rich/branches). Der nächste Lauf startet bei 10 €.
- **Schlüssel ersetzen:** In Schritt 3 das Secret `LLM_API_KEY` bearbeiten. Den alten Schlüssel bei Groq löschen.
