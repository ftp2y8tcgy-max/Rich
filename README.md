# Rich

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
