# Krypto-Scanner: Regeln

**Ziel:** prüfen, ob eine regelbasierte Auswahl unter allen liquiden Kraken-Coins nach echten Kosten besser ist als Bitcoin zu halten. Papiergeld; echte Orders sind nicht eingebaut.

## Welche Coins

Alle Kraken-Paare gegen Euro mit mindestens **250.000 € Umsatz in 24 Stunden** und höchstens **0,5 % Spread**, ohne Stablecoins und Fiat, die 40 umsatzstärksten. Neu ausgewählt alle 6 Stunden.

## Kosten wie bei Kraken

- Kauf zum Briefkurs (Ask), Verkauf zum Geldkurs (Bid), also mit Spread
- 0,40 % Taker-Gebühr je Order (Kraken Pro, unter 10.000 $ Monatsvolumen)
- Kraken-Mindestmenge (`ordermin`), Mindestwert (`costmin`), Menge auf die erlaubten Nachkommastellen abgerundet

## Strategien (gehalten wird höchstens ein Coin)

| Strategie | Kaufsignal |
| --- | --- |
| Momentum 6 h / 24 h / 72 h | Kursanstieg über 6/24/72 Stunden, bewertet relativ zur Schwankung; der stärkste Coin |
| Ausbruch 24 h / 72 h | Schluss über dem Hoch der letzten 24/72 Stunden; der stärkste Ausbruch |
| BTC halten | immer Bitcoin |
| Bargeld | nichts kaufen |

Gekauft wird nur, wenn der Anstieg **mehr als doppelt so groß ist wie Hin- und Rückweg-Kosten**. Gewechselt wird nur mit klarem Vorsprung, damit Gebühren nicht das Ergebnis auffressen. **Stop:** Verkauf, sobald der Kurs 10 % unter den Höchststand seit dem Kauf fällt (alle 5 Minuten geprüft).

## Welche Strategie gilt

Zu jeder vollen Stunde werden alle Strategien auf den **letzten 14 Tagen** mit denselben Kosten durchgerechnet. Es gilt die mit dem besten Ergebnis nach Kosten; „Bargeld“ und „BTC halten“ treten immer mit an. Ist keine aktive Strategie besser, bleibt der Bot draußen oder hält BTC.

**Walk-Forward-Prüfung:** Über die letzten 30 Tage wird für jeden Tag die Strategie gewählt, die in den 14 Tagen davor vorn lag, und dann dieser Tag gehandelt. Das zeigt, was die Auswahl ohne Blick in die Zukunft gebracht hätte.

## Echtgeld-Freigabe

Erst wenn **alle** Punkte erfüllt sind, ist echtes Geld überhaupt eine Überlegung: mindestens 56 Tage Papierhandel, mindestens 30 Trades, nach Kosten im Plus, besser als BTC halten, größter Zwischenverlust höchstens 30 %, Walk-Forward besser als BTC halten.

## Takt

GitHub Actions alle 5 Minuten (GitHub startet geplante Läufe oft einige Minuten verspätet). Kurse und Stop jeden Lauf, Kaufentscheidungen zur vollen Stunde, damit der Livebetrieb genau dem Test entspricht.
