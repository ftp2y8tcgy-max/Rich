# Rich

## Day-Trader-Rennen (Web-Dashboard)

25 Bots mit je 10 € handeln US-Aktien nach den Regeln aus [day-trader-skill](https://github.com/Jakeschincariol/day-trader-skill), Ziel 1.000 €. Start: `python3 ipad/day_trader_rennen.py` (auch direkt in einer Python-App auf dem iPad). Echtgeld-Simulation mit Gebühren, Spread, Slippage und Wechselkurs. Details: [dashboard/README.md](dashboard/README.md).

Die 11 Skills des Pakets (`/trader-scanner`, `/trader-entry`, `/trader-timemachine` …) sind unter `.claude/skills/` installiert.

## Krypto-Scanner (Papiergeld, Kraken-Regeln)

Beobachtet alle liquiden Kraken-Coins in Euro (bis zu 40), testet jede Stunde sieben Strategien auf den letzten 14 Tagen mit echten Kraken-Kosten und handelt mit der besten. Gehalten wird höchstens ein Coin; ist keine Strategie besser als BTC-Halten oder Bargeld, bleibt er draußen. Läuft alle 5 Minuten auf GitHub. Kein echtes Geld; eine Ampel zeigt, ob die Kriterien für Echtgeld je erfüllt sind.

- **Stand:** [KRYPTO-REPORT.md](https://github.com/ftp2y8tcgy-max/Rich/blob/krypto-daten/KRYPTO-REPORT.md)
- **Bedienung:** [EINRICHTUNG-KRYPTO.md](EINRICHTUNG-KRYPTO.md) · **Regeln:** [krypto/STRATEGIEN.md](krypto/STRATEGIEN.md)
- **Code:** `krypto/`, Tests: `python3 -m unittest discover -s tests_krypto -t .`, Zeitplan: `.github/workflows/krypto-scanner.yml`

Ehrlich: Die meisten Krypto-Bots von Privatleuten schneiden nach Gebühren schlechter ab als Bitcoin zu halten. Der Bericht zeigt, ob dieser es besser macht.

## Werkzeuge

[automaton](https://github.com/appautomaton/automaton) v0.4.4 (MIT) ist für Claude Code, Codex und OpenCode installiert (`.agent/`, `.claude/`, `.codex/`, `.opencode/`). Arbeitsablauf: `/auto-frame` → `/auto-plan` → `/auto-execute` → `/auto-verify`, fortsetzen mit `/auto-resume`.
