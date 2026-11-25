# Krypto-Scanner: Bedienung

Nichts einzurichten: Der Scanner läuft auf GitHub alle 5 Minuten von allein, mit Papiergeld nach Kraken-Regeln. Ein Kraken-Konto oder API-Schlüssel ist nicht nötig, weil keine echten Orders erteilt werden.

## Stand ansehen

**Bericht:** https://github.com/ftp2y8tcgy-max/Rich/blob/krypto-daten/KRYPTO-REPORT.md

Am iPad als Lesezeichen oder über „Teilen → Zum Home-Bildschirm“ speichern. Dort stehen der Wert gegenüber BTC-Halten, das gehaltene Coin, die gewählte Strategie samt 14-Tage-Test, die Walk-Forward-Prüfung und die Echtgeld-Ampel.

## Neues Papierdepot

https://github.com/ftp2y8tcgy-max/Rich/actions/workflows/krypto-scanner.yml → **Run workflow** → Haken bei „Neues Papierdepot“ → **Run workflow**. Die geladenen Kursdaten bleiben erhalten.

**Anderes Startkapital** (Standard 10 €): https://github.com/ftp2y8tcgy-max/Rich/settings/variables/actions → **New repository variable** → Name `STARTKAPITAL`, Wert z. B. `100` → danach ein neues Papierdepot starten. Bei sehr kleinen Beträgen verhindern Krakens Mindestordergrößen manche Käufe; der Bericht sagt dann, warum.

## Wenn etwas schiefgeht

- **Alte Zeit bei „Letzter Lauf“:** Läufe schlagen fehl oder sind pausiert. Details unter **Actions**; GitHub schickt bei Fehlern eine E-Mail.
- **E-Mail „scheduled workflow disabled“:** GitHub pausiert Zeitpläne in öffentlichen Repos nach 60 Tagen ohne Aktivität. Unter **Actions → Krypto-Scanner** auf **Enable workflow** tippen.

Das Secret `LLM_API_KEY` vom ersten Krypto-Bot wird nicht mehr gebraucht. Du kannst es unter Settings → Secrets → Actions löschen und den Schlüssel bei Groq widerrufen.
