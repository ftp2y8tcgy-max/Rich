# Memecoin-Bot (Papiergeld)

Eine HTML-Seite, die neue Solana-Memecoins live beobachtet und mit Papiergeld handelt, wie der Bot aus TikTok-Videos, aber ehrlich gerechnet.

**Öffnen am iPad:** https://raw.githack.com/ftp2y8tcgy-max/Rich/main/memecoin/index.html, dann **▶ Starten**. Läuft nur, solange die Seite offen und sichtbar ist („☀︎ Wach halten“ hält den Bildschirm an). Der Stand bleibt im Browser gespeichert.

## Was er macht

1. **Finden:** alle 30 s neue Solana-Coins aus den DexScreener-Listen (neue Profile, Boosts, Top-Boosts, Community-Takeovers)
2. **Kurse:** alle 10 s Preis, Liquidität, Käufe/Verkäufe und Volumen der letzten 5 Minuten
3. **Vier Agenten** mit je einem Viertel des Geldes und eigenen Regeln (Vorsichtig, Momentum, Früh, Curve)
4. **Rug-Check** (RugCheck.xyz) vor jedem Kauf: kein „danger“-Risiko, Score und gesperrte Liquidität im Rahmen
5. **Risiko:** 25 % des Agenten-Geldes pro Trade, höchstens 3 Positionen, Stop −25 %, Hälfte verkaufen bei +60 %, Rest mit 20 % Trailing-Stop, Zeit-Stop nach 45 min, Notverkauf bei abgezogener Liquidität

## Kosten (ehrlich)

DEX-Gebühr je Börse (pump.fun 1,25 %, PumpSwap/Orca 0,3 %, Raydium 0,25 %), Preiseinfluss nach Liquidität (Constant-Product-Formel), 1 % Verzögerung je Seite und $0.05 Netzwerk-/Priority-Gebühr je Transaktion. Der Kontostand ist der Verkaufswert nach diesen Kosten.

## Tests

`node memecoin/test.js`: Regeln, Rug-Check, Kosten, Gewinnmitnahme, Trailing-Stop, Stop, Rug-Erkennung, Zeit-Stop, Bilanz.

Kein echtes Geld, keine Anlageberatung. Gib niemals deine Seed-Phrase oder deinen Private Key an einen Bot.
