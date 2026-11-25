"""Lädt die Time Machine aus dem installierten day-trader-skill (.claude/skills/trader-timemachine).

Die Bots handeln mit genau diesen Funktionen: parse_bars, split_sessions, full_sessions,
build_pool, opening_range, rule_stop und history_replay. So entspricht jeder Trade der
Regel des Skill-Pakets, nicht einem Nachbau.
"""

import importlib.util
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILLS = os.path.join(REPO, ".claude", "skills")


def _laden(ordner, name):
    pfad = os.path.join(SKILLS, ordner, name + ".py")
    if not os.path.exists(pfad):
        raise SystemExit(f"day-trader-skill fehlt: {pfad} nicht gefunden. Skills nach .claude/skills/ kopieren.")
    spec = importlib.util.spec_from_file_location("trader_" + name, pfad)
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


tm = _laden("trader-timemachine", "timemachine")

SESSION_BARS = tm.SESSION_BARS      # 78 Fünf-Minuten-Kerzen von 9:30 bis 16:00 New York
OPEN_MIN = tm.OPEN_MIN
# 76: Kerze 15:50–15:55, danach glattgestellt (trader-exit: flat_by 15:55)
FLAT_SLOT = (15 * 60 + 55 - OPEN_MIN) // 5 - 1
LETZTER_EINSTIEG = (15 * 60 + 30 - OPEN_MIN) // 5  # 72: keine Einstiege nach 15:30 (trader-entry: no_entries_after)
