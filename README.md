# Rich

## Test-Trading-Bot (Spielgeld)

Ein Bot handelt jeden US-Börsentag automatisch auf einem Alpaca-**Paper**-Konto mit 10 € und vergleicht sich mit „S&P-500-ETF kaufen und halten“. Kein echtes Geld; die Echtgeld-Adresse von Alpaca steht nirgends im Code.

- Stand: [REPORT.md](REPORT.md) (wird nach jedem Lauf aktualisiert)
- Einmalige Einrichtung: [EINRICHTUNG.md](EINRICHTUNG.md)
- Für das eigentliche Geld: [SPARPLAN.md](SPARPLAN.md)
- Strategie: Am ersten Handelstag jedes Monats SPY halten, wenn der letzte Schlusskurs über dem 200-Tage-Durchschnitt liegt, sonst Bargeld. Order nur bei Wechsel. Gebühr geschätzt 1 € pro Order.
- Code: `bot/`, Tests: `python3 -m unittest discover -s tests -v`, Zeitplan: `.github/workflows/trading-bot.yml`

Eine Gewinnzusage gibt es nicht. Der Test zeigt, ob die Strategie nach Gebühren besser ist als einfaches Halten.

## Werkzeuge

Arbeitsumgebung für Claude Code mit zwei installierten Werkzeugen.

## Installiert

| Werkzeug | Wo | Was es tut |
| --- | --- | --- |
| [automaton](https://github.com/appautomaton/automaton) v0.4.4 (MIT) | `.agent/`, `.claude/skills/auto-*`, `.claude/agents/`, `.claude/hooks/`, `.claude/settings.json` | Arbeitsablauf für KI-Coding-Agenten: frame → plan → execute → verify. Hält den Stand größerer Aufgaben über mehrere Sitzungen fest. |
| [awesome-free-llm-apis](https://github.com/mnfst/awesome-free-llm-apis) (CC0) | `.claude/skills/free-llm-apis/` | Liste von LLM-APIs mit dauerhaft kostenlosem Kontingent und Anleitung zum Einrichten der API-Keys. |

## Benutzen

In Claude Code in diesem Repo:

- `/auto-frame` startet ein neues Vorhaben (Ziel festlegen, `SPEC.md` wird erstellt).
- `/auto-plan`, `/auto-execute`, `/auto-verify` führen es weiter.
- `/auto-resume` setzt eine unterbrochene Arbeit fort.
- "Richte mir eine kostenlose LLM-API ein" lädt den Skill `free-llm-apis`.

Status prüfen:

```bash
npx @appautomaton/automaton@0.4.4 status
npx @appautomaton/automaton@0.4.4 validate
```

## Grenzen

Keines der beiden Werkzeuge verdient Geld. automaton organisiert die Arbeit eines Coding-Agenten, die API-Liste spart Kosten für KI-Aufrufe. Wofür beides eingesetzt wird, muss noch festgelegt werden.
