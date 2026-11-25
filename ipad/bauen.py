"""Baut ipad/day_trader_rennen.py: das Dashboard als eine einzige Python-Datei.

    python3 ipad/bauen.py

Setzt ipad/vorlage.py.in zusammen mit dem Kursabruf der Time Machine (.claude/skills/trader-timemachine, MIT),
der Oberfläche samt Engine aus dashboard/static/ und den mitgelieferten TSLA-Kerzen.
"""

import ast
import base64
import os
import textwrap

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TM = os.path.join(REPO, ".claude", "skills", "trader-timemachine", "timemachine.py")
DASH = os.path.join(REPO, "dashboard")
ZIEL = os.path.join(REPO, "ipad", "day_trader_rennen.py")

TM_KONSTANTEN = ["UA", "PAUSE", "BACKOFF", "HOSTS", "INTERVAL", "SESSION_BARS", "OPEN_MIN", "EPOCH"]
TM_TEILE = ["TMError", "_nth_sunday", "eastern_offset", "to_eastern", "utc_of", "chart_url", "_sleep", "_get",
            "fetch_chart", "chart_result", "parse_bars", "split_sessions", "full_sessions"]


def lesen(*teile):
    with open(os.path.join(*teile), encoding="utf-8") as f:
        return f.read()


def time_machine_auszug():
    src = lesen(TM)
    baum = ast.parse(src)
    konst, teile = {}, {}
    for knoten in baum.body:
        if isinstance(knoten, ast.Assign):
            for t in knoten.targets:
                if isinstance(t, ast.Name) and t.id in TM_KONSTANTEN:
                    konst[t.id] = ast.get_source_segment(src, knoten)
        elif isinstance(knoten, (ast.FunctionDef, ast.ClassDef)) and knoten.name in TM_TEILE:
            teile[knoten.name] = ast.get_source_segment(src, knoten)
    fehlt = [n for n in TM_KONSTANTEN + TM_TEILE if n not in konst and n not in teile]
    if fehlt:
        raise SystemExit(f"nicht in der Time Machine gefunden: {fehlt}")
    return "\n".join(konst[n] for n in TM_KONSTANTEN) + "\n\n\n" + "\n\n\n".join(teile[n] for n in TM_TEILE)


def roh(name, inhalt):
    """Als Roh-String einbetten. Drei Hochkommas darf der Inhalt nicht enthalten."""
    if "'''" in inhalt:
        raise SystemExit(f"{name} enthält ''' und kann nicht eingebettet werden")
    return f"{name} = r'''{inhalt}'''\n"


def main():
    lizenz = textwrap.indent(lesen(REPO, ".claude", "skills", "trader-timemachine", "LICENSE").strip(), "# ")
    daten = base64.b64encode(open(os.path.join(DASH, "daten", "TSLA-60d5m.json.gz"), "rb").read()).decode()
    daten_zeilen = "\n".join(f'    "{daten[i:i + 100]}"' for i in range(0, len(daten), 100))
    vorlage = lesen(REPO, "ipad", "vorlage.py.in")
    ersetzen = {
        "#LIZENZ#": lizenz,
        "#TIME_MACHINE#": time_machine_auszug(),
        "#TSLA_DATEN#": daten_zeilen,
        "#STATIC#": roh("INDEX_HTML", lesen(DASH, "static", "index.html")) + "\n"
                    + roh("APP_CSS", lesen(DASH, "static", "app.css")) + "\n"
                    + roh("ENGINE_JS", lesen(DASH, "static", "engine.js")) + "\n"
                    + roh("APP_JS", lesen(DASH, "static", "app.js")),
    }
    for platzhalter, text in ersetzen.items():
        if platzhalter not in vorlage:
            raise SystemExit(f"Platzhalter {platzhalter} fehlt in vorlage.py")
        vorlage = vorlage.replace(platzhalter, text)
    with open(ZIEL, "w", encoding="utf-8") as f:
        f.write(vorlage)
    print(f"{ZIEL}: {len(vorlage.splitlines())} Zeilen, {len(vorlage) // 1024} KB")


if __name__ == "__main__":
    main()
