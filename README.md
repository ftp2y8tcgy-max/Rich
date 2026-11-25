# Rich

## Krypto-Wettrennen (Spielgeld)

Vier Strategien starten mit je 10 € Spielgeld und handeln stündlich BTC, ETH und SOL. Ziel: schnellstmöglich 1.000 €. Darunter sind zwei Regel-Strategien, ein KI-Händler und als Vergleich „BTC kaufen und halten“. Kein echtes Geld, kein Börsenkonto.

- **Stand:** [KRYPTO-REPORT.md](https://github.com/ftp2y8tcgy-max/Rich/blob/krypto-daten/KRYPTO-REPORT.md) (nach jedem Lauf aktualisiert)
- **Einmalige Einrichtung:** [EINRICHTUNG-KRYPTO.md](EINRICHTUNG-KRYPTO.md)
- **Regeln:** [krypto/STRATEGIEN.md](krypto/STRATEGIEN.md)
- **Code:** `krypto/`, Tests: `python3 -m unittest discover -s tests_krypto -v`, Zeitplan: `.github/workflows/krypto-bot.yml`

Ehrlich: Das Hundertfache in kurzer Zeit ist ohne Hebel kaum erreichbar. Am wahrscheinlichsten enden die meisten Strategien unter 10 €. Der Bericht zeigt, was tatsächlich passiert.

## Werkzeuge

[automaton](https://github.com/appautomaton/automaton) v0.4.4 (MIT) ist für Claude Code, Codex und OpenCode installiert (`.agent/`, `.claude/`, `.codex/`, `.opencode/`). Arbeitsablauf: `/auto-frame` → `/auto-plan` → `/auto-execute` → `/auto-verify`, fortsetzen mit `/auto-resume`.
