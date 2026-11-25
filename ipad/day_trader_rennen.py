#!/usr/bin/env python3
"""Day-Trader-Rennen – alles in einer Datei, für die Python-App auf dem iPad.

25 Bots starten mit je 10 € Spielgeld und handeln US-Aktien nach den Regeln aus
day-trader-skill (Ausbruch aus der Eröffnungsspanne, Stop und Ziel vorab, glatt um 15:55).
Ziel: 1.000 €. Spielgeld, keine Anlageberatung, nichts geht an einen Broker.

So startest du es
  Pythonista 3 oder Pyto: Datei öffnen, ▶ drücken. Das Dashboard öffnet sich in der App.
  andere Python-Apps:     ▶/Ausführen. Der Stand erscheint alle 5 Sekunden als Text in der Ausgabe;
                          das Dashboard gibt es zusätzlich unter der angezeigten Adresse in Safari.
  a-Shell:                python3 day_trader_rennen.py  → dann die angezeigte Adresse in Safari öffnen
                          (iOS hält a-Shell im Hintergrund nach kurzer Zeit an: zwischendurch zurückwechseln)
  Mac/PC:                 python3 day_trader_rennen.py  → öffnet den Browser

Optionen (nur in Terminals): --offline  --aktien TSLA,NVDA,AMD,META,PLTR  --tempo 40  --port 8765  --kein-browser

Nur Standardbibliothek, Python 3.8 oder neuer. Erzeugt aus dem Repo mit ipad/bauen.py.
"""

import argparse
import base64
import datetime
import gzip
import itertools
import json
import math
import os
import random
import socket
import threading
import time
import types
import urllib.error
import urllib.parse
import urllib.request
import uuid
import webbrowser
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse


# =====================================================================================
# Teil 1 – Auszug aus der Time Machine von day-trader-skill (unverändert übernommen)
# https://github.com/Jakeschincariol/day-trader-skill, trader-timemachine/timemachine.py
#
# MIT License

# Copyright (c) 2026 Jake Schincariol

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
# =====================================================================================

UA = "Mozilla/5.0 (compatible; day-trader-skill/2.0; +https://github.com/Jakeschincariol/day-trader-skill)"
PAUSE = 0.5
BACKOFF = 5.0
HOSTS = ("query2", "query1")
INTERVAL = 300
SESSION_BARS = 78
OPEN_MIN = 9 * 60 + 30
EPOCH = datetime.datetime(1970, 1, 1)


class TMError(Exception):
    pass


def _nth_sunday(year, month, n):
    d = datetime.date(year, month, 1)
    d += datetime.timedelta(days=(6 - d.weekday()) % 7)
    return d + datetime.timedelta(weeks=n - 1)


def eastern_offset(utc):
    """Hours from UTC for New York: -4 in daylight time, -5 otherwise.
    DST runs from 2:00 a.m. on the second Sunday of March to 2:00 a.m. on the
    first Sunday of November (US rule since 2007)."""
    y = utc.year
    start = datetime.datetime.combine(_nth_sunday(y, 3, 2), datetime.time(7, 0))   # 2:00 EST
    end = datetime.datetime.combine(_nth_sunday(y, 11, 1), datetime.time(6, 0))    # 2:00 EDT
    naive = utc.replace(tzinfo=None)
    return -4 if start <= naive < end else -5


def to_eastern(utc):
    return utc.replace(tzinfo=None) + datetime.timedelta(hours=eastern_offset(utc))


def utc_of(ts):
    return EPOCH + datetime.timedelta(seconds=int(ts))


def chart_url(sym, host="query2"):
    return "https://%s.finance.yahoo.com/v8/finance/chart/%s?range=60d&interval=5m" % (
        host, urllib.parse.quote(sym.upper().replace(".", "-")))


def _sleep(seconds):
    time.sleep(seconds)


def _get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def fetch_chart(sym):
    """One request for 60 days of 5-min bars. query2 first, one retry after a 429,
    then query1 on 429 or 5xx."""
    last = None
    for n, host in enumerate(HOSTS):
        if n:
            _sleep(PAUSE)
        for attempt in (0, 1):
            url = chart_url(sym, host)
            try:
                return _get(url)
            except urllib.error.HTTPError as e:
                last = e.code
                try:
                    e.close()
                except Exception:
                    pass
                if e.code == 429 and attempt == 0:
                    _sleep(BACKOFF)
                    continue
                if e.code == 429 or e.code >= 500:
                    break
                if e.code == 404:
                    raise TMError("Yahoo has no chart for %s (HTTP 404): check the ticker" % sym.upper())
                raise TMError("Yahoo answered HTTP %d for %s" % (e.code, sym.upper()))
            except urllib.error.URLError as e:
                raise TMError("could not reach Yahoo: %s" % e.reason)
            except OSError as e:
                raise TMError("could not reach Yahoo: %s" % e)
    if last == 429:
        raise TMError("Yahoo is rate limiting (HTTP 429). Wait a minute and run it again.")
    raise TMError("Yahoo answered HTTP %s for %s on both hosts. Try again later." % (last, sym.upper()))


def chart_result(text, sym):
    try:
        data = json.loads(text)
    except ValueError:
        raise TMError("Yahoo returned something that is not JSON for %s" % sym.upper())
    chart = data.get("chart") if isinstance(data, dict) else None
    if not isinstance(chart, dict):
        raise TMError("Yahoo returned something unexpected for %s" % sym.upper())
    res = chart.get("result")
    if not res:
        err = chart.get("error") or {}
        raise TMError("Yahoo has no data for %s: %s" % (sym.upper(), err.get("description") or "unknown ticker"))
    return res[0]


def parse_bars(result, now_utc):
    """Yahoo chart result -> (meta, bars, dropped). Regular-session 5-min bars only,
    oldest first. Dropped: bars with a missing price, bars off the 5-minute grid
    (the live tick, e.g. 10:49:45), bars not complete yet (now < start + 5 min,
    where now is the earlier of --now and the data's own regularMarketTime), and
    bars outside 9:30 to 16:00 New York time."""
    meta = result.get("meta") or {}
    stamps = result.get("timestamp") or []
    q = ((result.get("indicators") or {}).get("quote") or [{}])[0] or {}
    cols = [q.get(k) or [] for k in ("open", "high", "low", "close", "volume")]
    as_of = now_utc
    rmt = meta.get("regularMarketTime")
    if isinstance(rmt, (int, float)) and utc_of(rmt) < as_of:
        as_of = utc_of(rmt)
    dropped = {"no_price": 0, "off_grid": 0, "not_complete": 0, "outside_hours": 0}
    bars = {}
    for i, ts in enumerate(stamps):
        o, h, l, c, v = [col[i] if i < len(col) else None for col in cols]
        if ts is None or None in (o, h, l, c):
            dropped["no_price"] += 1
            continue
        ts = int(ts)
        if ts % INTERVAL:
            dropped["off_grid"] += 1
            continue
        start = utc_of(ts)
        local = to_eastern(start)
        mins = local.hour * 60 + local.minute - OPEN_MIN
        if mins < 0 or mins >= SESSION_BARS * 5:
            dropped["outside_hours"] += 1
            continue
        if start + datetime.timedelta(seconds=INTERVAL) > as_of:
            dropped["not_complete"] += 1
            continue
        bars[ts] = {"date": local.date().isoformat(), "slot": mins // 5, "start": local.strftime("%H:%M"),
                    "o": o, "h": h, "l": l, "c": c, "v": v or 0}
    return meta, [bars[t] for t in sorted(bars)], dropped


def split_sessions(bars):
    """{date: {slot: bar}}."""
    days = {}
    for b in bars:
        days.setdefault(b["date"], {})[b["slot"]] = b
    return days


def full_sessions(days, before):
    """Full sessions (all 78 bars) strictly before the plan's date, oldest first,
    and the short ones that were left out (half days, gaps)."""
    full, short = [], []
    for d in sorted(days):
        if d >= before:
            continue
        s = days[d]
        if len(s) == SESSION_BARS:
            full.append((d, [s[i] for i in range(SESSION_BARS)]))
        else:
            short.append({"date": d, "bars": len(s)})
    return full, short


def build_pool(sessions):
    """pool[i] = every past session's bar i as (o, h, l, c) / bar i-1's close, in date order."""
    pool = [[] for _ in range(SESSION_BARS)]
    for _, D in sessions:
        for i in range(1, SESSION_BARS):
            pc = D[i - 1]["c"]
            pool[i].append((D[i]["o"] / pc, D[i]["h"] / pc, D[i]["l"] / pc, D[i]["c"] / pc))
    return pool


def cents_away(x, long):
    """Round a stop to the cent, away from the entry: down for a buy, up for a sell."""
    c = round(x * 100, 4)
    return (math.floor(c) if long else math.ceil(c)) / 100.0


def opening_range(D, n):
    """(high, low) of the first n bars of a session given as {slot: bar} or a list."""
    rows = [D[i] for i in range(n)]
    return max(b["h"] for b in rows), min(b["l"] for b in rows)


def rule_stop(rule, oh, ol, entry, long):
    r = rule["stop_rule"]
    if r == "or_mid":
        return cents_away((oh + ol) / 2, long)
    if r in ("or_low", "or_high"):
        return cents_away(ol if long else oh, long)
    frac = rule["stop_pct"] / 100.0
    return cents_away(entry * (1 - frac) if long else entry * (1 + frac), long)


tm = types.SimpleNamespace(**{n: globals()[n] for n in (
    "TMError", "PAUSE", "SESSION_BARS", "OPEN_MIN", "fetch_chart", "chart_result", "parse_bars",
    "split_sessions", "full_sessions", "build_pool", "opening_range", "rule_stop")})

FLAT_SLOT = (15 * 60 + 55 - OPEN_MIN) // 5 - 1     # 76: Kerze 15:50–15:55, danach glatt (trader-exit)
LETZTER_EINSTIEG = (15 * 60 + 30 - OPEN_MIN) // 5  # 72: keine Einstiege nach 15:30 (trader-entry)


# =====================================================================================
# Teil 2 – Kursdaten: Yahoo (60 Tage, 5 Minuten), sonst die eingebauten echten TSLA-Kerzen
# (TSLA bis 16.10.2026 aus den Testdaten von day-trader-skill, MIT)
# =====================================================================================

TSLA_GZ_B64 = (
    "H4sICAAAAAAC/1RTTEEtNjBkNW0uanNvbgCcvVvPJEmSWPdXhHoefcoId7fLvBFcgiRALlbaoQRiMRBaM72zje3pXnb3cDka8L/L"
    "LTLDToZblJb8XqqsojLzxM38ctzD4y9ffvcP3/z0y5df/+XLT9/+/KfvZ/R3f/nyx29/+SY2/e5PP/307Q+/+/OXX3/5T3/7V19+"
    "9eXnP//x//nx+/nP3/ztf/hX89/f/rf59R/+8O1ff/PHb+fWv/6Pfzs3/v2fvv/+3yz/8c3Pv//mv/zb+N/vfvj5l5/+9Mdvf/jl"
    "N3/+p/i/f/O//6d//5v/HN/77qeff/nNT9/8/tu/+uaX+T/brmqb7Y/Hr+bO/eFP33/z03/85qd//PaX33wXP7qp733fmo1fffmH"
    "b37+m5++/Zsff/7l+Yn5A/MAJufbX335wx9/+fHv//7nb+eh/a9b7/Frv8wf+H9//OGg/9Vv3o7jN6//eO32v/rjtz9997tv/re/"
    "/vaf/+///ONP//hl2ZG/mf87P9dEPh66/N+/Pn7wb7796XfzUOdnPvbnmfn9N39evvba+vzCPK7to41l6/Iz3/39L3/+zT//+H99"
    "++0//rvv/vAPX37d3T6sXf/nP/z4z19+vbt+NFt27a+++fPza030Y2j93+OrbfSPvv7n//nj9386Tn5X9UefyO9//OEPr9P1m29/"
    "/v6bX/0v//6H333EvfIPP/70y+3/HLfcvF7/9bsf//Tzv/7+x5/jZGzt4zF/7p+WzXMndB7yz7/75vv4Z3xgnrx/912cjLn9eYce"
    "d813P/xhnqbvfvx93LnzZ+KvcqF//uW42+PeaS4WN8O3P/z+dTNtIrGh3DD/PU/Cv/Sb50/wm/PrX/vNf5q367/4g6/v84PjeQvX"
    "H5y/+Mv7afh5pvLf/f/9uo1t+Puvzw22f+XXf/urf+G3Ys8uv7WL2Sd/q7XNLr/Vxtg/+Vv9VYLkb/V5kT75W+PR5fJbY7fHJ39L"
    "pV2PUU0/e4w2HtdjNG2fPUZvcj1Gl8cnj1Eee7vcXzLP3yfvL9kefrm/ZGv7J+8vaWKXY5Tm+2ePsc+74vJbXe2zxzhv1usxDumf"
    "PUbZ9XJ/iYztk/eX6NYv95do00/eX+Larsfor3L4f/639DH8coz6sPbJY5yHKJdj1E38k8eoe9sv95fuQz55f2nbrmX0PH2fLaN1"
    "ljHXY5THZ8tCFbmWhXoU95/7LR3b9RhV+2eP0Zpe7q8odT57f81GwvX+8v7ZMno2ZK9l4bwSny0LbZdrWWi7f7YstFm1Xo5xnj//"
    "7DH2vl/uL+syPnl/zfbDtYy2ownwud8yvZZfZv7Z8stmoXDdL4/i/lO/NRvQerkn/KGPT94TvrVruerb+Gy56rM6vByjH02mz/1W"
    "12v55bOt8tljHHJtY/qwz7YxfVaHl/veRT/bxpxV2rVcnXfXZ8tVd7+UX/Pk7Z8sv+ZX7VJ++WN7fLL8ml/VSxtzbvBPtjH9MavD"
    "SzfpcTSjP/dbrV/K1blBPlmu+kzs/XqMso/PHuOsDq/HqNv+2WOcFeT1GNXts8c4G87X+2uW0p+9v2ZyX+8v10+2MX1+71IWzg3t"
    "k2Xh/KpfysJZNm6fLAvnV/XSxvR59tpnj7HLpY05N9gn25izdB+XMnpu0E+W0b7Ztl2PcbYKPnuMsz68HqPv22ePcd7lV53yeHyy"
    "jTm/qtvVpMy795P31z7P9eX+2ufp++T99T+jjH772199+f03v3zzb3/65oewUd/9EmZ2/DG05NMdfpHH7+e//us333/3+/8jNoUE"
    "+rLFthF/bH/8cf7Zjj/l+HP78/xjjz9G/LE94s8//xIf/uM3/+3Lb//705bOHf7jP83ferNGr7ARCqGfoRy1xischJbhthF2Qs1w"
    "fxA2QiGE1qA1aA1ah9ahdWgD2oA2oA1oAk2gCTSFptAUmkEzaAbNoDk0h+ZJ08dG2AmT9syAV9gIhTBpuu+EgxBag9agNWgdWofW"
    "oXVoA9qANqAJNIEm0BSaQlNoCs2gGTSD5tAcmift2Vx5hY1QCJNm2044CJNm+0l7OdRXqBnKg7ARCqFnqDvhILQMDZpBM2gOzaE5"
    "tMzufWR2z3AQJm1kds+wEyZtZHbPsBEKIbQGrUFr0Dq0Dq1DG9AGtAFtQBNoAk2gKTSFptAMmkEzaAbNoTm0zO55QjbCTpg0yeye"
    "YSMUwqRJZvcMByG0Bq1Ba9A6tA6tQ+vQBrQBbUATaAJNoCk0habQFJpBy+x+jSg8w8y3GXZCzbA9CBuhEHqGfSeE1qENaAPagCbQ"
    "BJpAE2gKTaEpNINm0AyaQ3NoDi2ze173nXAQJq1ndree2T3DpPXM7hk2QiGE1qA1aA1ah9ahdWgD2oA2oA1oAk2gCTSFptAUmkEz"
    "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"
    "77as90H/aMt9MO/VJdPrTS+1ftn9minyMZZLNAsMW+qOKFN8xCTFftZl25Ly/tGWY7/Jb7nZw7eS/czvWoSVm03OMnHWYXMndBzH"
    "+Eq061WRUtHpUvF/pXRablSpH5JZhK7HEx2dS8U0+XusKjY0Jg4+9zH6Lf5eHtfj03rybn66v33zeTnnzs4dpKqcNf+IVSrsrGHk"
    "46lK+vGe2ywc34umeSetqCj2YhU0mc1fO+uadixZsx915ZM+74jtoW87WNohsXvxvi6+Uy/YmnyjZMgoGSLlBhz1gt3XFGO5zmtx"
    "KiX55mdqbcIPn6esJMDk27WEHR+Pvmbkob/f6rdeWzvjIyYNucYKdP1s8j2L3OMlS28Xt6+N49vipbYpy93WS4Nhlu8S62Rt2/Y6"
    "eb00ofejnLqUHu1jW1sVrVy9vSTg9uGzFnhPpD0u57WEm3VVFBtZRD//GnrNwO2mGnq8/bke6H6ze+sZ20tLff6aHotfzabHeNUi"
    "a7n5+IjVZi4Ng6i1rrfEY16M9wOY/1guamwpjcHHR4wUvu/RrDT1sWwpqf4oLby6R/VAtnJrb7PZsN4Lj+VC7KUE3WtVP2+OUD4S"
    "L5w7v3Y8WfR2l99doT2G92KxyldROG+g6Hza45gq8fyd89uPZefvrq8sjbpWcreVCq6Vey+aQMfLZfM63e77cgm22hKfN7HFsGZ7"
    "b5bFC1TfC9P+sd+3FmZ1tq/F3JpxvbSHW20rTeZaM+xru2OrpcljOei4g6+03XW5XWPLeP6p13yYTdflhthKErdaH7Ry087SMmpH"
    "GR5mxb9S+Yy1WTVu66RR6rZR9mrcdeuulabGvTh3OZZ/ordbas215C2tv1Ha961mf1sPrpfioJdbZxb7Y6n9esnsfnN/1To7VPP7"
    "2Rjllh4fxzr+l5ZvK929rVaDC0tK+o6bsxqP3W+9jdGzHfb8c+30zsaYxMjgq2X3uiRLv2meuquFitMbtv9Sq65V+DziclaWe2Tc"
    "eKK1vBrFNki5I24bnhIv2okHx7OJVPvAa4NoZuSjtKl7vCd4o4LW2gcPXzHWZq6XbvlNB3dN5cAtDd25yZbUKl2BRRNGa12X8k1L"
    "p+m2B7Eah+p/rNzcHjs0G9FtO2st/9iW292LXvA7IaXHuLiIvjZtj/VgvdxXXu7PW225La0I+3j+/lrJ+E3r9qZRfCNras1W+h+t"
    "nIat3Ch7afC0WhW1Wrf20gfpNePWAneUIqYaNaltXy1tKa2dCbnp8MxzZPPgn6cke4jv7c2x3u+3xUQpTbVeIh9rwXi8FalrOwvz"
    "eazxjMAeNsky36/f0rVyuTVV6110W5T4KMq93CF296kbV182eekf+N2H5H8kDZeWamRh65f7xteSYnvUm/Tuhx5tyRIv9fn81FKj"
    "RpouJ2pu8rtNlztlO/zae38/PnPNt207ujyXHajubn5vOb2xpZyCut/7JQPnhqXIjyGd5SrFh66Fbpy3a5P82FJOd7mb4jJdxose"
    "H+d16PWqX0uCrarIOHt2PQuzkT8uPmduWa/6VmjHBe3XTbO4DN/7dmpkzfOt+onYFH9FbXY8nNXzfzT/ZzmbdXxhK/o7vrbu9KwM"
    "Y6C6SzxodlzxqJyv58PWImVuWVXI5qvTmVvitb/Hu+Webfh9nv14UYxoLO0RB79v67fmljXD40PX2nA/BMH8c+0FzU1rUbOX7uHc"
    "srSA970cT2y6lJFBi9b12xmeP7Q0b7/Cv97ne+kexg/FdIu3VsK+1V/aVoU0tyz1yF6MwP6ox/aot5yvuje2LCVPyOVrWeBr6sdP"
    "X6va2CNd9/F1OEvbPY55trriDbBH2/h5odersLRw40JFZ44930tHft/XsaE4l1eZuJdWS3yrXN79q9fm6oZiy9KEjau1XPdiYvai"
    "HPY6oLO3tYUxt4ylEjruu+uH9rVKj3P3vGnL9pKE+1osxIf29YSt9WWcqnKH7l1ePY+91hRxBm7YPea9xqQwe/3IWvxGKfEsPmLd"
    "hJjE9X7/bfPjdhZf+yHSrvfVXSkh6/fa2gePc7Dcjnc/VG8jrZf02imIDRrzsXR/37LeGmt5vpexvr26ovmhBdbXWj62LMnZPl47"
    "+ioMr52FOF0xK8Xe7r/jkdLrGV1ORF+rqNi19eqPkki91Bq9nolx1BG99Aj3XlL1dsu4nqBl3Hbva+MptsQb0TY5NfzchbWXMTc9"
    "/5xHN2/SeBHvMzdL72tuWdoOe+1uz03rKZW1ORxf266l6jFet57kpWyPPb05pXXTWt6P1TfvZShnbllE79yydK9jJ2PppuuBXP33"
    "3LK0y3b9kNff11biXnr9+zHtJ16uew5d72UWyl5mj+ylLx2fWRNMS4ulTk7aa6drX03rsZPPi3o5mJjrMPNz8vV1w9bexFFVLlle"
    "cquvzdG9uPNIodsMKBJ1L0ZyL9ZyL6Pzc8u8qmPbj2rqVXS08ply+tpx7WM1p5CCz59e75i7lsAyiBgF9tJ+aDdtjMVsRgV0u30v"
    "fZj7Cm2twPflCkerZt/tNaJ+1oKLjogm1HJRtvW+31ZjEbu4ZnG0a661xn7T5rZyLkXLPXfVM1H5LTVL+3hdvps6sJTVrexGW4cY"
    "4gcfa3O6brm5LGvLZC8F5V5a3Ps6jSBO59vI9dfah7f3xVoilfGvuDDteqFev7802LayW2Uazu2Wm67B9fZ5lLL7Ue75R8myR5zJ"
    "NWHWAeibW7P0s2/b4K223Ev7dRkRj0zZ1m/V3FnqstkRHzE79pQxWurzLSZ09YsxsbWCePaWXx7EP/brPRZbFqqX6jk6Y0vX4VEy"
    "I0RGXy7M66+lK3t3weIp2Vir8jQlXqb8xaZl7u7cLVU5nsxrZ/+vpPVWvEhc57IDj7NhvuiARznM9UreHN++x5N2byn5WO+aue9L"
    "ZR/nfXUoto4bb1XEz03S512yv29ZhvznlqWJGVuud//21PdWRMrdliW9bj8TVft7wh07evVhtt5Ft7u1iroy7Dm3FON596Glsbqt"
    "4z4hnxbpcOOsdE2GYPmxVnkmjFUDakVlWpV4VvbRlrsrzpCvZ3FpMMSW1YBacXZW6rvb+20dFYkS41HKh3gl4duk8dhyfHv2ILdY"
    "G+1l3G4PUHqsIncYQPvqjVLKJFunJcSZeZQyYy8ZPdsas+fTx5s8WT/US91Y5iPuZfgzPrM4ilbqvDLr6miirA2b9585G8FLK1E+"
    "WvZKSjN+LV+1VGxW1FkZBpxbXn+JPB/wfYmI9iilon+0/ohVtI45Nfv5tcsZm19r8R5j2cbZPmt7sSNtL12Jth070tZHNVoxs+2w"
    "MPPPtSRtj7XIz48u3cX5ydLx9NLmKOXpXlNublr76PNr8Yagt3pU73pvM4/wQ6/e22US014mpsZF3453J8iefdr1VpNSac+7Jx5y"
    "2FBbUg9fPl5/xRNA762a2SC5tj5iS+l9Lz2CskFLs7M8lBBblvNdnnGI31nckxyK0I8EPbOlpvGN1Vit2vNUXjrAS0e5zBjY11HO"
    "vdTKc0vpNVuRpFYtTpn9v5fR4zjSpclW5l3vdcrxXkZtdi13sZQS6xZfD21tS9ef1iIEvHY7rQw2RYa2tTg7Xqrlz4kmz1+SWHXi"
    "NTXZn+VYvD9zeNYFrY65zu9tpWCct0Mm7H2Jsd5nZfRiryPOh+9ZUY/6273FEoHv5bSU4rgUT0VIrZXlXRF2VymsBeljFfGzUF2q"
    "z1Za1u2xtn/vT/2xustbBsc1s2sR6mujZfe7M7t2t8qsmzjXS61fz2NtUJRuyV7nIBxfK5fxZlP9qVG04TrmVkdDY9PSAb2ri1Z3"
    "G8d/rQxu9rE8+3cvKZ87sRaAa7Fe2rJxeJe5KsehxIohzFeLPV+HRu4Ob639Im/m4R0rKPp5M6/FRs3AG78aSXktyb1YZ6/55dGd"
    "X86v1oy7nrVWJiq07ebOHSXhXiXTtWqd3113K7J1OcOtLZMsWpkD3Ho5LXPT0uVq5WGB1stzJ22Vdq2MNLXycFQrrjd+uY/9eJHG"
    "flyU1td6qrWyP22tb9s69bXuX5l3PresxVTRRLHl8VytJs5YP7ZI1Ak066Lt65epDvGtawnUyhNnx++s+7OIw9iyFK6tjI22Or38"
    "aHOvTez16oRhsRYL2Jln23qptVoZoY5WffkhLbD1gm3r1MhWvNn9Ll67ZnGsuh79zSl6/Tm3vU+PiG8vp3xuiXrpmlgVseZ7/HhJ"
    "by0XeGmBxL7K+zNWrcy6PCrYsRzyWpJUXRZn6vrU7v15qRfKa6/tpne2GIc4NK7muWmpYlsxrLFlmR9812+sQx/3p/tadbQyCaK9"
    "TGaZk7JXTRkV5FI61+enb+RBeUAwWuexUqFZipG9PJu7l1nRMVinq5dYu8N7L1XI3Rj8OhzZc+xknSygdWRv3dNShcToXP2a6twD"
    "37PlVJ4liwG7olmkjPKc0xHqDIW1yfEcqR9lYKdM5A3nUnrU67jxuOtPzqZKjxX3z3sknrfdzJ8FZnqcx9pfK+Nb8XTBOpYuZeB6"
    "7aZLmWx0PL1Av76OmNfu3Nrlk9dZW0eoRmmNzzOyHS9aMT6jdZbF2oAbZa/nZ3osK/quOEqPpT4ge1yksQzcl+Gw8rzp3TSF/9FN"
    "+788UaKuaXDImHWighURsl4aXeeolfUTdq37eLvpxiqE137VfC+/U2+3WONof1cI++KUxtKcvOuyeMlzj1G0buP4mexpl/bsMhwT"
    "VYOt5fmrfljakHu5Tq0Och8tsO39JLRjLtr7EzStDE63OiOutbvm6NJMa2XoNlqoy37ftWLXxlXMFZutS9XH2YiILf3Sii2SdF9v"
    "t1YmmMVR+FLztvWmaGXSaWzZZsM3qkY5PxPvDXibSN6ehXacuuXmOI74amnbTft/bXEfT0wP020c08KOLat06OWQxyoYWjyvPffU"
    "pO/j3HKtAdtYa+9WJ1+18bF+yZeRyVZqmFaLuFamLz33Z7bA/R12XcChlVKwlYcFb3+5tOtk6aK3Ukq1Y8WQ+ec6ZbmFuZy7KSMn"
    "6rUyYN2KKIyvLU3i4hKal2/5Ol5wbHgbVum1b+2rWG9FyrQ6GNXqmkKtyt1WVUKrfi92oRxs+V6RLn2dq9x7abf3eFpJx1vbsD+X"
    "0Oh2/rXIpV7kZy9qs5fGbC8rI/TyHGJsuRaHvdiCOIQYWBTNjnWvk1d7WdSrl1b+vNKlYC1P7tQb5uZKr1q/lWNt8YTtrNzF93ib"
    "z/ZM6/UCyjpi3o6lnfztwchWH3lqenNzrNVKDL3PSvNZ1J63y+IwYtqHzB99bK/nxpqvXYLmZWGFOGdLl7Y8eBE/ZGsKraeozDq5"
    "TbNFQuldGiyt+VamFLQy1DlZ7Tp3r6ZTq/6ux5OTswV6uatixb9Yi/k17t1jQaJYhJJHhXud5tSPx6pm22o8mwfHHVtw9XH5uK+3"
    "i/zoRUT0mNzydul7WZKhF3/Yt7UM7mUVvNidsW5Zy4Y6L76XJluctKVG64fCiTedZVlwx6/7WI9sGWY4zmu/lMK3u70M5x2naNnH"
    "OoWuleW02vpocWTn0onrj5uqax3QanUMoR3zfC4NprucqXe/lMp0UdwBW/yKr92MKEGWUzsrz3jxaetZ4zw1Sa9WKc7wtYkYF+ba"
    "XIukWM5C/NKz1Fm6gq0+mNfLpIRW7Xqro4lRgI2S6C0ubF7FXtdHidsxXud7LnD4TP3lGB+rl7gvC2rhWAvQXmuv4tJ8dUG9PtI4"
    "N61X1tdK/ysnrnyoXVfUOvayL62prdyy+7Is5E3ZW8Zumt+U4euQwLxL4p0CMvp7U8rXyqluWcTP8/xf+ncevuZ9NaabBLltyT1K"
    "3biMAsdPL0v/RCVbWrLH28iZcB+XcVvTZ2kHxG3s6+0n5VuLN44t17svsvBSEQeq3OmPeje2UqXetFQe9z2HeG9wrKt9DtVv6/G2"
    "ojBbnboSXZylvSIvQH9wcp4l9yp9pdwYdUW0VhYLaYcYC/CyFsqLHNLtMksl2n21cdhjNePtfCQhuo61N1k6hn1Vz2199L+Vtcfa"
    "swfQiuGLPb0+d9tW1dSOmTL78TjtuePrHlgZdb3rGXmpJpvfNeRiOee27zsN9KUjXh5haWUFjvaUWO9TU2PTMsKipWuo5Qzp2qqO"
    "ZvY2jrfctmxqrrdMLYJqeTfbtWvXuUz5uu15rIViWRCvrQsLHdesdHLKhX7dlms7RWriS/3yWjPH+hc93nKZjxfGb5d0Pm/Meuuv"
    "QzblYaBWn2sPJbPcG2Pt8I0yl6WuHxhneVQlU4uex1fO/1q63xVSa9e0PMQWh/woO7YOTGsZ7irP7kfKXNcbaNXPt+eQwCXzl0tw"
    "PPJ2GZi9Sepn8b6ueB1dvVIrzwLyeEvAa7S8l0HdaO3Pgzd/DRcdvmA1EeVW6fWO7dWxdSkFbo/Vs+fNeTrdY8tawZZStEttOpbH"
    "BnvM2L1M4e+1UujlVurlevfyHGcc2zw7r4bLa4s+mbEu+vts3F4npPf1QcZuq7PuReD1Oq+w11Wqe8n42y3PnXiM+T/j9Tjy8/Is"
    "3V5Zx63ju1chJsUKlWVHexkG6sWJ9rJEXq+rwvYyibQ/6w9aUbo+L9jrguZxZywXNFbGGcvpXou6rkUU1Eck4sJd5yPFFlsv7jL6"
    "EKrwOrzTtfQ7tORhefqhl4dIerG8vVjer+zPtVywdXpWL13e+1u99PnLMufxS0vKtQ9ZWnrhKJ9/vT6wPOjby9PtvTyJ3uP50hZv"
    "T9nt9Zl4LMBknrDHq+U4t6y5WBa1qMVm9O6Ke6vC3YsMLFNFbjdVj3bTvY4Vux/nesTPLa9+xjWvyhqsc0tM2H1ECjxbWDcnoZXU"
    "a2uje25p8Ra33fU8vXEdt9kkzBGqXuaP9bKgYK9VZS/PpPdaVYfZvirIXp7o730dmA9DXn9oTYi+TjO8ud/KgqRx+PWevD5X1tvN"
    "qd6rjV81yP4xlkdUe5nWFhe2GKKlVdyfz4H0OiGplyeh4/ce65b1umzXaf0hFGfNbkPfLM+19otB07GiS6HdCrushjK/tgxT93YW"
    "F/Hy0LfRg16eJ7758l7l2b6+t6Oviwo9N1yvSy3e6rFcvfzc0Nt16luvbwbodW2i4+65thykDGtprAI48+A5feZZmC/98n6sUjD/"
    "XB5A7aFNLuvujH3trg9Z1c441t17XxBgHK3WMdYO6dDV74061WuMtZc2t6x9wiFrPsxf2i3uGcmJcaPUdFJcjRwvUmjv8zFkW1v8"
    "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"
    "eUi2ly66bTf0RVscn+nnI0SvzyyJYTEs8D6QZOvzF1Zf82PFy9teLm1ZCdpqfWpl5pLVKVdWprLHTVJupGV0Y25p8fIqt3OuTtxs"
    "9adj3ap5Q8mW92jszdvSQHEfL5fjUQ7tUW6qx1rgHJ+JGtbPFXBjy3Vijx3TNmdHo53trPhMf3daN4kb2b1MObopJ47noFReHdHS"
    "MLRSqt9NRl8avKEirktXjvqo8ijrioxx96RVHVa6aX7V9ketw9aJdrNBOE/V1ve3inSd8nnT1qtNknYzWLk+QHHTbZqNnevY7XZz"
    "GDfHWht2Wht268HWFup2N5XzNbnv+ibZ6Ipcn2ofZVG2sb4l9jgaZ6T6dnhyWVsqmjvX9adu5yeWXsNWRpT3YpXupj6uy/kecx/H"
    "bO/2y34vpum2WfW4nX98u/evOb77V2eErvkV0zMmTeR8XPK+ebmvszMeX+mb381HLvNpbh4LKJvaawrDeq7rq3GfA72X2mKsD4fF"
    "btSJGWXm641r2HV/u9POidLLPLBRBjTuOsLt5sGKdcXMm/NVZ46sa/WOdSHS8VwL5+Z5o+Kw4zHN67QOW12UPNYiR8riYfJsyb3G"
    "p97ebCJHV2TWi/vbA4+PMmgUTzc8VBJZnma5Hf1ZT7GURZ3jobeyZR0rl2Oe++ZzL1+jhbLO25BxZ8XrEEl/u82eAn8dMyiPBUtZ"
    "uV6KnorhiOP316cFZ3t9vL2T7LlXj3Vw41qfS23kS3nffGy5jFqsy6uKlTGr9WVMUl8aJloO1sqQVXn5ltRlMeOo1qcZ9eNrh3e0"
    "RKQ8tRcXbBmXlbUKFrkZG7tq17sNVgZ9liUlakdTjpaS1JmVUuZMxajS+oTwKKNaZfLVzWfi+UdGeNfmllTpHLfiMp5ZZqTH77R5"
    "nZ/NznPMbZ6StzFxKYul3G5Zr08Z6IghPx+sVxTfWQoKXd2HlldKa3lzkMba/np5jY9uazbrowgz8eJ+tDxiNT9UOsx10VB93H3q"
    "ugSDlnVutdTyWl4nrfXVOlpmasZPy1h9RZmj8BxKkjJIJvX9gGRou75zRMokinmGtnVeQ7xdEKEpZZlXXR8AC73ixbiUsVRfGzi3"
    "W5ZWqUT3Zcy9sedLbJ8HsVZI5UVzscVndenxcsnza2tpX59JlFi7dx+Xk1k0jJQRttiy3HkxIngtiGxZ5v42DxdTLPbVG6G8KDF2"
    "4rJwylGcj/fFcG+L/LUeW5eBOyqtGJ57DK5AqRSqmorTuxyff7y2v47jqqWlrqRhpV63de3a2xOxFpRWZtxLecmgHO9HjC/3vtSc"
    "yxJ6cbBrtXC8pl3qCweyTlzHM7WOAbxOzDF3XcoQyd0Mn1nR9GVeTOzp++KfMl7V3dqKumszPbJ6rOs7RqlyrX5vK5JRmm9e6v41"
    "EcvwntRBubu5EGM9q7cTc9bG//3MnL7N6k022173+F27YV36JOr5bfLfCs8yTfCYqtQuM5fKdJH1SsvdXJ6tzC+qBy/lirbrajXH"
    "tJPZfBw8lipyzn65aRCVBle9i9a2ct1S13aU8hDL/XyY2uC5OXnPL69X9OYcjuvM+rspav2mRbm2jcqqpseJf3shXNxzX7uH57G8"
    "v4OiZnC8l8tnBSj+mj4hddpAHG/jlVv509eTVadEHWuQzdjfpyyWrCoDrzfz/drdIifLw+VShiKlmj8p7zKSsnaJFGkfu72ur1Nf"
    "+XU7T7GuXqM6fO7w+yUprfdS3/WS561e7ra+GC465WVO4t3COHVBm+eu2vUM95vOyLWs6zWFl4bs3fzC4yb090Z53E2l9NvKBLvS"
    "Miszm+OHfF3SZ52CeCcY7mY8ltWC/LpGmIz1qbfIgVk9vj06mid3WTj/Zk7r3ZZeir+bcmft9fePt1UOz9Ss1X2Z41gqsrs5tvOE"
    "zGw6h2OlrHQWN/h13fpnmX1xe/fHsV7wWlz2Um3WZVVik1/WwIsfKm2Cqq/0ZmawrB9ai4rn7CnpN7fdTfH/uhVihujQbc8kPZ3W"
    "Olu4VFp3u7TVFbNu5mrXgsEu7yHOltxXa+vibD3emna92x9VAnsxsl4emZfykgKpbxcYvjaVR1nkRcqI2rGE3dWxry9sGVoMdX3Q"
    "f5ShsVHfTTTKe4dup0c+6ijaPI/9bYGAUd9CNcqbJWKep15ewjx8fVJGjmVW40StNVpZWSKqxrUfc0yK2rw/soRryzPnUh/0jx/y"
    "7Zhtafq1pfjW8n4v7wyQMiMrOi/bWp3XCn7U/blZe9Drqnp7+al9nx3ty4J5axf3mBfwtqC27Hfr9a1dz/3sjK1CIv9j7bOUcT0p"
    "D/3Fwx5LmpcniaVMJIxlGHV9HGU9E48ihqoOexQrfLdlvenK+3JuP1MWJbwrMFaVXZYS8vLI3+EMYgb1MnPXy5qvUpZGuimi4kNj"
    "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"
    "fTv2VQz4PEgpUKHGP++XJnRDOyhiG5DNkFWVqJSGopze/xY560uwcdiUkJgwxrKYaJaV4/PeexDjbAAQSJLdijcfAkiFm77zT2Mz"
    "S84jRUKwaj5IQCFgH4DxSOy9a4Mo7BDTRAfXlh6vaBSB3GB/Wtz2q8Kya0+HLpVwXWJCzvJ7wjemnNcrYBoWYK89uo+a7wV6mIWl"
    "HoSvhMMOwJfMFkkoFCk87TOYOp0OLlUfLEhdXCJURqDoaI23PAOVYWbg1fZQpjhtAcN2AmC48kYQUSPXI3olDkGMLxbQrSo4MEPF"
    "LVHjKVCpWcLbyhgGQ0jYczkAGhd+CpEsMZZF1hJBzT34Mcq+U15PSatw5VI3DmAGzkR3+6cTn2ng48Q0zlUopA8q48JtS2CRSAiH"
    "a2VgKZmxedu8j11m49vmBD6OtCKu4ITseQT+irp1OSL0plM6i3eZOULvXTEHozzdfqTC34j4Oxh6FRPQfjA+VI/BCRGdNO2keozo"
    "wXNkhHDCJ0mgIglNtxB94rDcbFjqly05MTm1mfRkTkp8zu5yimrc+XhOkixPJoFlmZP10+wrKKJjXpLggCDEV1SMpqzAQpJzhWz7"
    "EooXSTN6aR+T5pNz0jUHpTbVFMAsoCUasuAooHSo95roswPHUCTqVBN/cj0WwASUaxaFg7S/Oadr/cwOgAXstEhXg4v7CqW3pRH0"
    "zAxWHMKzL02EY5iE4lwI4zd6FP29o22sh4XsY1yligitHsb8mMFKFEnXLMmKP4n4JCk5ydyeKI0YY5LsbS2v/YIWyllTFxVnz4YO"
    "GMlW4Ym8yy1NYF9VE2hJ0jdy9KvpBRSM1OZzlPDa7Ef4dUY5hEAeAkABR+HC91GM4L8G8dErWTBfQ+ek106pjyBvIB8SsTHkLSmq"
    "LKX37G5fOVHuAHVn34KxwITthMniGIJunGiDBJCspKFufRJrArC0L3vE275ypiAxxFUBUoWuQBbHAfUblvlv8EZNmLSoLwGn74t+"
    "a41yQVXZVpoG8jT3NF9GDN4TbH6vaFeSDsA9jUClnLITD+QJ2QOF1snqLNT5F1bIHGaIfu0rszdnGnPNtyMKq0WpYRpaASpNIe6Q"
    "39duTHkd2SQuXhh8Po56xx/UKtTgIZ/b0lFpCIR8CMvi+0aNPf/LazC4Rpw7ySyt1F3Z/2xmNpA5CaB1GkOQhUP5JeG1TLbQ7z+6"
    "TECWyPPzIs1Dy495xE3suugS/L72ZdL0gbUj4t+C7Z0CciO+h0ROt6hg84dUYIc+XvlPI9HtyapBUXxR5crdNLmT7BQWGtSGni+Y"
    "CvuYwnsxRVNOMRumMP9O4YuwKyXbAHp9+LWnAC+mnqtTrPUJQo3SPimpqZnt6TnXKU1vpqAzMC6uq9WMv18iy1ozrLPfb82HA282"
    "OGNXhXwTVwid+zwM4v5Jfk+1fDGUSmOTlXXreHYB1gqb5RSK7ykcmFNYqiZjUabyf6LQ+YyVT0G5TNmWU+ApgAdXs9I+sY15qZmp"
    "FLZTdPKsbHrMytj/4KXCKhZ9oWqnKWwHU9LPU2pJpgJKppCfTI852R3tZdLApdlAjvqETmaTJX8ki0HluiEl2R3tNWAobPbul14v"
    "0M+R6vWrsfXsgTZpup1J7b4bXDxg6UI6heltXg7bFCN6CqRwKg/XnNGlfJSkz8G1ltMN8ck9Z6d3mzWpqu1ziWePvcYpHvIULqgp"
    "bkukXsX8m+xBTAH7TKW2m0OYgsPZpc8QjwO3nJDKOYLxFJYF/nY5DuM1k4NNlMfk2HR41rWTpwdvW9lUWEm/2mWRaW+fGBAtLNXv"
    "wl85FVEBIbkljOIfKj47oG6gEMNk32Eu2YMCOp8SBphCyCdEEi9JxKowUNrT0m8KUZpdSdd/aSCKq9/sYuBp5HtjJGecdUprZkzM"
    "aahNoUbDy/TRm9ky0n2ZGTLYa8ML0uj77XZoFxiBNxXl4qM4eSCkuACjYCKAZNI7O5F2EOdFI1kAxQA/R2nXV2c+Cz94lvCPLEdW"
    "Le3WAE6K9YEWgeyAwHlLs05KHIJ57zLLHHrCPE/+Ha310uj40kwABmXXcnlRDH7FTtc2Z6/Pk0iHrxSwK7AuWDkiSpGJEwTY0hQe"
    "uBsa35RuvoZfgx2fTuLYSAwJcTE6ggPgeLnFshcmewgeWJlc5vR5XeJP1WJXzq5dwfZdEWtOcKmK18P1vgFFhWiyxbU7c0WqgV62"
    "0pnww98z60yVzEjlsTyRkb6kPRyuJNEI9T9TZ/GGun98TgGWkr6FzdhQK5L4huMMdr4IeeLE5NIaOp8pFlFbvG82Kxw38+MkRufo"
    "kxejxsJjlMwXrXEDP8pB4whpHGdz0FjHmS3wiS3jwi1hJHOCuL+MhFPedUoSOnH3tzU6SKrIwJGK6dcU0jt5CEK5CeNvmLBVJ5J8"
    "LETWL1OLV6YSc07hdcejyFUcQsQDc880/YesFD+jGMVguNUcgf9FMTJ3hcZhSOJw7iK8p6+BbTBFwTLVUea3OY+VrfDP+F5CSLIk"
    "5rkk8rikvcuSWCRokCZzS7HmEMTXkqpbXLEHrnat2HM43acbM1MllrylUELYSI0PGo7faNki1PpX99w760jIq8EZmmiBVntOUtXL"
    "YtmL3cmsXkLkG+1r5r6cktyMzySx9YNjIjB41UFnimhMQjNxaBe573411xpBdK3Z/9nrN0/1n/UlULp8yAMMNaXMInAQrxp3DQQF"
    "oUAlvJlSv4VsfesrpV9ROWUsUe/ddrZf+KJfV2i72ZWgFJ20VhbLRLDQ09uHTuWdvKvTdatMabMFCIBk4/QeztDPLBXF4A0ApPLT"
    "2WlKg5jZbtIBfoU2bZktokaczGFQg1kCp8mb4JrC1mZX6lmfBEAFvQtMcwckfkodxxQCvvAK1XA7eOOcFMGACFh+KrAeN72IpyfI"
    "2nnCuDQq5m4QkgvNKU1lZJotWF4NufJcm7y+7B/PAOT7OXKhmbDokqRkpgDvpnIRzSL7MVojjqgXriJ6mTbY78nR7ub5VXjcZMbH"
    "WQIKBC4uEkBBF3SipkUDiKfAoKqmxEuAIdxao3Sj7xQePvqTA3xRivYCMw2v4Or1PCruEJU7xGtCkYLi6BizCif8943Xz5jJIclc"
    "BXweScrvw58tW8z2o9DGJcYTKH9HinC8khQOijJAD/Ehk1GmRNzzAq4A+z2D2o6NFLjm5OQ81zVmZriNa1iCLxA8oEQE+2U/OOCe"
    "P2XqA3uyc9j0yN22pItR2MVp7WI0aZFbWBmiv9KWEVW+hnsqSiXPUL8AM0V80dFnfK2UsFUGAzKD79QBN8WZajUfAfjDAgKpLtTi"
    "BK2bEf8WOFC5R962tExRa3ROnHN3/1abhUStsqd24VZG8YxCuZ+PHVBpRl3b4Zh/7JaIll6JBrVvoTSF6j3qUpiZK5vpCXtARqjt"
    "IZfQmk7pvacfr+3uqWpLsswBH2TYwBK9O3cp34aYUd8Iff9kukYlbG1C6Rh0qUj/1nZd+zeodDGZaEDumoQ+XnnYlzbO3UIcWuVn"
    "jMQuynQpJgB4SvXZSpMatNdVVtSgTW7jhvbK0sqtKYTJVup2n6aoQDdQX9YuDKftPyXybHwues9Z3ilnF61rWxz9JSOR69xTSNqS"
    "/5+kMCBwbcwEu6icM1oXYQbm0sjKGjWgHPYy3agd5XRX49tXXQrF0C7x1I5NiDia1qPDwFrto1eanbl5fmkMelBVGvaipqWRio/O"
    "pRtdolkdgSJ7ZL8BmVcD0ZPrpwkC3xuItqMB+pJuaE1CvWiqSP0sV9CJlBAl+NXZ8LcJK2xTAygoeky8Yl0DFF3SYF049rrm2NBE"
    "3FYvzfIk67oUPH0ajZ+0t0H5jDZ2xcBOIK49jywdaU/QpfYWV0Ru+ByQQtR+1b52aZvgrbN1L6KZ5R7dvuE2NpQBOWiKrSox2ZR/"
    "er7VoKFLl0P5Zgovck4E/cKDHrt6UmnT96DpeRM+8aATOJ+U3lXny+wfKjI2AZWqWlutb2HzZukpQdt15QmvkNP05kudWZ67VOdv"
    "VWNg3GopAUpxPwyfXitsJ31t6REZMJzZIVP3TxwuLttvYS7XfQ21DobWsI6oOnbkMV6eBvyd7GVtkTWluYtjTSI/5rr8b47QlKL+"
    "s4/OkgXXKjnt66c9B7TGIih/1p5iXiXSp/YHVx+mEF8+iAJPKhjkq7KterqypNdqnN2pu0M78N+gPk8cC/TuM83b23slaBy3pD28"
    "aJ+BSf9ydVxXaG5OlC4uyGTxVkQPzE7UNtzjYTI2AgtjQ/zQbEabSFsAxt3epnxrNQNu7a8bK40Cn0L/yrXvKkPBpaDQntERXUkM"
    "fRw8NTIyVseSBMaVk10n6hYa9XTkFQ9DB7BqthlNn98N5T6g0n7tF9lZMLyObLQbFLj+vYSzCq0xZ5zFiJmeomz27eUueJjSFGN6"
    "wy7Tub/MURUsoxy48yrsmOJTI6gOLpdRPgmMKbhmDeDnbG8zr6+WF2lNUEa326eesB7VrtkG9mb8suwIEFFz3ojTgcp1hKmgJE6N"
    "0mGSNRgSoqe3i/8aJl8Y/yA+5pQuG/iuYVL5gwlnSWhlho1EJbo4lT+NsXCPFhELmPcqTgrW3NzzJ7nQTpxPsKLSyiGU26EJFV6b"
    "IMXF+ZRI2nUl0MjpPSWmcAZds04jloxXDtjKJfsS1E8TrcwUrpqrDPvrujqLO4uK7iit8J6c+pma7QrWqxCCAY36Ghd1NCkgCeoi"
    "App7TcgKhT0x+WsVfiT07LxG6eCusPIlPfA4Iyf8plMi31MIysMKKmr3PeX0n2IQR5VKQl8Zou63wNMZwh59xg+YtRTnSKE8oLxM"
    "I388h7kUVMLbL2hpOAMUBr18ioqdUtSl9pWDtARoL7g7rX6rglUrCh+VjPfikN0UdvkpkZhAvrSod0onFIDumoDBBaYcQp0UgpwU"
    "cKz93CajdQM41JYSA4agoMN6J4RhE+T2UCjbEYEPoG0paAgpQOrEVIb42WT0Jh1YS3Q0MNqFMWmMGo9wa1nepfjd9p+j1h3PxR9L"
    "IMl/AZVpBQFCwS8k6erbGDS7LNwR82cX3iPSSoSq31bs3MjpUSH+/Y0w87JoV8/D4h/40T9L7KWgKajijpY29ogupQCHyLC9LBon"
    "bJYYPDvA7psv8e1FDVH9cPzdQP2TAhpv4xafmVt85gBtSLGlsA1kUDQSlQQQ2NyeZJd3Se3OmbtgnAbF3dJVERZXQ1janvsshA47"
    "xA5d0FZtL7TrrH3KV9oaJgkPNeVSgy3YoRI7jrvWqk5V/UQm04NZhY7ujFmlPA6mbMr2eqomdFm0giUYsz5RG/QqtF06Ahc+F6KD"
    "ScH3zC/mH2TibH5KeUfNiE2MmhRvEvt9c+VS4nquWDcy7GgJX2t4EjxlNZneuaRDLyPp9GsCgO3iSOZlmn1NXef08zL+jO6Cs3wI"
    "AWhuOu/YKan9KYl8VNNuNjCDCnqtyLwL8ovZBX2/8EXAbhu9YEqx+Rir2ZPbE3vokSm87OC6uRVfG59sEIkeBqwIwhs/lQPdy4JX"
    "RZVnb+P/ULasgP4svAhJy/mFaoC90M4Onf1m2OHyC3n6t5r+vysj7vpuErEhpZSx25GockEKhIZagEp2FIpFUDtLQ5pMvgiD/6x9"
    "8bA2PB2iF5hRH3Uti+Y1wRs73aPOS1KhmMobIZDZIS5FVN1OxT1DCh/niLynp9hFPa3EzZTZXPgXdywx+4YJgR3Bbyw7rDMXdPHU"
    "0m919JTpg3IQ0ZNRX7SaGa7jKb556A0CFaFUFy/Zfen/QjWRQiB2FTC/gB+mQlei6JZATkI2iinBLDN9TPDK+NxE+N4PJwbHxmwF"
    "ywcYG8fPKCRQBdtfdQ9IS/XJPdunkD3PEhEZdgnW8VFUqKHFlB7LU5s8+3Ns6T7kSf9CCNK/falCGhEOd1exZOLJF1R5srlJ+Vtx"
    "MbThYBAgTxLepVKwmQXNrBbYCKrJtUrIbNOzWTiI1mgP2JW0xrckVypOcU+2G3447bf74fVf25VHgUP+Z545xTBozJx5QQQ9EMQC"
    "9NNHlxVJx5R/7qneWhWzyU4oQYA5QOEHikMUAGOG4oqFllY9LB5tWB1VaDSlC2KfvlOZqF04T6Ql2b2licKlkbHl9Jm2ScqDpF6a"
    "wH0JAciQ9nx2/sLelzC2rCnOjDB6L40Pxpe4QnIx8fua6nBK+741/4X3oEsBfvtnHEQyq0ZxhSURGPLEBNi4BPwYVnKyC4/e6jab"
    "pdTHDdTW5quJoywMaHiQ7RKbt/LQH1SmNUNkadrdv64FS9jkMMQtr086Iv009sFtXxBj9tKuZ14Se6bClpz8iJLts1TN2TBOD79w"
    "+HNJmxT/3jMEVsUP17qZaFJqUNxbZHFlczreCktzgtqW8pbbJd7HoWhc/+VAWJOt0MSnWJpGWsJmjKWmOsslNH7rguPij09Q4bkX"
    "hvV3DgJ50iVnLsolgDd/27l0hUECCDR88o9LSNSXGD1Lzo8gAJ0Cigk2YMGeYfc/HM//xouw5GU3Q4idO9e5+Ya9NAhfhefiZMlC"
    "6+Kj5feS6tY4dCwJEE2JrANfhhwJsfasIAsWhKv0XV3Yh3ivJ35ZnH9I/0ZUJOMi2UK+LgvXQ9GabV30+1Zmu7Dz33b6rJ/kVFIC"
    "lKTEVMrcodXlOgrlVAqSEYVL22XUQUn6Fr4LXcDKoqFsWFUZ42TIek8TNowqKa9WT30Tcwkk5v/Ip+bwK8z3xrGtpS7DksUAILEd"
    "Xx+mM0+zJNg8S1zUKHcqWBNt8Y2AgmZBN9OKUda/BpyK6fbwmf1QKTAlUgUKgaN5xpRTJS4yD4ztIaAoCROFfKCV+Sd3wOnJK/Wy"
    "KspO6ByCEepxRPEEPFBzZ5IUW/VqZhrwZTfbiQnD2Dl/mEyC2J9yseqVaTbz7lfC6ImWCSOjQiWGzeO6Zvgdd9fIaz8ZcqMAUTMd"
    "+MG7IH5X7dtrursmxeFQCegFbIhVaQM1XizaYQjRKsg1c7JBtg+fp4aQWQ1Lp0xshLNvJELfZjammzrjvgf++PGcLs9hOQrfThHV"
    "zjquBwkKs6JM+Mbqt39+NRqd0lgHmx3ECAdXByPEAsqDqWSx6yijmtpByGGOpR2x2JDGlmIz1W3eL2imiU0SMcOqHtAcBqumroo2"
    "Sn3IJlVUucOHEsHUqtAGQLa+HYKjls7asJ7L/c3t352awu5K/aNHwGFvRnT72vVDQEJDnPmge7nDnQaX70bM+m5IBXC0se9HaJN3"
    "bZVOCW40tbh7W5hI7Am+7OfHUvQuMY2gNcOIehHvJc3gG7WW0GYTJLljRB0ekrQO5gF1puMXqul/aebODey5A4vi4rVf+eRlDRqI"
    "C73YkKKK+Epn0eJjcygD7ZCtNYTbFlzv2o46aAideV6113eSDt3/0ui4MawCtPfKw2/HdLbp+zXVaKJ1hhS8DrGHhpRL454pvTG4"
    "XUhIxa9f/fRcaiJV6ddgg5mJIXOnpCJ3OufVWaL+i8BPYU8RYEXATBHTi0ipgriFqPyYMHzefil9cIwJlRpduBGSdDyU6rbJKaio"
    "MkTJLbtQgA1hhAp74g5p0hl0V4taFku7Zm5PWqWXoHYerlHr47oPXMLQ6OCQCui7ifK3WUMRaqur9we1t5MTprwNSie3+w7oTkws"
    "51OJ3P6FRIYwcwFvCpYviXQWaWEXkMjwpo6uEN2LXRByl649i20q0gcnGDRADZoPRzK2pTczXykiGXfP4Bz16GOOnPFlcr/bFBN5"
    "UUSbU0az+RxPCCxsiUzeRNyY17yUo/lNvM9MGH9AGjQ/lJaQ+bvP7l0mPV0KN7aMdtDRkvRqpd6+VI2jCkver7XMkO6eY7VvU2Ns"
    "vyaMdFwhOqRsH+lO8qlS0OVNtI00fUWjOqXEK2orCuvOjmy1xF0B75Oc+be4l0yP+k1laSazhVuLj13JaIK1iThlRxINl/6JWYuE"
    "tb7viLyJcSiqcfRU6dIHrAv3ckgCVITa6GLmWTSIsAZ3aSm0iVku+6GsDypGlYs2Kt01m5t7IJsvXmexRZ53CyOQ8+yV001B9W80"
    "GJWC7J1rf7qjJH628F2nfpyRMTURF12iSjCvKzLycI5s5lPhDd4ly9hrWF2v1DBm9R/Dpv5fXWgXewkISWzy07cXXL90fPdCuLb7"
    "L6lxcTIQu8M81XVXKDT4Hs7idjmN+1VPFxKm9I4k93jRyhexCXgKbECP2XDV86frv/ssLg7oEiQK2nvUKzcgBzujKkNgsENqtIp4"
    "D0Ua8uFd69e8LHNp+RCuGldpNDzhnQrteFKr4hcO+Or9QRVcuh+H5Op3W/bb1v9O6f/4+4///f/8z//7P/7bf69ZUrSZQ1vZmV9N"
    "tdY3QZwlaZ6vKsftf7/uMe1r35vbz1BMEvZPON7a0QMoSc4jSdIqSalTWnKEpyHl0Uk8ZLuJU6iJ+0XgHvpV8DY0MDkKvbOAh5KS"
    "nOPbKFOVkB0wQfhYAXaJ/a7kUOmEwMyRWkmo3DbD9LN/7FI+S8DT5PM0SYQnSY/GtHlDYUFPOcCvTnnC2OnASJJ/SZJmS0oVnnb0"
    "JApeJCcwOFA2SYJnuKkdahTCch7JyVvHtm9c0C5RmXDisExCJ9Vv/4kkLPCY/NPvSnI4JyH884/gBSJXOGnKLM1ggqhyF19a7P+n"
    "9Siw1NkcSZ17GCftv5cEI2RXiDApwe+3V42L4+S6QrF9H9B5j3R6wmekatuovtS5SRgQIfmyc89ECiTozCPgCp1ASRsWYc2GKAUa"
    "4wpGTVYlJracqMsk512qHDO0n5GtFky+8NYnhdMl6YuaiiQ1k5TiJ+E2TVrvlgp7bEka2CcNjKTiYZ8PTXJC+uP0JFLjvqKpcZYm"
    "CZILU/tp03T/rNsmX/em3T6T1A3GRbTM9EYxk2QfIddkhSchsElC6wGZnZ22NSX00+ZQA67YtJoQpxvJlyR+ni44vQ2CIBpJrIqk"
    "BDe4lDupLSqvSdJeLNQtrDfmP48e0lkOznAqsv38vJxENeHktrOkIkn/M7z08DiShrqTMC4lqfNIkuoN9FoXaxvzTLMq+QFcybu9"
    "snWdVvogPsAkaYvZJEEa0cf26BKrH1mqQJEh20xnseS/k8QOkrQ5TQqyxQgOBiR8SiDEcrKIbh+BTVhI6DrDTCK7kfMYSQrS/Fw9"
    "D3HhiIU+YsPnynXgX8j+cmfpR24MhXda4Um8l6R1HeFBccKM0kVG9/s21AHYAYQtfMukeU6U/k+CYk/KtYonp5OUI11lGN+XsR4X"
    "3vbkfmaSUhccVJVPHN7NSVIvieO9dqHk39nd/Mp9Y+GnrTP4nrIYzlJSnzwvnW1O0o2exclIqhNdJRod8ayCpX1NEt4amBOkGapo"
    "BuHtS9LiJgm1DdZXrAnZuvbose1rzV65grSJGVKThBaSA6KS5N/u6wIQD8fGtlcRx6iKoQN6SFJrXR1E2VIKyI9O2SYomiQU0cFq"
    "RSshehxYV5uTM2BQth3IRxefsplJBFdESxaClmDeMytJYmJN0sYbJ/IUu0kcFPGp7P8eWwN5ZbuntrfNJBZFJ5wHNJnhDz7lFGO/"
    "VHNZeil3rCpJY9DI+YGRYPunzfo7tfjYbMyul1p0klc5EtipbnrYdj3/mkiz9MLGOUp+pRQVJy2ZTdKcPElT7TSiJUl8uA3eTVKt"
    "6labvWuNVvpz/Kq1Q+gbLD/t7sYcDJi0ehqs6vrac4jWIHn6PXR358xjY9XvF0QmiAoTR7MCG1QqltK8I0Biic3A7xin1zvlRJri"
    "0GnEYYqdMNnmkfqlwM6Hl2A3tZsP7nKm1b8m+24xJg1XJC7Ib99qzWov3aTdHLKyPyS0pDiswKzA+KxERUmbhqUdxAoIdJUkJ5W9"
    "Njh6w5IjXor3XdEmMv6rWKNyakktjttetqKzj7s0P1UOx/uDzv3Zgns4XIMSZ/ReefMTSRu2J/Rfzd92LkGMa0lYVFjDEAkS8Wb+"
    "Eogz7ZPB2LwkTBRQDHl2+0m9oZ9JYFd4jmgwMQai3aSbkiIjMwiOa4RtUK2vh507hauRw9uteLLjivfyxyMXfHpGSwI62Eu6CVXc"
    "eZdkMcI3i0zWsp/sdnkWVMV7vZK7kRWvFF+ijZAvxpQMvvVTLWR2KbPY+1mKnTNY2nPfULGXS5WRWbperZ89vzyB13eZpZdmm/f5"
    "l4X+KysDKS6ZvH7rybMw8+fEZhOunJ5IVlwNJpxyG5kbymbGi+BbTxHDbNK2tEtEaptLlJE6D6ucNbNFOyUrRUOWKFceXNOdAVSr"
    "IABr7zkAeNlp6eSloqdcxPniEP6kHbKcc3jSqc2y5F2ywAXyYlRKRvbJBK7Ox7IuUjlfRBxKYVOhZJm2IgzupbCtVaqEOoqk7ouU"
    "0RZxiIqi24p2A7BL+jvSeUWOsiLVyPjVGWgu4P5stoPMrb2ORLuCVhZfHjR8/2mhFulriXsOES2iOIr0PS/AU9mr7ANubEERDr0s"
    "jIZ5yxFQEotMcfXwtbztCnuxRVhdffFZZmhEkKLz2CzoqLOOlI5dGraxXnb+ciEP8NszzlwcTlAKH8VFCk6LhIggvSOVX3TfLnDM"
    "ApdOf6cU3oNFAJ0mBS0DE90feEMR0KVvgvNwLFW8u6KkCpiuU1YqUw0VIQ32GWKJJ7v6N8kUvizCUBKIZ5NXgj331N+FySwgQqDB"
    "KW+myFc+L1v4z4RPMzifLOW9Ks/kkHBJB7HS+DgolUOjRTqRQbGcB00RtpUipOClPsPSW+fJCVS0t2SR0usiMSG7whD9IpFkTIJd"
    "eYltb8FKpLnIwsSIxuhru+36jCixpJGHWRpbR6Vxiqx0dtFL5zR3URR+EZ4Ju6IzxMdGE2O+eD1/OJmkG4tU+Bdtklw0B1KkTKlI"
    "TURhXpAyResKg1eRasPirByFgyeFAUJFvBMsAzmtRShU8HH2FDvByg3gKxKowxXaQFLvh/Hsw1AswnlSuKyn3Dm+suQYUYSDXTLb"
    "daZf1WVRDwSXSNA0ClC2qv11WeDlakKBd9FpMqWKoChYxy6RDVmm6vMaHB98VDVOluHKARorUpVUNMaI5aXtiloT8zvGvLiJw+WV"
    "FoeFAb7RBZkN6REHXdFnNoPpoXMoSrleqmxTJfgtCr2EiiMbuygOAkcSn7kleCH5v6EVowcN9QAplcG9+NVsZC53OWzN4ftZKfaT"
    "3I+uVEVaNYeHOINaSwlOQvIdMeR76EU+j4pN3EBvvMDyKzE/q+6lygV+WDr1InR9z+BhkWxW6FZQg0ncQ6e/2vChqSuLyw6D9u0q"
    "Sq5XSiSmppQPWeIeIoV7sRXhQbEr5MEWCRYUofktwsaLJydxBhp7XUkdBnUpVXA5HFS0x0NohPPsa39xjOn8kqywdrjdp3OYN3eu"
    "gSN+ykx2lojb4d9yrAozcUliU4vzVjKDvWAvU3UO/EJqblGEurfkYOEpR1SkgiELf0gRjhj3XM/n5Eij3n/wyZIZclGUbRyDZ5EA"
    "mX/5lRTg7+SPJFHZ6Z99miR5c149vJL8v2wiZMUG3oGWX0xrydMkUeEBnEPT5S2Bp8XKPHyyhFGvofsL2idunpmGJC8NpooJlgUp"
    "nAXjFd4jw5KC0yy0qlkwrlkpV8JI1/MvdHxgFih2t6Q0BBNDWyl8UtUAH4eIlTMma9lVliIvaI7zTIVE2j+tkb4CQo6RXSE1ao9G"
    "h7svCj/6YCGBwihPIEcc0KTKEMjsZnODEgSBDtKYAVcww0cgA/5e4zICs3mvkymttMCzZ51qpiu6EM/0NJCABXyAHorQL8MxoI+Z"
    "goMqWmpsvkZwiUzAmviwr3KUV6GEx6MRifzRz9fEp2QV3FBFMdaydf11wrCb2snKXaVGqSJw0+snR1QFtlSVD7ZKe1i7QmZz/LKT"
    "wLImJmAvUkmA2SdrAyRaJl/7V8tZhOyqaI0HlpYjWeqiCgq9APRyxsun0DfCn6fzc/L3F6XECAIDUkZfBDpgVwisWgRgX9Qiwoho"
    "tiXXCO+X7HPB/ARfJv2q7/hGeD1ziEHCB1VmQIfADrC2RirSrCiQJa/DwY/JfpnqdLv2OOCwGPtM7ZPH87np9MVsRUq/V1eC58qs"
    "6Ff6gfLNW87XItVCRXrH2kZkA34jpHs+aMuky8FTxfqtyDiUtcb+6DO4U9+Eh9JCV0kAVzTGsNGY13y39q3OYliEQs/DRY3nhe30"
    "zSm3Ks2MoIuPMnK8ERHlT3qvSKGVh5lsOe9CsUvP2Ze1U89RcKJqo+4qLXN8Mm2qPhBh/O5UBlX8Bpwgx0mon1qlBQg+/v4XM9AP"
    "yoginHhYBPtnMMi29+d8sG/xVbYoMlXkW6zaUBD1Z6L/lmQD1Nr25TxMFze/i1R4Ry/YmirZ7E+jCm+aFL+2DS7Umcsr1riSWaK6"
    "yerTyfQJbSYJUw6Jt3IQKtKArB6iE5fO+6L1fWXfqpRPtHCidDZlJaKXcgZYOUOqeOSVG3ZWzl9B+Oe0Z75Me1Vw57C5yMLJLHRV"
    "69SrVINVoaOrkiKpTtP4VZFVKJRwT/tCgf31pztpV+gIrC24QkJSUbBgEz3Xw6RfAQhbpuvnQwtWGxtq9q4l08EBsCp9C6o3uajC"
    "EF0VeV6LrraTRts/dLK0JUZRNdqMSzQXWr5ehTu7Fo4smSSsswqxcmV6zcxrDUv7ICSp0rqvSgfYqr0AqufOXRgPwwPm9mlUVEn3"
    "4pVfqt3raTSVAnPAlcXmfzD0e8BsR7wDZmscvyEfFZcIdFOlTwKuUDoV7yAYNiwK87/3yPu9S3d5ps7sWLfT+sejp45SZeRM5ldJ"
    "PlQBXsQfwt9R+NCMplLa8FZJh0CjkTgIZYXvwsTK6rJoKqlQjkBHZ7KmSqcN33bB0+oEDggF282k/oUy/jVHx1BmeBrqyZz9nooU"
    "hiF1LDk7dgiF8hLZ6mnz8WPTd3QCp/M1Vf/k7s5qLbySsq7g362f4FERCgfESM5oh+n+E7mNrNzZAe1f8vUgHrn11D1ACQX3wHEd"
    "NtX2Fetut14GL4ldWJKE1nso4zXUbZc60MLkGz4cOy3Sei2mEWT3z2KaK07V2EVnW3doiMhuOmlXihSUelBszV+ApgyugQUAgXJx"
    "3R58SvHFKohb2f4bN6ZAMuNa7hKE3aRsswyRMUTUtk3nfI6LoqjncJ51TfVlU3LsFbbCzQByxzSmfJq96C41fxRBllBILiYGrbb+"
    "i2DIPexEShlGETi3+/ZkBU/1yYUP1pWVhHQKW+oaY5OcihDBw/mTYOFt65AiF7xbrWKpV6m6q5KShk13lKcEJlMVRv+KJO96Y9vX"
    "64lctyo5E+zOdLALwH4F0KyY/3ofY1XAQ7ATT/cW5iobk8pyXkWP+zlKsQpuyAEzspdqGuHzbQ2ho2xq/IKYVm2XVCWoXZVjCyNi"
    "Iym0vM9Et7sm7GPIAIQxtTbJ81fGiLhrcpyitasfhJq/r+klRflV6rFqFwNJq9SrqBJcIVGXUpkqLApVC9BxUx31oaS7hy0LIkCb"
    "KhXo1XtKVa37r+COyf1DLFaFTaZyN/u6OL2EW2jrLE7cVCHbqVpdhUtk/rtb36SGoKntLBVPdYtXJ40iquRAqwYM4kv6OeK8SSil"
    "iffQBI7YJFvVhD2jSYC2cW+PLll2u4WsJlzpx8K1ycZfEwFrslWaQPfsHj4scUlmYzVz89d6hwjgLth7Ur9DIQ2+XcJ8PHxW7YpL"
    "fqm5WhITsWooui7Zq5Nzp1WAinUGu5fPIOQVTNLL7/WeInib8l73UFIU4+m8bTgOVRWPWIVCsyWCLFXNENolXlltwI7fnaHaLYpb"
    "Q/N4NDmXF1nb7zHiV1UBVdqV515703gKtPetKc5ti1oyW5GZ5/NrgctAaZBQKmEhhAnBpk8rKkxLq1/TwG4SYc5c/NEy+7xNctXh"
    "Pedx1tDZ07RNff2f5u79t1laQ1QDtHp13sKFz1hjflpaNXHvceX0kVtmTd6kPiQQEnwFTWxmdY8B0cndJEqDLyPVIkUCeHThKz1Y"
    "jdO+aoLkalr5iu1PIQhpEtQkstCUAwX6Z/FpRFZ3kyQX9tYJ7ayKrsDP7o1YJqppfllfbIvGe5O0V5OMWFMSaeyL0xry5TvPoCwa"
    "pUlZDsSHDG3Iz/3Wk4ahgWFz/apzWgqUyLJtsHt/DgN88WLNxzY6HkSHmnRNbZk7nTekrcr+ZVcx8GCexrjbLb8HTxcV2tVYWCJV"
    "FMRtSRSKL1358qE2KbCrQQpi//PaUiZR8+2oiCs153X9+Lk3Gj8HGNXP22qu7n+eMbKx1DSb6imYL56sCnOnLjZeQTHl8B7ZZmwG"
    "Ki31ZWeGP55iZ1L4Od5jpOdteU3UPxnK38YgRxu3qg7eNi995bsSDPvzdF/xHFa4idkJfY0WyQR7IsIl4D7BuXzmKkIbeA3/47wG"
    "Uq+eCSfswTOXfibHZSax93wt14d5o07B2FUpra/Cl1Wl40sV1uoqfGnVYyq361xv446FQuMuVThF3H3kaHbgqXJcRChVAu9VDHB8"
    "x2nJTc7CC4qlOmwGZinlHARiWHdw4PFswyHLC2i6J+iw/3mPORExzoUthqZhjtvXURNaBIjFrE+E/bnJLMSvQ1GFR9g19mmcbilz"
    "CDWNOHzKfYRRJnHsWZ1KO5x6dWfBipAQKTdUFURU1QKhMCzBYJkhWd4RyB4nG5V50V8ml6rEV+4/NMfTe625Xa2vrivBj8/IdFUO"
    "J3zP2xrkmXqeqiGxi8EWXzgLW3bgaNUO1/buL+0E6Bv3R+9bJY0B3+fEP7pry34ST8aWoM0IdhiHRwRsVyVDFnhesYkqx7J5J/3D"
    "wYvAx+Ml2U54YU12pYm5JsdEE+HFleuBM/inMxnTBnnHjdM+CLmYyORb7sv1XCI5aoIDbMIL05AaKiPntO4OkW0EwZJ0h0xOe08T"
    "Ow3JRzugRv5ZnFJF2IRgrAkorHno4+s8NOH1bjMYkXnCZianeuNzmzBS+Vye75riek0CZOPBNMBBJFNNaEObsBJhDnsYMENuyzZ+"
    "afWGO4Q/ZqN8ilnYJBzaJldCNIXpN+0Y1Zhpp8nxG7xscY68SfAVrydBXRKhaRJqwvpnk4j3pMS7To0aihpvgSWavmmNQpMOuU0r"
    "MZpG7OyujajGr8MDht14QZaEQnlmO1uwrUo0TEommwKImpQieqCTI7os/6hmx8TtV0ArMyk0gQw1gbk3AbW3FAWdOVYeevxnHXns"
    "tbGPB01vPuUbjr3CMxRxyGws2rCpjLuh0LZ+wEdN+V+xQueGQZ5pgZ9/PD57+8fktez+dsjEvJKgNaZxbtwNuGkyu4l50bq4HE36"
    "wTYt9G9NVF3T1zXWfvarucY30qAMjU27MOP7yfFUjEVToraGBOGyaXt5zHGFNzYCXyeIoAkrThPOlCblIgh6Zo5NLjvGP51ImueN"
    "WwlHkSUipzFCPhKkRATPJmRH0+xqq+Q2NanrhTSfRjomjx9dNY4qNcOtRiuD+fzQwTVpQdakQBmTVNY49HsVQ0kYAsIRmfTaivfX"
    "oBFOP9eT59RW4flpEuxsUv1i97ByV5xxv3puJV7yLo2I++BoTvdsn70+Hc0dT/3dpe9Dl4pEtPM6O0sJgsLbDJ09wLgirLNL3uW8"
    "H5p6GFXbAcnhMTRcOzRChFZftqG/PYbRXuzUl10CXmim93ShkzaC93ju3o7kWKOrGun5kQRghacUfi53Fa7S5rhKu02BXQwR1eA5"
    "TbqbCiElmjRRt9oatN/k3rjCTzaEQSe8h/xRXKlmvOW3qGVw8268nNvwVmmDW7h/BBoeVm0ieq5hFdjRYCU5qhCoDQGDB5PYuN9x"
    "2Fc3+X+1aSCF8oZQhQyp5LwbaX3UK55PB703O6VhcffTJrBcDIjWTRp/DGEPijr5Vk6e3r05u/Qv7sKb1AUc3AUE34UCC03wDoME"
    "jerOwMTVFY8659khnr9kaF12DtS0rbZ9Tb4JYLuTpL95l+4AvqOPpelJssagKE87pysLcOdu5t4WsdOvyC8KFPni472zL4eewadN"
    "0B1j961a6lJs2Tku0Sef9V1ja31oN+IhI+y82fzK7N9+e10aSQ5pfajk9N2DxF3puXHgEVg+bL53ZP16i57DvQztycD4/Yqru4TS"
    "MQdnHCL8Pt4vEmXowOMcOQK0o6QTkWmTuug2b/WYzg3EjTzZwenAvx18idgs1PlaLDRs3jP61oWdpisA0ntKSptJ7tWonK89iXe7"
    "2J9aEhLaAVyJrMjO7K4w9M7tqwjULqSTeDBlrrWAvm3xnLo03OtS2tgkPtqFMqTnaF65hKALZQ2mmpZasBC9iCRijuyxqCO4W2Nq"
    "Qhzraormw+6LmaQt5nWy9q/rqU5An06eI6Fp8Vk7d1Rimw9tQnlEQf9tme3g5NI+nV06lmDPPNsrmxN9N/1+WqsunuOK3nU753xv"
    "J0WX4Ow7Sxm6EHHibdrIlawrXKGz3UabIXc/PnRcobWxAzKf6ydIWVeRtMNBazgOJgsoQFbnku2Am3KCeboGGnrR3q9FZw7u+9Ho"
    "J1gC6ZrSJTjWpdFo56YvXV3OriGMrmZxr5FQ8ekSfi73atY+Kl1K6LqAZuKf8dEFvrY1vtgNTAofMfroYNii0gvbl10CNNgWfIJk"
    "Dih06avdM4Meu9Cbd+Wegn64Yl5PfEFTARQ6cCaFIPExJbukoNwlcbwVhqKbRrUpEBOknu5cA4esHJKNyCO5UkiHcVgkiKZg07Sv"
    "2mhNIHioJ7D/1Zbu0m7EQikEBHJWUyt3SdYbrE4UzeK8RGXPqgnXrT3n+SBie2/CUYvBU9yp/XP/mHFSTYJtjZDPTVxx/Ggcar4J"
    "oy8eUyRQSvZwGM3lKL3Yr60HWYPTo0R492M37ChMzeysTWrDfF+M+SV6DPJzmpxv0msp2GGSRQ3D5ryTbHq+VXeXWFJAvgVB+3US"
    "DmA2JsfaCSiDexJnkjNnFdlH8b3ZzsQcFWoGOVxNKHEDvxgBP2SaJcXURat0zoSM4DkJhsxvJYbmBibvk8Ugzx6AfaXTSWewedfq"
    "DGl2A7N0jtMh9krivld92vvCBiRrUhoBdGZP6Mr16G3g2XJms0Op6IPjq7696q/DtMuLTErTj06jK9M6LNTEZixbj4UDqTYWDnlk"
    "cUyzpIS6lnD7s08zFH0UbYI+Pdk708HDuqkyRrIJCkNWMUU/sE1n5gu/0CgWxf5DZdwF7NjOoSfafTCIeSoaJ6IQWLj/xJeazfOL"
    "entQEaY3WSvXMfT7w85Pe74zeK77h5QNwr2nWdZk4SIDV6N0o+xfp+EuBMZdauq6JvY8AtMoLMJ5EjuMEvmnPXpSP8/QLqQgQeim"
    "MaAJy8n2tg1ymhFuFmZ7b5J91BioFXhBjbEAeNuprDT72i8zs88gzscKQdrydi3cQ+CJkhyeDOJIbaC2Jnqp/MBD0Q5icdOgTQm0"
    "n+xujt2W/1LYokpIQptrhxsgsegGztpKZoT8Gid2IYuOVH0Rq809LDqfKOzbBDAHr+CoKIu8BLZ5pXykSVFTu5rtfJGkTZvuweSo"
    "Nmft6l5y+S3UO6UxUx1wX8vmo1/osAsKU/q2ySv1NUYFqtyk1rxJP8QIIMcwDxif+Uu40DRW7VYIW6hFfKYhvpF4X0NQ4U16kwe4"
    "QUHGwvgN0IZk80jz6ybo1SaNNh0bdwKxBnO3h9iTE07btF21+w+znYAmsTYZBSXB/NvnHIFEJAWwCYZLmm9DRudcab6nYRMO3jb/"
    "eUCLXya7NiO7Lom2EZ005cjZ7NOOxEXEQ/jmhhA7D24XNxKx791Jtyizrl14kJA9z10kUiVjGWQayQ4YJco00/YY2qRh3MaO/dPi"
    "RLAYVMFrmySLK6nVoWc0xkHTKs1BhizhYGfYh9MpvYouS3vYWXfxLgztND8kvYPsbjW98UP/DwHnIZN8TwrJSJCJ7RJcxyuKjIOM"
    "BLuJPKTRJX/NsSO7AE5Dc0OfShT7Ec76b7K66xpI+HYI6+mYwaqQlzKkFBJXTpU39Cgbwp+Kmz4FNc8lkkBhKRkC7Eb6fPK8ds26"
    "kyIcjre262SIDgkp4Ep7yoyepTx9ZsgzwTy6qMohMZcxBFehHyzdfsaQ8OCQUoQh5QDQXJQjHGK3aWZRqPk6Mz/Yha9k3Sl1hkZJ"
    "K1BT0ewAbTGjpSTIrjDiILqiYxYTcasv49FixweUF2bZrjx+JUAW2ZKyK/AtR+gFD7f98LXItU84AGQyJ+zgbfZdnmEzuBBfbVb4"
    "muOFTKx/nn+QaZUsjawzWMiP8r4uRkMXCP+FnBDgxkkkCXTH80Ay7rlIILhFwpQO8UOU+5PjEpvPkRfnXA8N5agRhCfZNrbHjJse"
    "ro/QImFXRrrzdrGDu6gIhys0giIoeoKTJ0Kq0aXfe79OOLjLjeMFLMwaOWNkWRCq0EhL4ON3Pl879zLrGrPsSngTJCw7D7FLqCp8"
    "NCPesQRiFXLwbkQ+qH1oyT96IYRIybwVOoYu1Ipd2CGQLDsUABgl9kPt/Hi75jeXdAEAHgecZwjZjjPDJ6SvIfCFZRSURJ/4eYh8"
    "KVz3CmiDiFkvZ6TD3f+5Vq3pTTqjVD3VEyxEmqprDjRIsVeJrfFWqxpoIb/MY5umFdfbQLJr06Vegjhe0wE1jpgQDvgKR0rDRwRA"
    "BgVyECz5VCN16WLapeMsAjJ0KlR4CcNOw99maLo/ACxaX7Lo7k5N/6QPe5GgXFUNif5dq6/19mrtAszFfE/BUOXT/o0jQoyHKiwk"
    "Gm4Hha/dkQGCeQJixPSGtT0ZlkoEi8iyzbNZvp8UQZaIbAm+fUr0nXM1WWKdF+o6zlNkCRIGyIApgIal0flgLWlRosj7Sp+C6kuT"
    "EBS2M2HoTCjFPxyHmSULPxuzHMwpEZTZGHw5nQZ4SvR0dt7B9jj0VP/wUc/BzVbmkrzLlJq3yRbOBG/aYR7ZlY/h7vdsTpeuJMFT"
    "u4lCT8urJFbij1mJ12YKZ8zSwq+l7bjsUrEHfAM2dild/z2PjSWhj+V05t9maEvhZnbp+tN+fioCf2D/RkftXnLvlnAHL4GvLdYM"
    "S/qVryvqsxTctKQ/whJipCVsyUswfLjnVAgYFmm1hTbTJoK3pJTrSQxcwsOr2QHddPT7cLIFlmibJeoQ97AESNJyiXbAy0CVUd9D"
    "HL8CJNwOl/Zblo74VX2criVVjUuSj0vQkUsonyB3JxHkkiQq7pEV5wx8uGvO2Ayew7/KbOPbrxrSAe2XxVvCj7q4OcZKHLc1pUB4"
    "linsrHNKgCEAS+7AeS1lDfuQN+TRlWAicKlQLFzaYYgq79ENFY/cGFo7BwHSUW+a6StKCndr0Vk0u1nMvY78nptTk6+SjRLIbJDD"
    "Yj6zGF4Y4BTVrpFELp/O3lfATXsbalsPzZvn4BlOR4arkM7B9eBcqlDow744Ix9FKiNKAEAYAiMOcZKNQR0KgewBKJEnjt0RfPwo"
    "V3H4i7dcDGE3C2KlWsrHROXo06WUPoY9G1tFl7+wunHjT1ZHDM2iBqt4CIBxnJYPfnjmkkIoLaVoYNebqWIK+MXYSM1eIKJScebv"
    "arxppCCoyNvVEVXPg+MCTWzoJmOOkBqsU6RX+x30/CZjHYoh7pIpkW/Mqt1qjCsvpDUayhu7RB8ZTa1Bc4T05jR/+Md637WD3FDU"
    "/BDX2q6wGh7aoGEIp+SoUd1ZNRfsm3Txhahp1DfD0tjyxJWTVmZoHm9IsW6QmNFoPHAi/fnWJ3lTzgpGzowO4ZofM0rZcF1oFxPI"
    "w/Hr6KKJlFM9koR6eg6BCSD9cdpJ+NmpJD0hA/qslwRpeCp1SDd4uyI5IMEqDGE+HkqCN5TneEjX2CGld0MpgXBJbuLTEhNDME9k"
    "jyTFxAI2OZg1dCOOaPUGyQUdcBC4PQvaX96EZVheYlIZUlk3NGqoAAYXFM4bcelvZyN3CNPykNgyXt9F4pLfyr5ylFAStp6hXHZD"
    "6KTwJKo419r1JXlQYRIckx3zIdVjQ7shDmmdPatws0+hfJhc1jph+sFl2m8Ay351YhVm5s+YQj6OuMTiK6wIZuZg8pSiJ/zsFOWp"
    "jjE+7FQ7MzO7wqzBgxZyOs/HXp9KcjoTH/TQE1TG7DrBDo/+mF3Y3KddivTmmdNfwj4wNsdDzKOGDH36G06w5n76JvkVqieY8Jhs"
    "u/+arUwh7cUVm5pt2/kmSLa3i8CkYIFEI0ofwcFN+zBltNmjKxyISaFCZoSIMmIEO0Z7cQ8pcgkT/MHrgk850XQY0pkkl3aFQxxW"
    "3CMKZMuhpaeIzNESrRlM0WZ9YVfsrWOP9IrsJuUQ/GiJPpZGB0E+HlhC+7IfMnoIThBXmBiDmzcOcd/DvblPXi+8XXc0oS80a+7L"
    "zOcCq2qp/hzS/hCMEjbNOY/f1wNDsb9Fq0PgdUM4Mh3dc54dKsAzOGWpEgEYHjr3R4TgICXjpyIbQgTYWULUMQFszjaJT+gYxsup"
    "K4SXcUi9+RCeyCFNGYbErYfW5wAKs+wwM1/2plny2RCQk75NMTVL7HfezxeFqa8bahfLx3ZQeAyDhiARhxhrJngImae7DI3tJYL9"
    "vMNi4YkeJ9i5ESC5WG2NgPjDXLv5pfIe2hVrSPPtwRmD4U2xTCfNj1dA1CtCDhy9qgfGb0PhxfFht5kqntFQmB2ZdUBh5ReT4cC1"
    "eawc/K9kfkt7VyWJTCQF+AWQMLL8e2QgE8tNixzSE4wQcP7UgKuFd2FVQFplhBTIcSrhHRm42ETZab8kSPKar1adykAzGYoFTOMJ"
    "hRkr8lXGybc9lJoU4NUzYwpfnP0G+9J8QhiHEkCZhA1TkvNt64avFyofiuSPEXAybSHlkRH1yKML7ppmW39y/eHJovuMPeMeQUij"
    "A4luisIjJJ9dLSHRmTrEHnBbcYvTIRlV/MxE4cPDOfqDmtVzQAGSNp69v8qHqRTxHDLimqjyHsA/XwkigiR1pcftE1NkF9epsH30"
    "YPYDqU0hx5OWff4LKnrNfZV7PL/jQ1Faf+LZQ7DcIrwtwoeTaauMDlAwekrwYaf6oylCVlympmEHwQhg08Ox+HFFDKW8DOQX9VcH"
    "tCA4SoRB38GWsjFrffOS9Y6STg24yqXEZceIrrLdYF4rBSoTakfr0/T7vmlLLUPAarUkoEx4omWra27z/NAceh/5viIoLKfDttbe"
    "rYAkkYFxwkPcxfNAsUazBfwUXm6ucxrMA4TqjbPwQFJDQ3JqoGxLtvgf965qQB3hIBvMbMdRzHqnyvYtosORQrdNAlOpPuUSlFiA"
    "bfBtEYaCkHUsv2Jy4D1x1KSApxndnh4MntLTKTDJCRTPMKo04ARdI+vlwjkU1KPQ4VDEwClBFUsX7kHZIyXIYTPrCN5f+Ungk/sw"
    "ymH/tdHXsp00nx0pLl4WGLWTbXbe71ytgpuQZf4WE5n6qWt9ty0vvkT6htIi4Sbys6IrQV6Iae32P4hsfLrNKJZ8i52chOnRrryU"
    "UM+gKQeMGIB8WAA8YEDu4sQNQAGauOKanCz635YxddNF+U1S2Qx10/dzjielJy0/AL8nrbdYrrtmQ/oWgr6lCe/9z1MZ8VQMDKGT"
    "Lf2pSXpAxaaItp3RD9gQPqSw0P6+8yU41LoCqmDQEJGuoXJeDW2VNwQbhVOU7EsBr+BBFBoWvM/InM3FiMxjWL0//exw8Ep9njLc"
    "6m6hXymHHN7l/yX6+6EwOJXjoRwMQxFFkIWPOxxVpGgjriG0Gl34kSGjBBh0/M74dk3rEr5BqQZV/0ypENJ2sTc/5ReDMDXhPbnJ"
    "UpdKLlxpQivJWAHpa9GlD6p/7Pz22/AK0UbFF4xIltYPeE4PK0XE7wNyFQnuX2PwroQ6wDw9FQX6T1Se2oWntguXbRfnBwUV5Ml6"
    "uc1m09AOgmSTNd+lZ0YypGHysrl4gpS+r1+K1keoy259jRuicFtufDJqmW3hSIc4GQ5Y/xLDhBETLukFPsw2VCtrvkZZl4rVaR++"
    "Pn0GhhKsu13YOGzB9l3jogYEjMjnhNtsJtXobx4qpnceR+NSWJxJSn43rI7xwOxHDii4zW3Pb9PSyOQTzM5Q7jfY0oTWEJTs8Haj"
    "/SNEgJ0I33i6/ptJSc9fK9fnUBdfWmBSzhwuFixHV4rkZ7J6w9IJADedQplDSebv4/SZQm8S95SHcUSGcJLn4Fd92EI+3A9+0DZa"
    "AV1KsYz13AmP4+DUDDxA+GAfvt3FMEM9r7zu0YzuX3NBnBfMRjS4F0iXtkpd+vlA15G32bkVJK4oVTIH+9w1FpQqF2txkqYr+Z92"
    "CUC0lRTQFtu43VGjO+LR4aSmH4IeYcYlaUD+rulM/mcOvHBJ02RILSoeTiXq+fbreRQhj5EBEjLZ5sOVaSvwBoqXxNqjzC87ntKc"
    "aXSujMBkXdelbITzE0Oi3gq+0Sq+wfwqCKg3xhmJz6qJfVTJ51+ex1sCtt1/INUhzduHtMdGonswooLU1owQVUOStnLTYJtYKiqR"
    "iYqTAvQ2Pt0moYj9w0gnTXHq5j8PZsxUUK5vT94g4+xN1DMlUMWPlpZQGMfkK+wFCVUoJm9zFliD/ksizVNLmzTaSPWgg6lhPA/b"
    "KCkacF5QnWLA7TCCGWdLLQSLUV3KkIrsIC0ygnToVDxZ8CGb0Q5FYJO61/h82xFAJHi/Jgn5SU0wTdI4AU4jJaGKTFGJwvhnW0oc"
    "C/uzc28ULWEjmZQJ+6awsuUE6ZTg9JIr802jlA+Z12WbctrNOYZfhMk9Kz9z8THVMlXljxJYuazhuLo1sldrEPsVi6ZItVoYyFxi"
    "PXYBr+iv7M1fP2hoCSoeTflw79BkI+rth7euEjXVOPOQKWLzsQgzlsdRV/3ElzBr5pvcwNZnRCqoE5tm1v7pBiMh4gAlru1pqAQl"
    "vNKG7aZPCbCL1pkAQs2ZqfsvBNwcuGYyMWu+ORmGcBFjRBzsrRJzuiyxGrlNgdDJISp4gRp0KFrS3kZHUfcwHWJe0tx3+xmqcR5S"
    "IRGkO6TDPdbuSasJkoDGNSXOOrHxV/9GAGZlv3A6QGQqMGcKpmkOUcsotKXE81Qupdn5eJ1eFmC+0tv8aHrn3xeRuq8KYPPEvojQ"
    "KajRLsyBs3MEfIqbMQXrgglY+9PWF0/u8vnnRp7S9XZyjnYq/9RsXM02G3uqeE4v5ob2d8jCtz2lLwuevGyFWl13ymRK8nc2jn7O"
    "zkWh09Pi0/mbzzpmt9/xDzQ1XRZGecVwiYC5lcuiJxjX7l7jj8DatgKrxCtflfXplO5WU7Tw1JgR9oIp00+TeNxEKxP+jM0eDOnI"
    "y2DUixeLUbl4EF/iisUpPaqwBKeX4cvR6Z4zl4gL5Btq3SXWZ3wj3JBdrtOXos85+CyfwoY41aufgpSY0kJ8inkNOSOEfBfdP0G5"
    "dvKrTKnumIrwCHah0n7M/U/6nkvX9NPnDgqYui45JR9wqZOqY16QxinAPPzDr+/s9UDzau1sSak/PZ2nwGinVOE4L0GnEuQzK48L"
    "ZIjMqaULUwjYp6QHcBPQEj9ZFmRVqIZFbWj8Z2ph0JQeUFOIRKewfeLQGWnm/LY4j99WSy3nTYHQsSqT/MRUdioM8rT+VXgEVo13"
    "nXBYXxCaEGft6lReTkV9U+oJphYdTKkem1IlNAVB78wZP+id/ZXH7HUB327meDft0sUharuSro87TfopBW1TUhtTSgGwm7sdNzM9"
    "aaC5ROEurlSbQitsVxgbhZtIIDcbcXPLyxS2MyX3C6IQWpD9z/0PbFkE9TFCFTK3VBnhnSZQv9bruId206ZQBy4QoUp0y3m+bVng"
    "LSjVpSz/4HLIQsBBW2ApPi661CnctSTQuDKr+IdQJFG8Y6Gu6W20+3xzUqYXjvxGS0r1HZAWG8XLEHi93s7rTzNt0JksE+WVnoMB"
    "95ybCmQZn+6OLiK1fRsg4CuI6iVzOBZPkSvsYIEGg6YyUZnRkgS583ScxCGJD7cl2JwlZMB25VxY7FI+trYowC3JzXU1MsK9AWUP"
    "adTN0cYpILup7I3zip5Ciy3W0NRSBoJxftYKlCG1JnBly5qBPYMt8WJ8n/9XzLct8ZKpySRwEIlUE4gTa8senPQqxs8aq4kKDfBD"
    "jOKDzk21tNQejz7EbyrhCb6t2MsfDszrpjNxjEefc76kpaIfCscJoHIcfupCVf+XO4rCd1PYsqcgofyezSaamoiUsfBzHFSELwfp"
    "XNGDKPgIieatIVV2U4Avcz8bi9yVyVmvxXVbk+lOpySkprQmd5O0c5RD1n/KUafB7ym1U1OquebVN2xq0iWwlkOTlmJifpMdJiu/"
    "3RCnFHW7+8OW6FCjOrKgz8znlLqcyPAVTgIcKJs3Ip2o2NBCu2Vqsq/1piHBxXTaxqAXM4XyisbFqMXaujC+CYxWxE0F+j57zrh6"
    "yO+bh0u40dav6+FtB/C5qPlUnHntfLYk8HF42gb7xptWipQsbQMxn5bEXaQiF5sM0bcPomVKzbbo1yVw1CmwSVdworoZF4JnJ1Z6"
    "faWV31wqJCabRsm73ZwNMJpEMw0a0Iq8c/ugby7b387foabW2O2GbjwDGsuck18WM7SReb9soWlDiM7+N36UMFMo2DwOVb70Pgjc"
    "ViY6FJOhswE2hVtpKsMZohyn+QCoPj+H2RMLyGc+3hx39UUd/sT/6u/cSh6bnxJ5EXIC1MzfSAZeGSG+mzWouA/y+bRPxFi9yAXs"
    "CenLLnD/QzcL+kPL8Fw3Gekn8GLwWIQEDOM9869YXImViodQ/2FShXtlOJKtnI4ziwrIEmfJwRLzkWQq8SS4sStk9Uwh2ZpS14Er"
    "jGERp7TIKVLYdyySRABV6l1E+8xaEK2tI780tfu+UvOXQUNANsIe5bHR8QL1oui2NEGb0tN7CpIw2LKCJIz2voDmsBCk50IxYANf"
    "WNxAgkKw0YuvtX5axEylyHKqlEYJqaopqinCyvpBO+k6pYUgWajACNWNa5g/UH/IQs6jC7GvJ3DPjDYzFDpAcRPS/qkqaVxqsVGR"
    "/YUJCcvM0E65QFMKZTn37hVXEyUag+/RchBGWyQlmkqsVUJOCIq8e83IUdGViHMH2HvCcCUJHKOIY5r8QXZufkSYFSXbuJ8Yxv2l"
    "39ZeQxwwBzcLcpILRZMWXwpR6MghwvZClMpsdvnEoOCA6enE7fNWEonLf6Qg6O56ZHtjz/yQ6XQJI4a/FcikhDH7Dot+CNjJxqP/"
    "igszi3wwEwRubWERzsrkcsTgO7gvw5adsZROG/ECE1977IOqjx7EJRYSB43qd+Y/XQs67LzZLuPPPdr1hOkQpxaOounOl4UGMFca"
    "9Ho6IS6t8yjKWUgo3aqNvCs70nGXeKK/F9xJRJtZgw42RTpfEK1skxqmLvUimrv0DpncxXJKt4QUtNc4SBa7tI/GmNtsX5r56Cu0"
    "x4eI8tMygOHVlZV/lwxzl5bfEf9tbwdh97+06GTCfua6V5o28IYiBPW2rxBAjzPtsqgxGae2ptROCBHLP4y13Pa3Xy6labtURHSx"
    "ZmMGWzPJ2rder0gQyUU9909comsVbtyckyfJ0XPfMtguEK9fhwAlRUZ/tV9oP6RuTaBrLF+Ry9rJNSvjq9Atiwg0IRvG2/Y3XhPL"
    "vH0v4GD5xxRLJnAX0EqX9vBdKrwD5SKYPiyd9nruIinKtKy9HbZ0Vg76QW/7SX9xl2j2eca40GvRTJT9ltqgseeJ3dAmoghGmof6"
    "aR/TRtDWlDtbgoSAGoJKPqRtLX6TVEvXMFj32lP70PHkpnpi975tzlPgbcne+5R7+SD5Q7SktykvYVv/hS7ozbPJmHJunbm4Yhyd"
    "Y7lzK5futasj2of5EN/z0R34YGrhAwMy9y8FO8dWrg7h/Yv/wCUyY7uYsegDTwpCGyFpOXB0D4X7fSXPzsM5aM3OxlQWYy6rQRJc"
    "SmIpZUGp9BxZJNrEJjBA2ErRvuThPaJ9qKlRDRoWEUztp8m7UJn/Sy+p8MwSbcXuCy5RrWykrjjJ0RVY26ULCJ7URIOesZuw7XzW"
    "tkty+ubg9Ndp5co3LXzBJSDgPgMQcJnX739aKAzOxXbPh3yLXPsIjLouJdhcKnzRLnmDM6E/p9O5BxXdQWcHqXR72MfJbl9RwR/X"
    "6UlmGLNH4i6Mou5uUNdFpUyo0olddvuQcG6XzFr3Jshdqna8tn1ffBlP+XmWskCZghGUbm8dV5I+aqKFhlguXTq7dwf2g6P6RosH"
    "XfWkQi7ohietlryFHr+LUGlBE9GJpunHu4SKKCC7t5m2Wf6QiXXJiKLJH/dbEAw1hmg7zub97faBma4mgjn/ruRlD26/ijyU9OuQ"
    "eBlDzgKakClnmVauTu1PL9TZXVB5cROWoBWi3d1z2VeHmeumIsW0so6sv4M63RlQJAScDXwszUDWKJ4UcMROocvZUsgooSKn+W3M"
    "l6wc5IySyAKKRIs2O+Q+ReqTm11HF4akL4YExBleUx2DWCnggej+uZFmDoo0UFK1a0s3K0AYN+csyxVwDmjFmRklTt1xskWqlmYN"
    "kj8cl+cmNZhxQlyUYDo1acMZowzFcZcsPBXNjdNVWfJeXLAGmWg8/wF9OwO+wqTW4JyEpGBs1HZpjR8qWLNsYqxM4VyYmZkz8DIC"
    "7hbF4JQgb7I1sRx+Xw4I66dw4bOMZAH9qteHxBD1/wtS0MLwM4UsAetE2fUoO6wCyJCZEvyqafZRHySSUwQWFJQHIJpiZ9638kJq"
    "pqogALKcL3G9K8WGwmnjIjBUpZ5QEy+aYqx8umFO51xp9n4p5kPPNEeoH/FAYJCkloPLVnpQVzTsvMrlZaN4y9UE7z4iIJci5ygV"
    "PSNslmRJF0dp8DtOAE82G3CFsKBS2j/vsl0gwqiUTHiapvJK4BJN61B9D+cn5/XjxAR0pr4cJ+83JgH+y9bVZAeeNRl+yjj+LaCA"
    "FczEVuSsQPoEP54YIrWQuz8Apr0fMK4pdgmAqqfKXdpFQiBrDlWvR/VABMBnKO4OwHBZMJ+sxzaHwQBB1VaFhcG10l1SqP4UuYop"
    "0z6ZtIJLTgiAz+lBQsED/PdiRLjOR4CqFnB3hKqvDMYP0IrUGlTwKkAZEu7Q5uMkZf4VXLCuwOf8DsBngqWv7ObiXzRnXdwu0/ZT"
    "/TBIYcrJWF5yKnrjy07weeKgwBXpR6sYRQr7LTm3gy6xWfqAJo6IQE6pzevT6FbhlcH8kjketHB9HkcOsjfubPwCqSwgwwNvfF7M"
    "YqFbKWmlShUUuD5IUfFBQ9OztHhJXBQzcdaM/MsCSV9UUS1Vp52SIgFw/18qQBJL46my7weddS3V/HH6+iRy/ugqCoW7xm88jKCu"
    "KtBEW0o/sip9Uc3ajVmR/0k2QaCayRMPiwqCIpRtWuKDH42fnbS5dD7MySU9shZTwd3NoVNwMGtlg5YklFLrjytiSmsxt0ArSFR/"
    "hmNooX2oDp9Czn1SJE6hC58SQkMt9WJeAnLq0SHhIIpEhSgVZl1xty8yGjTk/dsyIeQgCOqdKfYgTO12D5MQKFFB1yJeodIPnIAG"
    "5J8J1V1s/wzxgWa9ldSTC1bZW5feM0Ghr7D9z/7WP0sz9z6zSWipn0s8U9FyS9FGlx6aU+KhzgRBeHktRB+CT0co++x06aW8s3Ft"
    "uhR+2B5pRwBgqt3NdF+4QB47fK6XLfvpeS8VHes/LQES7if8KtmmL+2hFJraAMQ/9hTVIQGDEXBq8J4cYjCPgHMg+nguidaCdBZU"
    "pNaPTqhTmlAGZfR3rZ42vpzCv/tx70pBmmw8ZOYYjXqQV20zlagJHGMKG9XL2MGlFvWfJ4A0JQa0JeRRP8UKdzCRUcb8HA+UcLSq"
    "xJBuwWMAC6+A7SzfIDNVhPYdwS47EHJp3wClSTFs6PG0HXwit0lg2EzkEkUFK9OhFJFwSViGeHgJXoQAfQ0UbolkdQlS3R+40Y7n"
    "mHopQ2DlUNieBMB+mj6D0TzeIGPh6C1j2rPsvPxPybZZ7GD/lXxwUD3xyZulImvsoP8tVY15+9vfRnuKUz4z3u4ekaeQpSBXwSvA"
    "TS2mVCpPZWYN2lgiwC8Qe7aospSJaGxP+NgQpJcAKIcto18JfUEONMY01bCOOP2yQ8vE41cYVLSaVzP9LlcchBeqGWAgDpxfKMQc"
    "YK9yWAguMqgQFDatJRxHSxghlzCZLzVWV2ckqD2avb0uatBuIrDMGmKvexbc3nkiT5YUci4/WJYWb67JvEBLuDHXFI9e6CrtAyit"
    "YeMXzgZmJVrQw3bWzz5+HkgWR1hrN6uEcLjursh4CjM1KB3cqgRhWEIHt4BotA8rycyWazhVQxQVpvVbP36XoLIxuuSgw3yQ/1U5"
    "KowhkRQqG/uqfC6tqnNP/VaWnIFLW9nYpTY+R+ySasYlbXWWQiyX9MpbkrhcsrfxEScPEmaMwyRCq7cEvn4tEE1rIA0ct6rC0qgy"
    "3fhYXU3ipCEvSQLJ02f7J9rsTT+1RhPLoT6BxeJJImabGLMwRXO3Nd6eDEvBc0v0OHbD4K2oBbgagSLnGFe21HUnCczZmf2F5muY"
    "JSa1gHu31nyPNmGl8ChP6WfYXqNkkoyYEr/syhQkgRLC5UZ135RFR4RsM5dQwMhhIy7f2kdQoNur74Ysd5LnR0rCU8eW/VbL1etx"
    "fuGBKEmiDBdb6CuCoBbzOSnNiXQECkkngjwBW+0RM4VeYcjtVFiKgOmcPUqIfYTPSYOMkukL3r89GfcJnAaztoNltX+xa/VXk76V"
    "z20LoVfIElVqth2X0y88yUa7T7fNYy/j8zu9Scm6eFIkdzM1Se5z0jmNyRxrFz5yLjVWF4dJY0K0gm7Qa72DXRKExr6aLAocf1gS"
    "OV5SxisYrinYdLyeK6yRLt/zQC/wVNWASbLbVD8HwWU8P/yRox60MFWARtwQFySYtBmETNdZTZkL1RTvkT+bLcZZHN1tnTGVw7JE"
    "K9MjEgUJJHThmkEbL1vZ9PYFRPhPQlKMUJJ22FM8iCistyRCFtDKKBsN79Yhx24PGAo1Pph0hgYaonza1AQEnwFpodCdArhsZ9Ec"
    "7fmQiP6x2iM+EZZoEskJ79yeGKKAgOV+G+d5FP88ypS1E1WF38RDF8e5B5HuINIuqruJHf3G66jLFm6lOGYTX1mHgfIoBjaK2aO8"
    "E2H0bSixQXTJtvU38uk7+3B5pnBWx4PSiCWpkZCpll0eZ87tNCmKOGJ7IdQI8rmaWxhBdI6bDWlTQe/skb8ZliFta4ZQ+gxnfdpm"
    "jM8nxtWkk5RwOF+/OsKVYVcHaZs1hZw+6FnCaRT8ihkaVjgjgv5d0gyCSuyn9h2WwMuYQc+EYPqnNqOQBi1METF49b3TzckAP4SN"
    "QGiR0Qnk3NpDUl3oK34wMYatcqgbm22Gp/L4bQ+vfTG29AWRni5D27oN7cGg9SfoscM9LZLIkDB4TJEPxfTbpTLtWS2vGxyPyT+7"
    "0wSdcMr+MHfd7YWkOfxJ2Y3O0Zsp9iuYvH4dMZqIXWOPb/SgO8DcFJBuQq8RXQEBq5lc7XMPEVU0XQtJaaNt+P0v3PVGi7+DrvES"
    "CEWPG/noLsI+tLH9lD3CXQ0kcxy0dJEqlyEII5ArdO6GpoQqWvik9Umm621my5M56F1q1qXvldfPnGV79hUoJvu0m5zEntKVkQ+V"
    "OVTpvrBFAfZ4QOfgzJhHl7dxwZWCrnVZlzvrlhcouHeps8Xdbz0O2lKctnbcPpraLwZtG686x8HFk0PyjEPycd5AvBO9DzdN0p6E"
    "kmgZgpcbwloLCSP+BQnJhEwpNJ4uQSRQ1AgxytYmsuyfD2FgE1SZP1pIfKhdDAJmvaxxgYOfdtFHDXPUkjAUpX5S0o+Ls2xoRS8u"
    "LW5AzRokiUUjTMHOOMQLZQrTxjZmXQ/xzdYW2UIdxH2NIrqjuQ4MKCahtHt2/60HpXa5z4LPDpuecp0U4vUmX/siq3l7rhJTVdAH"
    "Rw5wCX7j2TQhSoslCG7YBrS3tC3jEPL0wDZobnF+JW6wxbmihmCsg9Y/b1sw6W605HSl7dPYO8K5KS2R9jR571eBbmyIA8xY5/7A"
    "zUcO1JISDU2VycpkSFxjL+0ruxDmKzmU6oWgJfWS43KxfdSVlc0LRRs35gy6bnJZ+4o6UJ8Qv6AsU+t22Rb0Ms1GVbtC12TOE/bt"
    "j0u6q8eOgnWu9tX+tgEviJKJ9azl8ftMbIE9oJWyXpOiSBlxYxhi1xwWHsOFqzUoxV9CDhAQEgS8A0RTIQudpSQ2S8ihM8a0K/ed"
    "oEV6Yi8ZTBan7nWyjXOXKT4ZH/ZpU9FzwPRyf8nidX3W8v7df0qw0MWc0y7rQVN52+RIEJ3HHnWkhR1njmwZ6+k3Jk2cg3MnS2fM"
    "rGZ7k1O3i+EVdL3k3nnBLfZSU6Sl/iIW3IeR9+r/+PuP/+9//6//9//6n//x3/677eRhl/9ysb3b5p8N2i784bTp7W+slcf4syko"
    "ddk/VjO9cW+ppbS/mcDa92dnacv1r+1sh+rftPHYT0x3m1HxN5cZvBMPGDb9f6PbtE27iiZvfx1tkuYfBm5/mMDbY03gqmnav9ZL"
    "x8Xe87S5qXsV/FuzI/7P3Ni+vFZ65fVXsGT1r9iXYBZBP2x/M/GYyf7NtK09JZkcTjxll4Uo06r1D1H7vsDxk209TJb8j40mvn8m"
    "ARM/mM3cFvsbBgVhrNVuMVe69r+8Tbrt7R19tf6c5dgu9o0BFnyn/c5Mwrb+zAaxJcYzMQibuGpDsk9eNlumV7ZNd+koZv7D3GMm"
    "7bNsJlq2KQNf4sJTKuTQ3r6Axfuru9rk/8FKW5iXYnOPQaRsC450d7PvQx33HxZyLkigSemfbYjZbHrM/FrVJgSQzT/f1/aDDpWD"
    "HWZPwDrajrcvSmauYWJA4FX+llmmrf/taWPaf3PA7P5D+5mRuq3r2MMW3Q53W2X7CpPDP9sr9pY/WAE2l3by4/fNQ8t/vdqCLAzA"
    "phbLNG2ofaMr09+yjW2f0Uw6sBWzia99osmq7Sc7aGzZbPzFrPU/tKBsnhEb0BAZNusfKG3H/EOTSZs28MqZdHdvlfMHZbGzCXkv"
    "NtzuCQmTvz1cKG2c9gZ7Xy4QINulWGX/m+ktG4uNoWEl8REmAXDjTdQKDBb8W8Y4zcZINt3oXW+TBxBCdfG1BTXpbTaIYsdygnS0"
    "bJ8CE9gGYYJie8reh0i8fV/HotmgbfawaAPylwrWHGJou9ue0rc9xTamSyMYuP9MREzT+DMz1nxAfPFvvWOf2Dvs57ZEdssG1aot"
    "h23CiodhjU0mIUDF1gPfYMO2cdZiC28fPfPExjJ32QZhpykeZi7t9s2Qs81W/jMT20QBC7lNKrp9mT3VPt5G+QcG0pYh47b29uIO"
    "UbH5KPaOBmIYXLT9Zneaj25DtAU3CbDh2560kcJ2sTsHGqzZzIDPwoY4po3UNsaAXrDdhH3j0QyEwhe2pG35BS2xIKjV1AMWcpoS"
    "8IuQAxPxcp2cy+XApGJCmZv+hSbopmtsUe0ksG9A89K/6pF6TPM0ScO2g0za0Btm2xS9rfWG+Woz2u65r6YJqu1ze6YdFz3jhDVH"
    "a/lehDQBaQAtMW28tr9NX0M94CT7g6KHNCWbNTxz4EjKYAerplnt0xO2kEmLPdMk2/6wHQDVONGR7g99aCc2ffIVNA0y8FrTAB4i"
    "7NgDNrcmfrC6TeA6agVw0cSuYR0afjAWdJsp931dHPbtAMnaas5RcQTYtEPcTRFjP5pMmDDY6+3ox9FiIm7Hmf0dkUXbhabEsU7e"
    "Jqn+2aFq9p0pDXMcTYVUHPx/toUXph2qxLYm8pHlD3Ee+8YB8bZNbH7bgKx1bBV7EgQCq1bTny0DWPGnPbdX18VuKgDMZzsThGJm"
    "NBYo6OG7BilI6OI8sR6m8BZExB5harclXASFij3MhNf2iROO2O/Qhx7LYlKIv9k/2SxjWW17mj2Q8Ye9FutoU7+xVniRHx3YwTZb"
    "A7dsSLtJNhYXWtj+MMVkYmD61KbKHl0SdAQC3LbXu+nyguw1dBJ0S/aTp2Cz2saxP+xTCzRGbthkHgOGArDdZnIKJW1PsaWz9QdV"
    "P/4tmfhgLG5kmPC42MFP7b6MGQfsntjU9t6Jo8N1kv332oDZVAiE0GQTStqMEWhEjMw0kyksm/llk2B3uso2DWoGrkmKyc/qkFek"
    "k3GsQAubbOMQ+wNEAifoaBuS24ZtXxuk6S6oMFNgw9S+6UiTbDNR+mVGLDPBYVv5uVyRbcPpYaaFiQyI9RrkEITLdjKhiZ2NxY5U"
    "P4sGtAe8CexYOzXtj40AHlYaG96OiFw8HAWda28wdWf/ZufyxnzavTjX84ZeddPI9oodYjafNpU25SbUDRdXdkExQwvmi+l9TJZt"
    "bRy64OM0zWKL4q55wYFoW7X4irn07OpWk+kliDD0qE3cMHsXAm2+2sSKYWbsB8M+LNu0mIqG+QIph+Fg8gKjqULrmMKAEGWzjGxL"
    "J1h7EBfXOg3yYjLXoFkSvsg0lz3ABg88FL4hw9AxzwjSY98HhQY3HrfAHsVpB7MnIxzfX6PLzIcJUbQXQlvZcYFHo7QeB01x22tj"
    "AVBXBYE2a2nhCLVzODWsthkpthdMk8BHmKglN4mwV5nA2qaBxQEdhNlLEAVb++QGnm3q6rlJKGRT3WM4QXUqTswB5TEKDBBYtxny"
    "bkJnZqkdAphn086m8Oxhyw6ZPyD8bHvaR0LL2DlnB+CqUMo4LbHfzcB1QKhdMOlx8S12UuPbAYyAEYENj7nGHsN0+ho1fI6HQ7Cr"
    "TI+DbrG7PdRgSMJmazA/YXa4Cbds75n4NJcpIA78zDML8s8TE8slGmadHZaYB+AjJ+yUjccgZoVTFUQ8tgI2jTA17YugWewjcSJ1"
    "nIC2uBX6EHLQXK+5oNkjYe2YfsRy2kEN07bAvci272G+wgzFTINI1/5mU44ZcZPAjJ7qRredzTC5TDXbIHAGuUJLsLxsSO3aT5gY"
    "e9jyk9osm79pt0NlJjiM+EAbKaTY9ESC+GMr2hQPO+hMYvpy4egm/rYpYL1Dh6DY1ywA+8uGJ1Lx6uYIzj8cSK4C0PXCZtHEv8Pu"
    "GdAkJmKwEt2at0ECPHGZ/dCJtgvwVbYb8YMNLQEhxK5FXsuVaMcBawK23FZIOA/MxPZnooE8Zt8tfBSTVFiJy++sWC5TwHZ0Qtn7"
    "wWMeNqbdDjM4K73N7seQq4diB7z9AY0AaXXlZGdlXq4sJlwJ21G1uFFra9jRQX1j0e0rfJ/6+T3h2pqliIyiaYkMWUsdkoe/wZ60"
    "vY5vsF2Ar4U/7NNjK4Mh2ZdBIZh5afvKRLX76TeHnxwJi9Nd6xY3+exrR3fvzW1bOxKwHCj3y1AkBXvKmaNso9lKZVg4DU6OOa8w"
    "zPulhxbMSdvVw9+eppuo9rXmgpqTssEJDwGwvWeiBOPaPAkTIDu5GmCgMPrgJiAes2Gxpg4z2uYAs2Znoa28ueJYF+xCeHqwe7BV"
    "ENOwvzkkzJaj4mPsF8WN0+EqttjNkC04Z9gaZboBgo2zL4vVdg+2n4lhczsfVj+qtUzhYmExLNsSdhscQls9+G44DmA+2pHW3NqF"
    "XGaMFf5DMuG3J3VsLGwSTAuY5LKf8ZATKDn7w3YBvNkBCJv9rcOdyxiXK+DuGmPAJDPT3NQYwjn1OoxgTJqGK9jBZvMknIEVBkOG"
    "DTIRUDC7F5JoGusPrcvhU5gkYOzYobakiPbgZ9eZAlsER9my6R6IBiQ/i7DBl8sxhK25m+PBAXMlod/ScP/NDBT7dJt6qEf7vNXd"
    "rYcP2lG70ODCYins9DeZ/0OZNOxJ0+fQNNCEBWKGKBFMGQgWxBh+tjli+/LcBo6L5gdAxQljf4Dr789dEPg8rcPQMJ2bPRK44HzY"
    "8uEAMLPdfV9TvQNnVoGjAIsdloJ9KCxdGBz4W4G2TLBvoTSyG5GuenJ3BzVPm1V4buNSNmb9Q8uiTzwEd+D8twMNhy20BWQN9gDM"
    "AFiy9sCNIxvnKMQmwwMqiIlAwNykxzpnPwZg1NmWdkHBqtjPbZbxWpPbsa4NjlsmNHdGIB/mkRlCUNXIOUFJQQ3aqGHD2Pug6s0C"
    "XvgbVILfCV8JJoJrtQz/xExFV8JoZANVULB7THbgn5j3YDo443bXQxt/ZJO55qYIDm+z5kxjmVhnRD02DgQoX/8SU0aIWaAwvbi8"
    "NM/TwDUzR6e6sbTcgDcr0vSM/dU+rV5/LlhdcC1Nvyx7hEmeSawdVh7cshkyyUFMxtQwXDA8wObS1DXMUFNH0AxwgOzfBuJx2G0N"
    "0mq3bngciF+beJg5iDiLeQH28D804oITDAs0/SFGZStjppudMbjT/BHTQaaDHT3VILj2GRnqFcA92IUbNpDtTz9Eza7CottCTbi2"
    "DdoZXIsJbn3FR8CoafAcE6QSRC/QuaamEc0wdQvJ6/DE7SjAtiveMNouooMZYhvbF7a7dFW3m7CC2K6mAhHr3N1HBkcPgrvhBANl"
    "BP3b4cdCxzSsCUYLmwF06JdPU2GUjX39ILtU4qNhinevzrLNDAVqvm3zQZXr67EUZoL7KWbHDiwR+F3YdzZrnoRa8AtNFP3Ih1MF"
    "U8m28x9cKZi8vpKXGQ5Xq5mta7NvMwVL3yxgxBdMPl2lgMHD7MqKj/QjeTiYz67afO+K77exmmAgRG5DtIFORFPa9YOB2kI7MtzP"
    "QAc3mAd2KF42IUTALmaoBtuT+Qoe+BEFrxXiDgWDaIh/fYXNUFFTD6O+ehDTVANcUHhCUCLVzVU4DziUZvGAxMIJa9oDAQL7+uuE"
    "a9jpGaxSkITlKncMnyDvieaOiVksttewrjYErM9ttMFDtkEXtNiF+GdXMx66gpIb8B1t18OmSdhu6BwMm8/OJWzmjonLBfEGD0eY"
    "7jAtZD82vYPHDzPDXCaSO+m2PNOXbeJXzfdxskk3JwLHNjYH4o3w5uF8mLWQ3EtGAMKOsuHRuY4YB8yDdU06xrj6bd1vPymW60BY"
    "yThJEaG1UdgpYJY9nFMPkefqIQ80QzY1hjCIKZOMwCfcHFi4vSEbg8As/IIGQlzbjtMcI3uKG5OY6GVHqsm4O3sDXW88+IGIGJgX"
    "62V1e1S7N7eH8No6HK7jbCA46/Ftbtt1N+jh/RbE/hqmpLsOnntddge23Paonq0ntjECdrW6bbF8i2FT2b+4mna+L4++u562vQ0L"
    "oLnOtHWFWe92LCLLULr4SjzRI/HZw7jgIIB9jy83hd/c2DclU2xKbXJt7WzeTAXCFN1pZJzjsDCGKU8PYSLfkJHFwjs3cgm2myFh"
    "wxwMHEHDHQmTf5heNss4GkytQGYQ/sCZhRQpAm0LDn53X9426roG2y6zpiFqYZYV/Ccbn4dYzSa4fo7tC7OiQzaLb0pkkOxcMPno"
    "PmasL5bQRHAulJaZvToxYeAnTO5nZgRTu/vIFXgHj7tA+ZoqsfPJvq8gVtnRoi8jpgqXqXrh4t+Aow/fzKxK5/GCw2JSiMXzfknu"
    "IEK9gygA2tpMOoiqzSlEp5lKGx4c7+72Iz6EWIyNGhHOisCL7boB9xZ+RFlu+ldwzmJizFR1ZWmKzUOWC+cw8kdu4eE8MMnubgvA"
    "gMV56zYEVDAMRERFMrKMSLmYHd/dL5suquZowmpo0GSgh4DFaw4WHmajdr0GFx5GByym5CF9UxuIorrDgnCRHZFuWHQcCgWoNQSW"
    "oP9RKwIth2ABdBFEC+6Sx+RhhGMXuCuVYYHC/u3IT5nWrx4jcb8TsV4M1xwe/A45B7fFETq0Ew67oUH0IcYw/XG0eTBumdKDIYyu"
    "ywUhUVtxO/sRUzLBR6LXTl/zojxoNSHaduh2D2u6XWwHJBRxhUeAbFnB++0QgNKwH2B17WBGrhJmsT3azCG4h2a14XuLp/7gM/op"
    "YrJhd5oxjgPD/J3s9uJwRwfWmZ+2fkDhB3BmbL81j0ReUZQGfQPTypwjqP3uBi/sXFxEZA8ROVsyzNyc+K19CNwwWy7YN8PFxWwQ"
    "WHZov9iu6LPPOPYDTFU3EWy68DdIDxb6Crp7Hhh+kqs7m2GcVTVfSuCK0kJaFwyUBkvIzgH3N7HVbaLNTMRWKYj8IpI3kE/tOJHM"
    "DoN3DWocExebS4RZC3KBiJd4Tg5ZC5uifa2h7aiCBBLovWEQ2Y2+sz2FAzu0wtvaWDVY2LDDmlvPMAVgO5mAVajimmFw/XlHSt9D"
    "dlBC8zQs+iXOSFGZIVCxJMmWEPNqAlkQ2DeTEalB82rgEC+ENv7s8GxIHUAY15/3AbOLcMZMQGwLwKnaHl4y43G5jbhhBAxAIU2T"
    "QQPC4QLpNL4XpgvmzraHbV+4AmbcZDhTpiThaNnHI9KPjpqIMi2cmsnnbWL7gIbG0z/VAxmmr+AOmPcBM/OOSY7LaTLxx3E+sAux"
    "CZJZYnDK/FhMboDY6QyVM7CpYMhedjA643q6FXEuM97rlTJGlg2Gt41uQqZwLHrM3BZnQEIQloW1iuY1CAy4PdiQ5UAUK8Fote+G"
    "rweBvixZ6IAFo9FThc0jLr5bzTKDZwxD30OwrhQBHEoQb4QasUyQXfuE6slwDAJRhg6J7J4KHZ5izFBy0J+215Hp7EimY4N397Ad"
    "keiJeiwHCBTcJvEpBSjAjwvEf2ybIC9nu9sPgeopaOQhAUSwybhy6/AG0DsU8cSK0jNPBGDL2hbFzG4YsnAfPFXu8AdP8sGMAFYJ"
    "hoMpKWQFbXs2T6rjD4iIq5fpifoFHwbpOaxBao5zgHTgRDGp8XhrdVt1eZ6/gYUfm8EP8+rDtR9APu3j3D5AusUtZaRp4Ri4AXK5"
    "HaYL4CibmzI8iN6z/zHwBzYUfE5zpnFAVE8qmSFUXToQCDA5hYzBBjDJnxXvtv0NewheNmRxumuJRDO+ZyPKaudX9UPNtqrHUwq0"
    "tG1mhFWG5zAKDlYoTtjpbn/BqTD17tFC0z6zezS6QYkkZN+qc7/8OaoA2ZkJDEbGVkPsyZScBxnAqonRwSm0ldxAtlT3XaDpcD7C"
    "P9kIEAA11u9sTEX+c13JNPxhwgx5sB0K+8gMDUQH7YR2IQGO7v/v6dyRZMmRLLuXpp3AVwHMXopsrqRHpESGzL2PnqMWTVVlvnwR"
    "7maAQvX+cIUnaEclyblpCHaZvkHKe0T5uYY7NMdoVgcBK4wIeXxylmT5WSxTjxUOQhqAfST/cq+FKKEA8xStzvOK3uINAfhs4jmA"
    "AK+va1sY4E2hqIBnyoNvdcuFp3uuJk73/Jf0iLcI166kZtDKM26vD96oObTx3ngJ/PXD9P+jkAjqb6pNLp0nFgGhzTcbRf6x3fIr"
    "D0C1LN+5Kp9MEiDOkjp2CeWi54FMHIiqY5aIsShHkQ7QA11cEGwBYhSGpQv+QOmAqGaDwaiShVJGnnrIjAGIn7/c1ZL9KmqJX9Y2"
    "mnO43izTSGAAPnJPDptROs2FPgFkHSgyj4Xcn3QKoaYja8dh7V0oBfZBrvIsqc8mPcsCT5vRGfQ+d86mZqGM+IEX5srLg6PLQsAn"
    "gSHTrmWpgixGeAGk3zrtS+7WyVe9R8ouF7XTUdtqIHJj2dQudUTElgC4qF2AdIN3mFL8fhgUCcVsLTcbOAbVBhJUdAMx1GkwGyLf"
    "lJmprgLJt31hL9DsOHlM9EC5gP7KDBht9qHN+VSOiHmHtYKAi2NDQUMe+tPO06addAfotWntYUPKO0kDHqGtPBEEVPNFcGo13oiH"
    "j0WoMQgwBA6+WFZsN5hfcwsM0dvtoczKaIx8zF1xBSqmXGIy+X3HhzACIDAb5Z9mqQRHDCL3rsSdoFfhYvxY5uRqq+45qEEAo7O/"
    "oHPh7Fx5+uW4f+gomBLQD+XAxQ5rDvBsc9ZB2BoOggQnrSGQKL8hT8ssEvQzWaTOWdVIcVo9etSVZcgGIJgImQ/4tdhkUbTkU6fF"
    "pYEAKGlyF8gV6eUHvQV0yCmCjLqwfJRw30/YHmgTYAfwFGKuOmTf0hkCq54zDNs09odmBCGVXb+6o3xGHbAWHIj32SXFvYuGpyz8"
    "0JDy8HY55UBI+E/YqEupEPUkl0xz+qLLHY5YfAh0Ax0chcNO9DqPH6bpjlJSSJUzNovN8hzF3mGTvG1ChGSOYE/HDA/shxrF8qLg"
    "KEcqwaWwW9yeSdkL0HyMJ+eI0IM3QYFHasJ0QQ2oFY9yW1wLaTIcVUfTE84Hkt9iHkAGuTQEoPPb+/eZHKhPi8pLEUNhAhXHbzyI"
    "xrI/uuH3oVXjEB8cQWAI06l7obzg59FhXqH3jdKEjqnRVsEZqokkKiLXGfWLqYlOZMKrssCmZ21AbGUXPZWxMGUij0PsBSTMg8xn"
    "E7OqyDw0bvR9MLwLUPXC9AQquc1P4fflqdUZ03MLUJny9TNn56su3RhaipUND+c+y4yFCR+uOjDfChy/DDzKVVpgkEZRbioTaldQ"
    "X44o9zZ6g6z4W44qO4z8Mw/0TtTR7xKlx2HB9YrQ+Qh6snpwXIIb5CvDfQlZ0h1ZstlE6Agzm98oZ758QBD8dNfobrI8MlrRGDKE"
    "XodSZwHuOQD5gC4phL4r/cnDqyajy7PpQlTZt6ELXMAVQ7DDweb4gmByQFwGWwPwysa4wXvlT6GXpmvYTJoX/HjlWwjJePpjGHbr"
    "5rBW9Ec1zLb+CjiPKapyiubJZylCy+w1SmTLiaEk48kJPiodvWUwKh7GC4AQh7qPXm3SwJNGB4r4bMeRbCeBU85WzM21TZw1wGJ5"
    "8LA8PGh5eWPanTOG2tUDBeRILAJP1gmbFugu+xHnHgojR+OjaubPXK9a7yv426SVIGr4HwBwxmmZ6e6yytH3Luk6F/wDyMqNBzn1"
    "cm3nhwgfE2rN7M3gDVSCIEQEXrjgIcgfWGsIgxozKNQ5WxDetqFKy61Y9BDPk9UBn34RhgrbxuKsRDVwFRE1ZA2bos+4ll1TlZAm"
    "IZsPlr8YSzXHBiZejOa5PnN4lYfwc9B5MRPxQeRls5Bc+F52z1TJo/YOVaBJVtDqnIu5IiO4gjc3A0slD78HyLUYW4Df8tsz8jXJ"
    "vqdiG2ZNVPkxwaNznGpTxbryNUjOo4hR0PHEKRzc6mxZpc9Y4Dus+Qu6BXzA/Mii4Agn1upnH+rTPQ5urTQBQ2A/VwuIe1Z1lmkM"
    "AdBcb4q/HfuzsSmwihRRd6U6twubg5bgKZpU2UYPSuMrokEzXXJHNGKDdInran0S57ckbYhuOUF5w9nczjpbuuMJuASDDg8E4Z+K"
    "KuUUeB2mM0c+JUYoAD6sLvl8HlJW/j5HFOdlU/t5CufHQBraEayYWSt4FcytsEH5nFUuA6tmbaPBy7UETwGBsooqZQXQVDURkfzN"
    "fwr4VzxRbnL18DtksFdxLBJN9ERhaV7q5QbHE72q0/bdEq7cq8RC6BSH3Aysz/wQUi2Q+TwTj8gQKO7gVUo+CoRUa9cRlPai0Xth"
    "37OUnMNhVsVziI1gz/BgD+Vz04KaJ2P7aIHtmUxFhLYAz5tCTgDFQEwKbEHXnMuXYrqcnOhjcYtQYhBWSd1RryazWuG3YrSge/RS"
    "sntqVPM9IU4AS1GcvH3ngXZYzREzKFEQjAcIgtmwSPLyzwbnWD4xpVmouJAo0xTn35aBIIGdVgDsM+humWuMBMvCgTjoKHzmlaPv"
    "ZhQOhmxo0+8cGU4U3DWNVA1DDnpbhc9EgdGyArbnqLXsMmWn1iy2Ns9TpE+IsYsMBWTMzoqKnKsbBUSX+hU7cHRT2cH4WLPzEs7X"
    "djA09uCqYP1g46kTnpEUj7ST9JMii1mCaQZAYPJj18Dg1k19ZLkjIca8kG9Xv28vwYZnBeMCvTgrZqCghE9a0mjZ4D3WQfjbEeoI"
    "y6v+4lHSpKo5wXgRsnaOWF1pEwG7DMRb1g7eAA+Aeg1AIo62oTwhP/I8JbhEXNRGcQq3O2lt+hm6Lh6Iolq7ImfAXI2G9zZRJTYK"
    "f4bcA73+mVIgIEALDsOimB+UZQE0SvOzUDZuepr+p1jOfwNnEBh+c665TNO/UDzGqz8Cn4vhnVql3DgPzCX9DpyAWBKOGpya6YhF"
    "kh1i+xhchHG5C44o4HTo32h0honElG9UzkjtWU4gevnJkLdSjp5tGXz/VNYIvQVYNMQusBx5KOUy4COvYjvUV84sMHQMeUT6qnpb"
    "JSjZCkObSyp/gKcfIzkzkMjJE/CBEBni8tX1aJjIg2cJ3UmkHdAIVRwKxyZNhZrTIYp5T0FdQn58Tp5ad4UoRLlDrN9pj+ZWpuG8"
    "sIZtJU7vrKnQNpxYwzocOl2wT9j85Pfk1OR08WEiJdmKUr3KnheEiJf1IkWH24hJItfIcmzX3IM29ThpLbTSoDtPKUy+Jv65sTfv"
    "70HpeRQhJvshpQSlGhZy8IG95MfzUM0VnsvFZ8JJgH4r9/8L8XE2PZQ3Xh2mJy07TE+ilHAXBxgwMHixCo/wStZiVDD5Ebo23uMq"
    "bLSLp1RPyCCZiIN7mLKqofKlqQqW0yH7CmAn2GmrKeJfS8fJ7LOaVsy9Sg7UNKOhp40Dz0d/oIpVHG9CXPrXeT4HwXo1L/7oAAYj"
    "oDErQhDpYofP0Ry6FPPzCtCh8KRkibpAVT0KPRr6A4oBopdlSMHdUV8NOc6Rfu0pch2ekiKeOqGfDhPOe1x3zM559OTZxz9hl0Ii"
    "A0oTIKggIwMK68pu7GZnklWBLxaoDXdNqSzFgz7JqCWCKwqBO+rucrwQBe4hRd9UfhE+Tzt93SMrtw21OA8Ovl9+CTAMEqip/Yd5"
    "lddHO7OmpP6aNHXA/UiJci1sBct4A9TTUirUCPPGaAUeHL+EcJdzYbDAUBUGfgM7oAvSsdYsGllGnwtc9jUwOqmiVBwLRw7VyVzC"
    "agVlWw6H+d4hf2BIC6eeH1hCK4q11x823FrXJZmbUeGYFJ3dAgV5HA+uLM+eNbodNtyLu4hNhN5XkwpkHs+firfxVdIilS67MR9m"
    "ddEtlYXgFRA3pDVKtnuXY3KDSsV9Krh8FTltFaQTzZ7/xLACCj6s1dDfecKcUvA8PTpbQSj67yWNcrwhfnGm5HPN/zJ7NptkoWYa"
    "8NmlkbK6beoLgwODVfVjC5Uu045I8VJwCmLPirtNpV0+LmycWG2AzfKL0qY0gGPWE6rNrPPI9nPxI2SiOqK2x0dEscBTwxyh/w3L"
    "TxeRE/AvZT+S1WkLI9VxFFRTAkq30gWadd9B9dLRbo4I1aWODEwVgwNGPFwtc1G+yNWeevRSMC15rzi8UYBw/jrQlpz1g1PZWBGK"
    "65HNBw3tHtQcSaPON/o+sF6H+9ilHb3VeIXSltqL+/y1MPL3ilRQKTGeoSh1EA/1Ivk1Hz/TxuvUQqJb5ffRH7NtSuWwu8IEtaa0"
    "40wmiLWvy8oBnuBOwGkooLWcVoKNwpQaShiMmmfRMOceH4JtZEdWPBVIaojK8eWI9fFNuoYQeo4OZMVgPC2gECPxZMWzSnk09y7A"
    "Cec8EMLpdCH2NP9rQnQXZ1meI/ln8K0Wa4YsZZfQz7aEiKlpR4aqtgB5BqJ7YvcIxLoy7GPXqAeP7nRdOdE8Jw9nFWawrh8Q/osq"
    "/5Si5BsL85Ahb1F8UROfkA2UBdbR7N6AiLJ4q+0D5CkbAF3bVZN+v1LlLDLwWaiNvUO1fBQnyb6gAoCJBtMZOKt+ZkJehmLLIt+G"
    "GF48yV4lOvk1neYGly+CKbnakXABCOaZWuQ+NTjbO5rrfMeNU+XwcbM53PJh8b5ml73GMWlg9NBvsEKX34CkDda1NvDrlL6n0Br3"
    "F+Hqhk5XJ9Nk1gZn+qtFvka1WpJAOIlZIVBRGnayBfj0B7Ys2VJgEOhMpzRe/erJ5r/n2EQlTL8DLYwZEP89eB5q6GxGjqh0yVCv"
    "ADifbJbmZoucoujgFTZ1TvkQAHBCIBnpOa32UXQDHuxTR2Gef68PPafEj9A0XH3j9LgCqM8lw9maR3ETSXjSZbPMAVyuPu0daN/Z"
    "HSoom7jmKrvw0H9DJbWUQoPAmBWiMxzSQiMUjpmuyal/yp+u7ddd3qCcIRdAn6iobBT5vAlw2Rwfp24mrALIE5DUwrRotRIxyO3G"
    "eveSeHpTBZ/5/jV4Mugg2WKJwviiYA9oEYwZgG97ua8XlANQ6rHa5hAkBUFzCsKMQyKc+n3Q3RyP+8PtyI69YLostCohjTQCFlLX"
    "DplllZHpbBVcOZA1ivdFFoIcEpQdjhD0FcVIR2sS0xeZx1C+5JLi5TkNtuHcCaasOxZhp59Ajg6DYHZWlyRDTkj94rBNiGpuaaOX"
    "OsjNKn8qLbsKpFcOrAI8BOchkQ+/bwEsZTEDyp1lyswlv33zXDb3YzRlWHgquvN1bmnvB1sKKF2kpRBwrumtFb2azoAK1fC9q2dl"
    "bT1hkzw0lhXrlXi7asYov8D04IqFQIT+S0U8VzHQyHrkTI4DqoQzBxqC8vuWLoXJAEmBZ6knK5i+xHgcZ6IJBkPAwClPPxsDAJRH"
    "oPRnM+Wivs1vshxQtiKlzrZXwwtWfiCpu8NPsXtQpTA1nDG8SGRD0yQT8UY61UkLM4fIWVPNGdTGfLf2vNEhUmOYAwELzR5CcIz8"
    "HgvljywJR2BCGDRakVCxh2wjtp5R6ybff/bUUol8J44AJR1wkM0RV8ctUil+Ck0UVUSLPzeVUXaXPQMB2LQ49G+d5WbrIFs9ynKZ"
    "NZSNc9yltHC9zhNG3FwvYmn5IMtcNLRH6kPrCiTycJZKpN8CjB3+MITvdscsNJpqFkVWQLid9kqNWsJKyhbs+OzqdHZZWF87r0Z4"
    "7cJLE9VWwLZWNcJHBacWJzqdJ2PRXylskIwxPTu0d3UOuQNV7fcS7yxoeESkfAfKg8MVqCYdhTsja5LKwXzNiE2Cs4Ctj4Moi0Rj"
    "Gs7BmZ0Fy4uuBxxOVfLEBqiBmcq7eTombPKK0AhdZSeNPbYYXXUNqzh8kCe0DQoIxfaGCRwCh+Ls6hYlEXiAiMj082n3KbUXyS/C"
    "RxpTriKFboSKCHkrvbpDSnfSyxHs1WOZkvFK1mC46GW5Pw2VvNsQbFkYe3oCt6Mla2gW70Q0sVOVwI5b0hmM1XzN8IU9UQ+iWfgO"
    "FUuRz8EJK1+U0pehZ7xPv59wFqoLXm0+9WaVr395Q/NlPPtKtKxAPVv3ztfjTw8RHqC5JkcfyNmyGEAqTAOg1pxd+p9yDuKHiX2r"
    "OsZfg4aLqqh+4mAzpS0EflLhAvDyU9OBeHqwtlCIuNX9pptz2QUnyoHMS0+Nzl3EhkDA2FoKa1OiBH41jONBYEJQCCw3DSHbQ9ic"
    "1Ur7vPRvaeOGDmMS4M4gpc266o6qeBSMGgwodYa18b0FLHEVogfH1vy0nCrtK9Rtc/wwF4AY062B5HeFdmpAa6s3NUm3GjHhtun4"
    "0wGzAdjFCYZjHjMvw9CsCpvz2TbJZGkG4xvxWbb45p3aShHGg8Rumh8rDAXq4JbCo8U/4eGkbmzBaOTDTeEvWAANRHe22fa2jUYF"
    "kg3s/jPuzecg2AGcc/mqA4OxLCUgEz7yG+wTB7wabxPY0bJOvdJWGiFK00pszZOda8hsggwnMk0WlriFGprT+rIrRO1p+wGfkSNt"
    "/sIeYjW5XxkXbh39T3B7ArLY0ZVw9Oxy2/sQs0ug2ADAyUQ0wcNcopyQqCt/cpYgxu9ZnbaiQDgkOwdKcRa34zRNfaEz83h/QGEF"
    "k5hay8iE3F6YP0JU9Gkiyw0tFxyawNiSNgnl0WihBYbUQw6lXjhiKxUc9CdU8EAtS+oOx0Kj98t/kKzng7HlXcOIyRHM8KNAebV7"
    "mJYURSRnu3Ck++an0i/ghXGkhzAEkT4eUMuJHEOE5gA4eLQm8EEY+OzRZIdGSQLI3/LWNbCg1UhO8bg6lm7lW1kss0Tt/MpDP4fW"
    "L0Syl0cAQJyL+qFbQpes85O+DmX5JLuEdwW6jzxVgi+aNFPzMBxqIUC5VgVbCCzvpoWf8AaP9yOheNTS5/HMgkErTY+x1pdjYhYC"
    "OxkMky7mhaFPIPnb2tokfTRf5UpWYB5KPi6XEGFd1zB1lNOzz4zzyN64PCdshcNs/4NGdy9pckevds19G/oBGvFQ9ljActhCGTox"
    "sXZyTsTjmKz+YI1Aa49pFsyN8Iln5uNSpNgNS+nVeObCGnYxpt2gvzW9SAU29uF8DzxIUSKpQwmR/KYifUgqxbhQmNBSsFrDrh4o"
    "/im1mqZW6DLnXF3tLx6pE6xmE4uikpTarZlSMfgtPo9Auy11PVzT17kwyHFhcj5GQ8BgsvrVAS2sU8jVgFlVOdB10xTt7XiL1ziP"
    "zoJ8JVdy2mRjDe2vuR13VF4RjeTyQADnzGWU7SroLsPmts0IG3TOdrY8B+Agk5clZqebS9nx/5TC/WoOH4A3FQym02YoeqYmSmCV"
    "3nNaRuZyqeTy4+mdSjYC/a46PbUqGprTEF+CyjQZf3z81g+V5tNqMrkXiqd+eZRrmOOxC8GlpKl+HDQPIQEONbLFV9GyMUo3c3yE"
    "tOHNbTKVab0hZkvOLOqRhZwIJaQe6hjlXwF/wY1LpQIIpqBy5wKQvdBl1oWmpd/jfTP58mdLeQQ51MAD5V2FdcbIjckvx3SOD+xk"
    "2H6Q9Xsckud4lv6Ig/LwQc5ehCI5niJtmEpBZ6EhS5PmfILQOIjd96IRgX0/Cos1L8ogATREAA+hbgOceopMd9gcyaN8vwZf5KPG"
    "p4wuDnPMRaKRJxc+pEkCTsXJzeq3WisvIL9Ii3h+VU4PumoLmqITyAbRyWOWEKaFaZvHGIlSXg5PTQct/9LjrfRodY3BSrCzI5n6"
    "h9SJDBTj4sJPnbS9DJiBOVpGXRARZc0DBDZnYJRKm9eOkNHjh96JWiIstUVmo+vrQiakTU9ZN0lkOtqnDjCZVxLL4NALUWGylQie"
    "8ut5pIvRD5GuKAD6lfM+iDRQNao44aqq7GYKUG8AX7GPqqLvpgFA0malINNJxw045yO8ZlUcAScXki70qgi1wUqeNA2JEpdT1ygY"
    "iruKBFT5SFuR3WpAiIt+kk4PczIsHLZKhEZsJ+ZHwFPiPohOa7J4IrRHje+kf/0BWPrpD49+4SJCkLSMWSTdcVZOIq1IGTJJpDGL"
    "5laOC4fBBBMNB+NjNIZ0O2bxYy7YUOleArjc/n3WKjSFQIlfuOGlbKAGSwwPMd8VlIzye6NxefLq0KyVpPfBoTKjh+xLDj1M4MgO"
    "nbBEKvIXVc7BuW2XzZs2dETZCvUoEn3l5F/g9wMcoNPTCaphn2WkUT/0k9P1mLhr+Ni58KETEbERiOAO+Yaov1QH/npDb3EE1Bn6"
    "sR0xLHWWP4pwJUmOx8i5tcf6VTj9aGrgzTGXB+KsBeuI/Kup4Xgof38YWBrJAACnPzsqr9TB2QFdD7yDWkq2aJXG6alc0pBLFQfk"
    "PnobWjHoR8MbmY4iEiW7RiM7CTmalXKkdIHSCiDqlNMYvIbpS4gZj7zmM9fofkFkYUBO+EqH7Yn+DbOnomI/bu1pbp2HMTJYIh+u"
    "p2B/5ifqXsiTTgTMPP6fDIbCFnNMiKwod6atx1VChbH6/m9HTyascTJRDQz/JVA0I/TmGjPKt4l+neYIumt6rVI7f7mfFLmGbhrA"
    "wPFt6FrGycaXvsqk4NU8VnRHkN7YDUDannvwR8RmCftwR7c8mf/bUbXxbrNvOaAjF8aEQcwdv3jqS0qQGRi14Tkaepkph7i13y0n"
    "EnEPSb9FCyO9bZYftwBoTPNxHxx4iKlEtkInz4AOkbVUwwz7G7rkrvX/fH0tDUl+//YRH9fCqIIE95OHiRU4wun1VrDZsvN50veY"
    "BagCoMyzbD2aRo8WqGduFE25n+yKpIGY0F+U0g2LZokxeeqzu/C0SxNBovLkXmNV8CH/tFMYwVq96zJlYRj8pWbRPAhmrI5Ab/zl"
    "EcG4V6LT0bpjKmbZgybec6xiQ9jWcKcLUvTTc8QmIbxPub2H4hxl9ptfsKeGpM7oBwfJcRam0u2jAAcsXLZhucyNmuw/ggOP/jPg"
    "rx+ggwFaBJnyNeElu02JMRZkQw6BUp7shTPFlnE5CAIbrtTD/rIsKd3vE4WoLdnwp03qC3EAPg5qgPqBT845xyoEWQ0hbhQLcneE"
    "zhdkvGbXX4Nc3vVXCkaTG6GoDDOLYZPwcF/lX9aoD9/UtR94AMBr1wTZqwkdxuxt1YZNER5hn1SET1fmzE3kizE0qpxb2b1zC69K"
    "4mFaekcVwqUn4uDQulexKOYpABMqpAURrRCKOv10aAHgV+usQxA4ujLUdLyhk9Cm6KlJepRaW4E6EtJdm0/jmixl65Xg18zuICCh"
    "IvjYiYdbj9hY9F5Wumw3yAlTLKikHLqESpsVwCwKEpeRMzbpHXOaaZpZn3eKza1y9vmctOXURdsAKrCOmovcKF8U09TNwbSm/4ib"
    "C1cp9LptmkXCQYOI72bLWJATiklHTPM1EJ9a2f2X5MBSBZdZIKOUhGag4gbZUirgXvlKa5zHz01jRogLvM5hHy0FeVDBXqTNrlrG"
    "33G4IXUE1hfzc6pEXmi8lq4Bc/08NDy3OUOnwGnoF9U/eUrSMroirqsKN3sB4xPyjZdi1kfAj2GJwAipITCd4DSPng2km1+MLc1f"
    "y429iw0Y6Mrh03q5jZzsiO77aRoSXDa3Ygfoli74px5Yb/yuSZ0HAkoBSoWZlsHdplUoeNH48AagQwyaw1b0mrl6nY/PP/bKQfHq"
    "CkY6iN0l1szpe6fSItrNTs/K6yLA5OGgOVjniAQAFsPVkOsSw/3FJoBjPgoy2ZghwPvhw3P0whzgYYmAo8KcBIFIt9CFzL4GGAHQ"
    "I9+V9me7UlWaoMqGVaWjQDK2xANJS1HV4Z4HVaAeI9MZxkM3jx6dl3T2CoZNpyLLcdCycwAxv5dcokSSYUzK0+t9jy7TZ2ZkFopT"
    "Zl+cwjitIZkM79Q5KAR8DGGgd1N4zVbgwiEm9+zIHdm7xt1dkRfnS26pYpS7ZHkcBcX2dX3RLUSFUEzPivDkUCNdXnZRiJ7Dm54s"
    "VNJdJ5Ln6iC0EEoYVhLUlFAA2hEjg/nltBeAcFHpRoj9BjK/nznCJpLjX1tEUFwtNLhGaW5UhRiQwHFEA5MPCvvUBv7ktvdu9sQU"
    "UlXlTPzGlt203fxCKgkQ7KKGXaZN+ezLDdr1cHpDNdfmZQ+PVU44Shp+qkUHA9HOZAh8FhJIg9y7XikfFUjfvPIqR0eirRfCPdXn"
    "Jp5Wt1BBADQ3avpu91OA7wodAt5OgiuFFY2JI5VW039XhDxlWZhq9I4qOOE7mYMngXNNPSJ6yAOoXHsUPCasdcyO0zQ2RDVMdjMn"
    "Yw/V8hxZ+CyNeugmMICBb5+dwBma91Yx4SFxXuYFQhHIrSsXOF54TE9216bACYqDfuAGJx88UGv8wPvtFngaxFx5fYABCrmqB0N9"
    "LLM44O3BOtFNwbXHMCUywL/oATXCGQ2azZjSVSQKSqqMGyVMCikoUIgTg14BLmVgBUzB2Faai436llwWR7vjlJu7wJ59KRUnIsbH"
    "fCUHMdRqvBV2JpPjp57eIgukyBN4opumJ0wSKdQ2qc3mijITR63DT+0vfqVTKtPtHFzwGUDU8kJ2R97aQ10j5IzKRBvs/bKYQNyF"
    "CoEtVh2aMcOse9yv+1W34JlQJPIsY8UUnL9HsQ36AtHY6FVWHNmgUjn/PN8xk9CEraih0FwHLlAAINBWP69JtjDg5pdoeVYqqf5V"
    "UHcy1ulGgMxFGbaBwnL1s+HIsMijM4bWvFehLB2fCPHi+FEaCBd8RVDJGloCKGfgVHC8fLsMv8AWYXwSCcF1wwK2j7pA2kHNMGGW"
    "lZgExv5e6KOSMF8X3g0javngDBNAi4z8BNTf5yW5amqYJCnAzz4VKdhSDqrk6JMLwrU4IL0v2tU0ked5gS1Wl0qXzkbujKKnuTxC"
    "rhCNbi841hQR2BnwcQAnwkNRP3gPAI52bmC4RjCaRc/mf+ZvrDW8UgN+XQRPQRr3gfmLPDYe2BNM45VJ7nI30xYIMkGLl7PX/kjq"
    "Q9zYAEVegu5Sugf4ib/HaE2nSHkZu/hAfVNBD43vBYmCvNaunAXzoYgYJSaRC0v0xKIXYySTl0P5PachAfT4CHQAZjhZttmwhK4B"
    "J51R99mjkuPXI5IlW4kIG6NWD4Laq3oLz282wvRzyG2xFB41Mgsr0DWZ2zHxMPaMLr03SZPmvCEHmdm+KP7pV1zV85FNo98NhY68"
    "b/5O/aFeICJAJb5V17cMZ1KIZwlZiRHCQbSGR9mZjh0FY185SVVC3z8XcRjtsbQn0idQGSsIz4wJwM8wD69IN/M4gaZrHuWQIciu"
    "7sXgICE3KRRF6r9+AjPoex1vlnkXtxIG8jhh/iJSRonsqdA5RoKOrxskbMr4gM45ht3qsCqAXfvSu+Wsm7wT0sZpKwqSRhPBHLa4"
    "poK98xiutcVVEgZSDfZb9w61333D4Zyo1maoHFA1/3wk5vNHhwN0q5GYPQ/gw/k0vdEgzxkyOxdH2MbmFKh3YCzUKfL1TRHe8B5g"
    "Mt5fAd+HdBe8Hu+aGW3swh/9KRuUSDx11XYTNHZeYyHuuhTg6V4R31JZ2A1EyzK0vbupfFhYdk+hXbaMxwtMqusl8aiZguB9OAaT"
    "YD332YZ2HjZf80YOQ35ATpU1oct6JQP57AH05K3kHFTPYvFj1ZUKS9EZuQDNOEE0EmNUbOkw8wS+bmtMU4mwRBUu2WUstm2k0pP4"
    "MD1MY3RdFkP21riGcw62nGJHuXQEV4M8QbTBaKO4uIYDwIygPot7UIM9ebHvVcgABbhxt5H5g7uOo4epUJksYxeDBhGW0NqmD2pY"
    "hGuSvskjrTLTMFxwPZaeb/ur5eUXOE74l0/TJUwR/U1XVUx2MyzOHBVOP3zlNljM4qY+cWHHMpT9CjaIv0evnG0uVCr9kLEux7It"
    "gMbsKGXa2GqLM55JL/so37yULn2UylR5OhqpZvKxeN8zQziY171hRYn6B6qDlhlycEQiuQkEdGCZPQxrRLJGBeJAn+Ya0a57hzk+"
    "yJ+NJzYmgkumjxgif/1W10xgoLrGLfV8RmFhfRTiaybLVLezhzOkwXoqv42FG69uKVgFcYSKhMpdJpOQ/3K5mrIQ29KyB3+yRdTs"
    "VgrKPc1tksgOe1wwL3F7yw6eOwZRbhTA6aFQFZaNe7GMQljGyxPgxAKWm4UO7Bp7vdSja8pWEtMrjFf6tjiprcq3MtmxoakDLfck"
    "cv1T1m7lh6JOWzqH9yoKqUqvH3d075/Ceq2/8ZSusluyORtsJ3Uz76b+HfwFP9R1l3DhgKQFywIJpX47naNcaDAFd1VX0BXe6t+I"
    "eydy0FeooBKDi6n2SKlz/Tq8BQBmr+A8SBZ2H+MpZwoODVik0CPX/WEUHs+GYRRvU1+N8Ri30h69RFq9jgQPttCBh9jaQ5dDjxi3"
    "76ytJ6GUetRowmqq6mIw+3MYP4b3Z3/AqJBdDe0UUxe9Ha4N9QKEQJISTCQAq0E2yLRd4kPyZ2eRbyZygtjmbzrUv+1Vs/jhpBXQ"
    "G+AbCsWTubE0IggQoIHiQDin8Kn2vIsk0C7l1rBlInFUF783N5D/UZOKBs2oQX/Yn66p0jErogD+K+PWEi7A4mdArDAcbUdU3+D/"
    "eOICdvBch9cicXuFCbo2pruqKhrP5iVoQwjJfoNEBjFuzj2Uh2bPmgYCZyE69oyuQyKuKiP/I+TcBf7VdSMPNZ9NgFZMc35nKSN3"
    "KXbB/q4yy1u+BbOChx8Fj6RZPl0NcziIoU8zO0DYlpgN+27CjtSHNKNQdQ4Z8tplxkza0bC6mnfI/DmEz/GrNNnAXLX4FuJ5p10e"
    "vUxyhMCwFc4oTSIECRZnL9kB+RYr9xeXS9AcaOrz1sBUHvOB4GdIvdOx56Ow1/ba4l5cGntcAQ74AJkYXjaBfb1XV16WoPLUQ+DS"
    "vjBqZuvgPVOV9Vxh4zKCU9niK4OITOguVvY5vtIp7sJDC/IykXUqVT3Kgb0FzhqsGgNCAdZgoqREE2ZoNy0LBR1EB3k9L4SrrDQ9"
    "+yLzxTkuK2nvyKv5uF2I3thVI+k1fZlX+r15LghqZuYAoCMYUK98RuWKq9w2X1zptUP+7XVFhlMzH+LWTU1bJt55N8wHxIdbqVxd"
    "x5VpoVidDX1h7XNXhNd1MN0r47qVhc9dp9WKG87wzQc89qmWHORqcocBDgOQBlRjId4f3OXEHYEbfivL/TEa53q9YoW9MaUeU868"
    "2o+p2sm3e6fTrjX4UClyd6GG9qMDEKA0yLFuldN0+DRcmeSFgV61RiBhLw7aWGDUlXZmW5W9uRdQCqJSH6Z66QdiVDKDYTPwJ0/R"
    "r6pKZu1WEXzOPqpepy75XhErXqRjgDB3GLGD/bM5CicxQ+T0W5CnR4tqmcoQMf/GlcLQpq3QbHJYt+tTl4E3Fgu4QhSfECSvmPQX"
    "mQeP8F7yqPjnM5yqc6tv5w8dEXAlrjBjtEkq3rpxzUFp3Ujxo7yITnmJdSNkyqbLsHKU/F19HFaeA6lPy/k0PUNNem1qXaLZWikM"
    "Cf9DRNSMJxp6yALEHIzUO6lK/XIFS777o2gr3cjudZhNoWjNXkNfR7nwxb12ZUSNkntPPS3d3OSrw8HVL60Zih7G30+Z6vKElVD8"
    "yxGXMfEq5xiV8x5LbwLTKBpGGT4iI/HFogrnbKwaq8sBJrIUWHlalK/xLWNq8ftlo4LUJp5OFEsD90x0ITQYCUWY9HmkB6nSaCoP"
    "jw43bMcQCgQwcBoEAZnN+ykqFW3YKCC0I9cqjjqYc6rh8lh7taJeXd5XNmEuWrGGXJ/+tcDjIRkWHS9q6vG+tuaq/QQTJDqhSO66"
    "MgXFKiNmO6Zf7Qqw2/iZSQZkCOlFYE2dcFw8VG2yzeNRZAtrZmbDMMFwD9sMrH124JThZnbs8UZDhZWdxlyXmPwmd2eqODcYpkh3"
    "lNz8DyflUrppUIPkXB/e1YnWUbXuJbYQjW+ZnbGBXSS2TxojHwSotXQgkz8xhBCMpxk4iW+c1B+zNiPsIYwOovPNKn712HVv2aFl"
    "BSlARkXKMWAQVYgubWldzTbVzDGEnUOR/DiGwiB+ETplonFByog1ecgteoPmHbvj63WZKrTTVGX2dw3K2Y5hwz8TPhEENvaTQ7tM"
    "Q/K6xydEJnx4/hXgD3XDfczIkXJnFKWnUZkrHe4uHwQGbvNbLyfE44tCjKBN1fJm4ASyfXTouZCPl+QeMzDGlqHbRl/BixyVWSYP"
    "ENqMjc6UpK5zMv8v4AWQN2hRnqXdz2SMMUXGtEj5wl35wYhyW6W5Aq3oFSp51OFF4ez2FrJzv1Q4b1fkTiejY9cnssfM1ExCzupo"
    "JEFsZ4SSK5O2ty1C12DxVwOVtf6U1u9W2BUXKOi9aLWilSptMpN1pyhNNH6NiZWux4v1mOocy9atqKNm0sP26kwGjbL7KsDngtH4"
    "SyChUVEPweKRY5B5JddMNYn9wwntncau5Jd7kkVhCg4F0QvVCBqdyJBCeMgLQDwavEnielWBugiknhocpkYZ7AP4ZVCuEd9Ni3wI"
    "MSaB4wDrRl3zTIeMK/HYu3O3Fag3bCyrhqMDSw1VlEOhbv6uG/RU5vPblje3ms4BsyMx4IVF3I3VSjDCf6lrFKTeMvIxJXf+yfOi"
    "hJlb4NWEl6FjfdZ9d3kCimpsL7haXvYEM6hUUNLxs91CF2ibvJp2EGyZy6rdnVRiWWypcZxLzWp0VynzrpdZeTvJvQZnDY/wWQk2"
    "lbSAEE0QuLBgWj22dtT9WL1MCaaPEH0ihqo8M5+3EOzw/lfIw1V/nY2DIU1pyfoS4qaTuLfdDnlydom39HFNhGxuSXCNRsb9rTtU"
    "1eNyLwPuZvPERajUB+TYZ5aozoBhgmRUclwFkLkHMZPeL0PUhP5WMgXnHq8t/3kF7DFDmACe/Oze/YX+OFcAEXh5BvHpuaPtmPbL"
    "tVnwx+d66XWube8IlYMHZVNhH6FwgjszkB9usTMCuYHpCU3B9ayIai4RXiK6vNEG9RU5BE3j5vV6yCBWiS55eGmhrFcWbqApuBSj"
    "Nm3xOaSP8lakEwIZQ7UDACBVY5FheQQn6Sa4K5eYMYTlyFSZELye1phwvOtergp4a5ZI5ZHXNN8VXJE26sc23xE5E/m5bRk3eiqB"
    "fE6jQUgUJJ6LnXboD58ez115L3AjbTcbcMAdyHAwgcAQY1ACptDVDUQFbgCfeqamEktI88jFjZXzo4QVREtY0Iu8SpgARgpdhm+P"
    "ISqnj2sKbTN8GtXdABY/bFYy6BWkcU0JIraBkisbH6aNA5ZYWkciTTFqdSWRyzwI4KM8Mv71z7/++edfv//67//85//+57/+z//8"
    "v3//+59//j9/u9aIaVMGAA=="
)

CACHE_STUNDEN = 12


def _cache_ordner():
    # manche iPad-Apps führen die Datei als Text aus: dann gibt es kein __file__
    datei = globals().get("__file__")
    kandidaten = ([os.path.dirname(os.path.abspath(datei))] if datei else []) + [os.path.expanduser("~"), os.getcwd()]
    for basis in kandidaten:
        ordner = os.path.join(basis, "day_trader_cache")
        try:
            os.makedirs(ordner, exist_ok=True)
            return ordner
        except (OSError, ValueError):
            continue
    return None


def rohdaten(sym, offline=False, log=print):
    """(Yahoo-JSON-Text, Quelle, Symbol der Daten)."""
    sym = sym.upper()
    ordner = _cache_ordner()
    pfad = os.path.join(ordner, f"{sym}-60d5m.json.gz") if ordner else None
    if pfad and os.path.exists(pfad) and (offline or time.time() - os.path.getmtime(pfad) < CACHE_STUNDEN * 3600):
        with gzip.open(pfad, "rt", encoding="utf-8") as f:
            return f.read(), "Cache", sym
    if not offline:
        try:
            text = tm.fetch_chart(sym)
            tm.chart_result(text, sym)
            if pfad:
                try:
                    with gzip.open(pfad, "wt", encoding="utf-8") as f:
                        f.write(text)
                except OSError:
                    pass
            time.sleep(tm.PAUSE)
            return text, "Yahoo", sym
        except tm.TMError as fehler:
            log(f"{sym}: Yahoo nicht erreichbar ({fehler})")
    if pfad and os.path.exists(pfad):
        with gzip.open(pfad, "rt", encoding="utf-8") as f:
            return f.read(), "alter Cache", sym
    log(f"{sym}: nehme die eingebauten TSLA-Kerzen")
    return gzip.decompress(base64.b64decode(TSLA_GZ_B64)).decode("utf-8"), "eingebaut", "TSLA"


def sitzungen(sym, offline=False, log=print):
    text, quelle, daten_sym = rohdaten(sym, offline, log)
    ergebnis = tm.chart_result(text, daten_sym)
    jetzt = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    _, kerzen, _ = tm.parse_bars(ergebnis, jetzt)
    voll, _ = tm.full_sessions(tm.split_sessions(kerzen), before="9999-12-31")
    return voll, quelle, daten_sym


# =====================================================================================
# Teil 3 – Engine: 25 Bots, eine gemeinsame Uhr
# =====================================================================================



STARTKAPITAL = 10.0
ZIEL = 1000.0
LEER = 0.10
MAX_PUNKTE = 600            # Kontoverlauf je Bot (Tagesend-Werte), danach ausgedünnt
STANDARD_AKTIEN = ("TSLA", "NVDA", "AMD", "META", "PLTR")

# Fünf Regelprofile aus den Optionen von trader-entry und trader-exit
PROFILE = (
    {"name": "Lehrbuch", "kurz": "OR15 · Mitte · 2R", "or_minutes": 15, "stop_rule": "or_mid", "target_r": 2.0},
    {"name": "Reel", "kurz": "OR15 · Mitte · 1R", "or_minutes": 15, "stop_rule": "or_mid", "target_r": 1.0},
    {"name": "Früh", "kurz": "OR5 · Tief · 3R", "or_minutes": 5, "stop_rule": "or_low", "target_r": 3.0},
    {"name": "Geduld", "kurz": "OR30 · Mitte · 2R", "or_minutes": 30, "stop_rule": "or_mid", "target_r": 2.0},
    {"name": "Eng", "kurz": "OR15 · 0,5 % · 4R", "or_minutes": 15, "stop_rule": "pct", "stop_pct": 0.5,
     "target_r": 4.0},
)

LAEUFT, PAUSIERT, GESTOPPT = "Läuft", "Pausiert", "Gestoppt"
_TRADE_NR = itertools.count(1)  # Reihenfolge der Trades über alle Bots (für „Letzte Trades“)
ZIEL_ERREICHT, PLEITE = "Ziel erreicht", "Pleite"


class Markt:
    """Handelstage einer Aktie: zuerst echte, danach simulierte nach Art der Time Machine."""

    def __init__(self, sym, sitzungen, quelle, seed=19):
        if not sitzungen:
            raise ValueError(f"{sym}: keine vollen Handelstage")
        self.sym = sym
        self.quelle = quelle
        self.echt = sitzungen
        self.pool = tm.build_pool(sitzungen)
        # Eröffnungskerze relativ zum Vortagesschluss (die Time Machine startet erst nach dem Einstieg)
        self.luecken = [(d[0]["o"] / v[-1]["c"], d[0]["h"] / v[-1]["c"], d[0]["l"] / v[-1]["c"], d[0]["c"] / v[-1]["c"])
                        for (_, v), (_, d) in zip(sitzungen, sitzungen[1:])] or [(1, 1, 1, 1)]
        self.seed = seed
        self._sim = {}

    def tag(self, index):
        """(Bezeichnung, echt?, Kerzen) für Handelstag index (0 = erster echter Tag)."""
        if index < len(self.echt):
            datum, kerzen = self.echt[index]
            return datum, True, kerzen
        if index not in self._sim:
            vortag = self.tag(index - 1)[2]
            rng = random.Random(f"{self.seed}-{self.sym}-{index}")
            preis = vortag[-1]["c"]
            kerzen = []
            for i in range(SESSION_BARS):
                o, h, lo, c = rng.choice(self.luecken if i == 0 else self.pool[i])
                kerzen.append({"slot": i, "start": _uhr(i), "o": preis * o, "h": preis * h, "l": preis * lo,
                               "c": preis * c, "v": 0})
                preis = preis * c
            self._sim = {k: v for k, v in self._sim.items() if k >= index - 1}  # nur Vortag behalten
            self._sim[index] = kerzen
        return f"Sim-Tag {index - len(self.echt) + 1}", False, self._sim[index]


def _uhr(slot):
    m = tm.OPEN_MIN + 5 * slot
    return f"{m // 60:02d}:{m % 60:02d}"


class Bot:
    def __init__(self, bot_id, markt, profil, rng):
        self.id = bot_id
        self.markt = markt
        self.profil = profil
        self.regel = {k: profil[k] for k in ("or_minutes", "stop_rule", "target_r", "stop_pct") if k in profil}
        self._rng = rng
        self.zuruecksetzen()

    def zuruecksetzen(self):
        self.wallet_id = "W-" + uuid.UUID(int=self._rng.getrandbits(128)).hex[:8].upper()
        self.bargeld = STARTKAPITAL
        self.position = None
        self.trades = []
        self.status = None          # None, ZIEL_ERREICHT oder PLEITE
        self.modus = GESTOPPT
        self.wert = STARTKAPITAL
        self.verlauf = [(0, STARTKAPITAL)]
        self.tag_gehandelt = False
        self.spanne = None

    # ---------- Handel ----------

    def neuer_tag(self):
        self.tag_gehandelt = False
        self.spanne = None

    def kerze(self, k, kerzen, tag_text, ereignisse):
        """Verarbeitet Kerze k des Tages. Gibt nichts zurück; Ereignisse werden angehängt."""
        if self.status:
            return
        n = self.regel["or_minutes"] // 5
        b = kerzen[k]
        if self.position:
            p = self.position
            if b["l"] <= p["stop"]:
                self._schliessen(p["stop"], "Stop", b, tag_text, ereignisse)
            elif b["h"] >= p["ziel"]:
                self._schliessen(p["ziel"], "Ziel", b, tag_text, ereignisse)
            elif k >= FLAT_SLOT:
                self._schliessen(b["c"], "15:55", b, tag_text, ereignisse)
        elif (self.modus == LAEUFT and not self.tag_gehandelt and n <= k <= LETZTER_EINSTIEG):
            if self.spanne is None:
                self.spanne = tm.opening_range(kerzen, n)
            oh, ol = self.spanne
            if b["c"] > oh:
                self._eroeffnen(k, kerzen, oh, ol, tag_text, ereignisse)
        self.wert = self.bargeld + (self.position["anteile"] * b["c"] if self.position else 0.0)
        if self.wert < LEER and not self.position:
            self.status = PLEITE
            ereignisse.append(("pleite", self.id, f"💀 Bot {self.id} ist pleite."))

    def _eroeffnen(self, k, kerzen, oh, ol, tag_text, ereignisse):
        self.tag_gehandelt = True
        e = round(kerzen[k]["c"], 2)
        stop = tm.rule_stop(self.regel, oh, ol, e, True)
        risiko = e - stop
        if risiko <= 0:
            return
        ziel = round(e + self.regel["target_r"] * risiko, 2)
        anteile = self.bargeld / e
        self.position = {"einstieg": e, "stop": stop, "ziel": ziel, "anteile": anteile, "kerze": k,
                         "zeit": _uhr(k + 1), "tag": tag_text, "einsatz": self.bargeld,
                         "spanne": [round(oh, 2), round(ol, 2)]}
        self.bargeld = 0.0
        text = (f"Bot {self.id} kauft {_menge(anteile)} {self.markt.sym} zu {_usd(e)} "
                f"(Stop {_usd(stop)}, Ziel {_usd(ziel)})")
        ereignisse.append(("kauf", self.id, text))

    def _schliessen(self, preis, grund, b, tag_text, ereignisse):
        p = self.position
        erloes = p["anteile"] * preis
        ergebnis = erloes - p["einsatz"]
        r = (preis - p["einstieg"]) / (p["einstieg"] - p["stop"])
        self.bargeld = erloes
        self.position = None
        ende = _uhr(b["slot"] + 1) if "slot" in b else b["start"]
        self.trades.append({"nr": next(_TRADE_NR), "tag": tag_text, "zeit": p["zeit"], "ende": ende,
                            "aktie": self.markt.sym,
                            "menge": p["anteile"], "einstieg": p["einstieg"], "stop": p["stop"], "ziel": p["ziel"],
                            "ausstieg": preis, "grund": grund, "ergebnis": ergebnis, "r": round(r, 2),
                            "saldo": erloes})
        zeichen = "🏁" if grund == "Ziel" else ("🛑" if grund == "Stop" else "⏰")
        text = (f"{zeichen} Bot {self.id} verkauft {self.markt.sym} zu {_usd(preis)} "
                f"({grund}, {r:+.2f} R, {_eur(ergebnis, True)})")
        ereignisse.append(("verkauf", self.id, text))
        if erloes >= ZIEL:
            self.status = ZIEL_ERREICHT
            ereignisse.append(("ziel", self.id, f"🏆 Bot {self.id} hat 1.000 € erreicht!"))

    def tag_ende(self, tag_index):
        self.verlauf.append((tag_index + 1, round(self.wert, 4)))
        if len(self.verlauf) > MAX_PUNKTE:
            self.verlauf = self.verlauf[:1] + self.verlauf[1:-1:2] + self.verlauf[-1:]

    # ---------- Ausgabe ----------

    def anzeige_status(self):
        return self.status or self.modus

    def kompakt(self):
        return {"id": self.id, "wallet": self.wallet_id, "aktie": self.markt.sym, "profil": self.profil["name"],
                "regel": self.profil["kurz"], "saldo": round(self.wert, 4), "status": self.anzeige_status(),
                "modus": self.modus, "trades": len(self.trades), "offen": self.position is not None,
                "gewinner": sum(1 for t in self.trades if t["ergebnis"] > 0)}


class Rennen:
    """25 Bots, eine gemeinsame Uhr. Ein Schritt = eine Fünf-Minuten-Kerze für alle Aktien."""

    def __init__(self, maerkte, seed=7):
        self.maerkte = maerkte
        rng = random.Random(seed)
        self.bots = []
        for i, markt in enumerate(maerkte):
            for j, profil in enumerate(PROFILE):
                self.bots.append(Bot(i * len(PROFILE) + j + 1, markt, profil, rng))
        self.lock = threading.RLock()
        self.tempo = 40.0           # Kerzen pro Sekunde
        self.ereignisse = deque(maxlen=400)
        self.seq = 0
        self._zustand_neu()
        self._ende = threading.Event()
        self._thread = threading.Thread(target=self._schleife, daemon=True, name="Rennen")

    def _zustand_neu(self):
        self.tag_index = 0
        self.slot = 0
        self.laufzeit = 0.0
        self._seit = None
        self.rennen_nr = getattr(self, "rennen_nr", 0) + 1

    # ---------- Steuerung ----------

    def starten_thread(self):
        self._thread.start()

    def beenden(self):
        self._ende.set()

    def steuern(self, aktion, bot_id=None, wert=None):
        with self.lock:
            ziele = [b for b in self.bots if bot_id is None or b.id == bot_id]
            if aktion in ("start", "pause", "stop"):
                modus = {"start": LAEUFT, "pause": PAUSIERT, "stop": GESTOPPT}[aktion]
                for b in ziele:
                    b.modus = modus
                self._log("info", None, f"{'Alle Bots' if bot_id is None else f'Bot {bot_id}'}: {modus}")
            elif aktion == "umschalten" and bot_id is not None:
                for b in ziele:
                    b.modus = PAUSIERT if b.modus == LAEUFT else LAEUFT
            elif aktion == "reset":
                for b in self.bots:
                    b.zuruecksetzen()
                self._zustand_neu()
                self._log("info", None, f"Neues Rennen Nr. {self.rennen_nr}: alle Wallets wieder 10 €")
            elif aktion == "tempo" and wert is not None:
                self.tempo = max(1.0, min(2000.0, float(wert)))
            else:
                raise ValueError(f"unbekannte Aktion {aktion!r}")
            self._uhr()

    def _uhr(self):
        aktiv = any(b.modus == LAEUFT and not b.status for b in self.bots)
        if aktiv and self._seit is None:
            self._seit = time.time()
        elif not aktiv and self._seit is not None:
            self.laufzeit += time.time() - self._seit
            self._seit = None

    def aktiv(self):
        return any(b.modus == LAEUFT and not b.status for b in self.bots) or any(b.position for b in self.bots)

    # ---------- Takt ----------

    def schritt(self):
        """Eine Kerze für alle Bots. Nach der 15:55-Kerze beginnt der nächste Handelstag."""
        neu = []
        with self.lock:
            zeit = self.uhrzeit_text()  # Zeit der Kerze, bevor die Uhr weiterspringt
            tage = {m.sym: m.tag(self.tag_index) for m in self.maerkte}
            for bot in self.bots:
                text, _, kerzen = tage[bot.markt.sym]
                bot.kerze(self.slot, kerzen, text, neu)
            self.slot += 1
            if self.slot > FLAT_SLOT:
                for bot in self.bots:
                    bot.tag_ende(self.tag_index)
                    bot.neuer_tag()
                self.tag_index += 1
                self.slot = 0
            for art, bid, text in neu:
                self._log(art, bid, text, zeit)
            self._uhr()

    def _schleife(self):
        naechster = time.monotonic()
        while not self._ende.is_set():
            if not self.aktiv():
                time.sleep(0.1)
                naechster = time.monotonic()
                continue
            # bei hohem Tempo mehrere Kerzen pro Durchlauf, damit der Thread nicht nur schläft
            pro_schritt = max(1, int(self.tempo / 50))
            for _ in range(pro_schritt):
                self.schritt()
            naechster += pro_schritt / self.tempo
            pause = naechster - time.monotonic()
            if pause > 0:
                time.sleep(pause)
            else:
                naechster = time.monotonic()

    def _log(self, art, bot_id, text, zeit=None):
        self.seq += 1
        self.ereignisse.append({"seq": self.seq, "art": art, "bot": bot_id, "text": text,
                                "zeit": zeit or self.uhrzeit_text()})

    # ---------- Ausgabe ----------

    def uhrzeit_text(self):
        text, echt, _ = self.maerkte[0].tag(self.tag_index)
        return f"{text} {_uhr(self.slot + 1)}"

    def laufzeit_s(self):
        return self.laufzeit + (time.time() - self._seit if self._seit else 0)

    def schnappschuss(self, seit_seq=0):
        with self.lock:
            bots = [b.kompakt() for b in self.bots]
            salden = [b["saldo"] for b in bots]
            text, echt, kerzen = self.maerkte[0].tag(self.tag_index)
            profile = {}
            for b in self.bots:
                profile.setdefault(b.profil["name"], []).append(b.wert)
            return {
                "rennen": self.rennen_nr,
                "tag": self.tag_index + 1, "tag_text": text, "echt": echt,
                "echte_tage": min(len(m.echt) for m in self.maerkte),
                "uhr": _uhr(min(self.slot, SESSION_BARS - 1)), "slot": self.slot,
                "laufzeit": round(self.laufzeit_s()), "tempo": self.tempo,
                "gesamt": round(sum(salden), 2), "start": STARTKAPITAL * len(bots),
                "ziel": sum(1 for b in self.bots if b.status == ZIEL_ERREICHT),
                "pleite": sum(1 for b in self.bots if b.status == PLEITE),
                "offen": sum(1 for b in self.bots if b.position),
                "aktien": [{"sym": m.sym, "quelle": m.quelle, "echte_tage": len(m.echt),
                            "kurs": round(m.tag(self.tag_index)[2][min(self.slot, SESSION_BARS - 1)]["c"], 2)}
                           for m in self.maerkte],
                "profile": [{"name": p["name"], "kurz": p["kurz"],
                             "schnitt": round(sum(profile[p["name"]]) / len(profile[p["name"]]), 4)} for p in PROFILE],
                "bots": bots,
                "verlauf": {b.id: b.verlauf for b in self.bots},
                "trades": sorted((dict(t, bot=b.id) for b in self.bots for t in b.trades[-3:]),
                                 key=lambda t: t["nr"])[-8:],
                "ereignisse": [e for e in self.ereignisse if e["seq"] > seit_seq],
                "seq": self.seq,
            }

    def details(self, bot_id):
        with self.lock:
            bot = next(b for b in self.bots if b.id == bot_id)
            text, echt, kerzen = bot.markt.tag(self.tag_index)
            bis = min(self.slot, SESSION_BARS)
            return dict(bot.kompakt(), profil_kurz=bot.profil["kurz"], quelle=bot.markt.quelle,
                        tag_text=text, echt=echt, kerzen=[{k: (round(v, 2) if isinstance(v, float) else v)
                                                           for k, v in b.items()} for b in kerzen[:bis]],
                        position=bot.position, spanne=bot.spanne and [round(x, 2) for x in bot.spanne],
                        trades=bot.trades[-200:], verlauf=bot.verlauf)


def _menge(x):
    return f"{x:.4f}".replace(".", ",")


def _usd(x):
    return f"${x:,.2f}"


def _eur(x, vorzeichen=False):
    text = f"{abs(x):,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")
    return (("+" if x >= 0 else "−") + text) if vorzeichen else text


# =====================================================================================
# Teil 4 – Webserver (nur Standardbibliothek)
# =====================================================================================


VERLAUF_PUNKTE = 240


def _duenn(punkte, n=VERLAUF_PUNKTE):
    """Kontoverlauf für die Übertragung ausdünnen (erster und letzter Punkt bleiben)."""
    if len(punkte) <= n:
        return punkte
    schritt = (len(punkte) - 1) / (n - 1)
    return [punkte[round(i * schritt)] for i in range(n)]


def handler_fuer(rennen):
    class Handler(BaseHTTPRequestHandler):
        server_version = "DayTraderRennen/1.0"

        def log_message(self, *args):  # keine Zeile pro Anfrage im Terminal
            pass

        def _json(self, daten, code=200):
            body = json.dumps(daten, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _datei(self, pfad):
            if pfad not in DATEIEN:
                self.send_error(404)
                return
            typ, text = DATEIEN[pfad]
            body = text.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", typ + "; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            url = urlparse(self.path)
            q = parse_qs(url.query)
            if url.path in ("/", "/index.html"):
                return self._datei("index.html")
            if url.path.startswith("/static/"):
                return self._datei(url.path[len("/static/"):])
            if url.path == "/api/zustand":
                seit = int((q.get("seit") or ["0"])[0] or 0)
                s = rennen.schnappschuss(seit)
                if (q.get("verlauf") or ["0"])[0] == "1":
                    s["verlauf"] = {bid: _duenn(v) for bid, v in s["verlauf"].items()}
                else:
                    s.pop("verlauf")
                return self._json(s)
            if url.path.startswith("/api/bot/"):
                try:
                    d = rennen.details(int(url.path.rsplit("/", 1)[1]))
                except (ValueError, StopIteration):
                    return self._json({"fehler": "unbekannter Bot"}, 404)
                d["verlauf"] = _duenn(d["verlauf"], 400)
                return self._json(d)
            self.send_error(404)

        def do_POST(self):
            if urlparse(self.path).path != "/api/steuerung":
                return self.send_error(404)
            try:
                laenge = min(int(self.headers.get("Content-Length") or 0), 10000)
                daten = json.loads(self.rfile.read(laenge) or b"{}")
                bot = daten.get("bot")
                rennen.steuern(str(daten.get("aktion")), int(bot) if bot is not None else None, daten.get("wert"))
            except (ValueError, TypeError) as fehler:
                return self._json({"fehler": str(fehler)}, 400)
            return self._json({"ok": True})

    return Handler


def starten(rennen, host, port):
    server = ThreadingHTTPServer((host, port), handler_fuer(rennen))
    server.daemon_threads = True
    return server


# =====================================================================================
# Teil 5 – Oberfläche (HTML, CSS, JavaScript)
# =====================================================================================

INDEX_HTML = r'''<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#07070a">
<title>Day-Trader-Rennen</title>
<link rel="stylesheet" href="/static/app.css">
</head>
<body>
<div class="hintergrund" aria-hidden="true"></div>

<aside class="seitenleiste">
  <div class="logo" title="Day-Trader-Rennen">
    <svg viewBox="0 0 40 40" aria-hidden="true"><path d="M20 3 35 11v18L20 37 5 29V11z" fill="none" stroke="currentColor" stroke-width="2"/><path d="M12 25l5-6 4 4 7-9" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>
  </div>
  <nav>
    <a href="#oben" class="aktiv" title="Übersicht"><svg viewBox="0 0 24 24"><path d="M4 11l8-7 8 7v9h-5v-6H9v6H4z"/></svg></a>
    <a href="#bots" title="Bots"><svg viewBox="0 0 24 24"><path d="M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z"/></svg></a>
    <a href="#trades" title="Trades"><svg viewBox="0 0 24 24"><path d="M5 20V10M10 20V4M15 20v-7M20 20V8"/></svg></a>
    <a href="#markt" title="Markt"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8"/><path d="M4 12h16M12 4c3 3 3 13 0 16M12 4c-3 3-3 13 0 16"/></svg></a>
  </nav>
  <a class="unten" href="https://github.com/Jakeschincariol/day-trader-skill" target="_blank" rel="noopener" title="Regeln: day-trader-skill"><svg viewBox="0 0 24 24"><path d="M12 3l8 4v5c0 5-3.5 8-8 9-4.5-1-8-4-8-9V7z"/></svg></a>
</aside>

<main id="oben">
  <header class="kopf">
    <div>
      <h1>Day-Trader-Rennen <span class="winken">⚡</span></h1>
      <p class="unterzeile">25 Bots · je 10 € · Ziel 1.000 € · Regeln aus <b>day-trader-skill</b> · Spielgeld</p>
    </div>
    <div class="kopf-rechts">
      <div class="pille" id="tag-pille" title="Handelstag">
        <svg viewBox="0 0 24 24"><rect x="4" y="5" width="16" height="15" rx="2"/><path d="M4 10h16M9 3v4M15 3v4"/></svg>
        <span id="tag-text">–</span>
      </div>
      <div class="steuerung">
        <button class="knopf gold" data-aktion="start" title="Alle starten">▶<span> Start</span></button>
        <button class="knopf" data-aktion="pause" title="Alle pausieren">❚❚<span> Pause</span></button>
        <button class="knopf" data-aktion="stop" title="Alle stoppen">■<span> Stopp</span></button>
        <button class="knopf" data-aktion="reset" title="Alle auf 10 € zurücksetzen">↺<span> Reset</span></button>
      </div>
      <label class="tempo" title="Geschwindigkeit: Kerzen pro Sekunde">
        <span>Tempo</span>
        <input type="range" id="tempo" min="0" max="100" value="45">
        <output id="tempo-wert">40/s</output>
      </label>
    </div>
  </header>

  <section class="kpis">
    <article class="kpi"><div class="kpi-icon">€</div><div><p>Gesamtkapital</p><h3 id="k-gesamt">–</h3><small id="k-gesamt-d">–</small></div></article>
    <article class="kpi"><div class="kpi-icon">▲</div><div><p>Bester Bot</p><h3 id="k-bester">–</h3><small id="k-bester-d">–</small></div></article>
    <article class="kpi"><div class="kpi-icon">▼</div><div><p>Schlechtester Bot</p><h3 id="k-schlecht">–</h3><small id="k-schlecht-d">–</small></div></article>
    <article class="kpi"><div class="kpi-icon">🏆</div><div><p>Ziel erreicht</p><h3 id="k-ziel">–</h3><small>von 25 Bots</small></div></article>
    <article class="kpi"><div class="kpi-icon">✕</div><div><p>Pleite</p><h3 id="k-pleite">–</h3><small>Wallet leer</small></div></article>
    <article class="kpi"><div class="kpi-icon">◷</div><div><p>Laufzeit</p><h3 id="k-zeit">–</h3><small id="k-offen">–</small></div></article>
  </section>

  <section class="reihe2">
    <article class="karte verlauf">
      <div class="karten-kopf">
        <div><h2>Kontoverlauf</h2><p class="gross" id="v-wert">–</p><small id="v-sub">–</small></div>
        <div class="tabs" id="v-tabs">
          <button data-ansicht="alle" class="an">Alle Bots</button>
          <button data-ansicht="gesamt">Gesamt</button>
        </div>
      </div>
      <svg id="chart-verlauf" class="chart" preserveAspectRatio="none"></svg>
      <div class="legende"><span><i class="punkt gold"></i>ausgewählter Bot</span><span><i class="strich"></i>Ziel 1.000 €</span><span>log. Skala · ein Punkt pro Handelstag</span></div>
    </article>

    <article class="karte hud" id="markt">
      <i class="ecke lo"></i><i class="ecke ro"></i><i class="ecke lu"></i><i class="ecke ru"></i>
      <div class="hud-kopf"><span>NYSE · NEW YORK</span><span id="hud-quelle">–</span></div>
      <canvas id="globus" aria-label="Weltkugel mit New York Stock Exchange"></canvas>
      <div class="hud-uhr"><div id="hud-zeit">09:30</div><div id="hud-tag">–</div></div>
      <div class="hud-fuss" id="hud-fuss"></div>
    </article>

    <article class="karte rangliste">
      <div class="karten-kopf"><h2>Rangliste</h2><small>Top 5 nach Kontostand</small></div>
      <ol id="rangliste"></ol>
      <div class="karten-kopf klein"><h2>Ø pro Regelprofil</h2></div>
      <svg id="chart-profile" class="chart klein" preserveAspectRatio="none"></svg>
    </article>
  </section>

  <section class="karte bots" id="bots">
    <div class="karten-kopf">
      <div><h2>Die 25 Bots</h2><small>Antippen hebt die Linie hervor · ⤢ öffnet die Details · Balken logarithmisch 10 € → 1.000 €</small></div>
      <div class="farblegende"><span class="plus">im Plus</span><span class="minus">im Minus</span><span class="ziel">1.000 €</span><span class="leer">leer</span></div>
    </div>
    <div class="raster" id="raster"></div>
  </section>

  <section class="reihe4" id="trades">
    <article class="karte trades">
      <div class="karten-kopf"><h2>Letzte Trades</h2></div>
      <ul id="trade-liste"></ul>
    </article>
    <article class="karte log hud-rahmen">
      <i class="ecke lo"></i><i class="ecke ro"></i><i class="ecke lu"></i><i class="ecke ru"></i>
      <div class="karten-kopf"><h2>Ereignisse</h2><small id="log-zahl">–</small></div>
      <div id="log"></div>
    </article>
    <article class="karte donut-karte">
      <div class="karten-kopf"><h2>Kapital nach Aktie</h2></div>
      <div class="donut-wrap"><svg id="chart-donut" viewBox="0 0 200 200"></svg><ul id="donut-legende"></ul></div>
    </article>
  </section>

  <footer class="laufband">
    <div id="laufband"></div>
    <p>Spielgeld-Simulation. Keine Anlageberatung. Echte Kerzen von Yahoo (60 Tage), danach simulierte Tage nach Art der Time Machine. Bruchstück-Aktien, kein Hebel, Wechselkurs nicht berücksichtigt.</p>
  </footer>
</main>

<dialog id="detail">
  <div class="detail-kopf">
    <div><h2 id="d-titel">Bot</h2><p id="d-sub">–</p></div>
    <div class="detail-knoepfe"><button class="knopf gold" id="d-umschalten">❚❚ Pause</button><button class="knopf" id="d-zu" aria-label="Schließen">✕</button></div>
  </div>
  <div class="detail-zahlen" id="d-zahlen"></div>
  <div class="detail-charts">
    <div><h3 id="d-kerzen-titel">Heute</h3><svg id="d-kerzen" class="chart" preserveAspectRatio="none"></svg></div>
    <div><h3>Kontostand</h3><svg id="d-konto" class="chart" preserveAspectRatio="none"></svg></div>
  </div>
  <h3>Trade-Historie</h3>
  <div class="tabelle-wrap"><table><thead><tr><th>Tag</th><th>Zeit</th><th>Aktie</th><th>Menge</th><th>Einstieg</th><th>Ausstieg</th><th>Grund</th><th>R</th><th>Ergebnis</th></tr></thead><tbody id="d-trades"></tbody></table></div>
</dialog>

<div id="toast" role="status"></div>
<script src="/static/app.js"></script>
</body>
</html>
'''

APP_CSS = r'''/* Day-Trader-Rennen: Schwarz-Gold (Bild 1) + Glaskarten und Verläufe (Bild 2) + HUD-Linien (Bild 3) */
:root {
  --bg: #060608;
  --panel: rgba(24, 21, 18, 0.72);
  --panel-2: rgba(34, 29, 24, 0.8);
  --rand: rgba(255, 196, 110, 0.13);
  --rand-hell: rgba(255, 196, 110, 0.35);
  --gold: #f4b740;
  --gold-hell: #ffd77a;
  --orange: #ff8a3d;
  --gruen: #3ddc97;
  --rot: #ff5f5f;
  --grau: #7d7a76;
  --text: #f4efe7;
  --gedaempft: #a39b8f;
  --schwach: #6d675f;
  --radius: 18px;
  --schatten: 0 10px 40px rgba(0, 0, 0, 0.45);
  --mono: ui-monospace, "SF Mono", "JetBrains Mono", Menlo, Consolas, monospace;
  color-scheme: dark;
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0; background: var(--bg); color: var(--text);
  font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Roboto, sans-serif;
  -webkit-font-smoothing: antialiased; min-height: 100vh;
}
.hintergrund {
  position: fixed; inset: 0; z-index: -1; pointer-events: none;
  background:
    radial-gradient(900px 500px at 78% -10%, rgba(255, 138, 61, 0.16), transparent 60%),
    radial-gradient(700px 500px at 10% 110%, rgba(244, 183, 64, 0.10), transparent 60%),
    linear-gradient(rgba(255, 255, 255, 0.025) 1px, transparent 1px) 0 0 / 44px 44px,
    linear-gradient(90deg, rgba(255, 255, 255, 0.025) 1px, transparent 1px) 0 0 / 44px 44px,
    var(--bg);
}
h1, h2, h3, p { margin: 0; }
small { color: var(--gedaempft); }
button { font: inherit; color: inherit; }

/* ---------- Seitenleiste ---------- */
.seitenleiste {
  position: fixed; left: 14px; top: 14px; bottom: 14px; width: 64px; z-index: 5;
  display: flex; flex-direction: column; align-items: center; gap: 22px; padding: 16px 0;
  background: rgba(16, 14, 12, 0.85); border: 1px solid var(--rand); border-radius: 22px;
  backdrop-filter: blur(14px); -webkit-backdrop-filter: blur(14px);
}
.logo { width: 38px; height: 38px; color: var(--gold); filter: drop-shadow(0 0 8px rgba(244, 183, 64, 0.5)); }
.seitenleiste nav { display: flex; flex-direction: column; gap: 10px; }
.seitenleiste a { display: grid; place-items: center; width: 42px; height: 42px; border-radius: 12px; color: var(--gedaempft); }
.seitenleiste a.aktiv { background: linear-gradient(135deg, var(--orange), var(--gold)); color: #1a1208; box-shadow: 0 6px 20px rgba(255, 138, 61, 0.35); }
.seitenleiste a:hover:not(.aktiv) { color: var(--gold); background: rgba(244, 183, 64, 0.08); }
.seitenleiste svg { width: 20px; height: 20px; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }
.seitenleiste .unten { margin-top: auto; }

main { margin-left: 92px; padding: 18px 22px 18px 6px; display: flex; flex-direction: column; gap: 16px; max-width: 1760px; }

/* ---------- Kopf ---------- */
.kopf { display: flex; justify-content: space-between; align-items: center; gap: 16px; flex-wrap: wrap; }
.kopf h1 { font-size: 26px; font-weight: 700; letter-spacing: -0.01em; }
.winken { color: var(--gold); }
.unterzeile { color: var(--gedaempft); margin-top: 2px; }
.unterzeile b { color: var(--gold-hell); font-weight: 600; }
.kopf-rechts { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.pille {
  display: flex; align-items: center; gap: 8px; padding: 9px 14px; border-radius: 12px;
  border: 1px solid var(--rand-hell); color: var(--gold-hell); background: rgba(244, 183, 64, 0.06); font-weight: 600;
}
.pille svg { width: 18px; height: 18px; fill: none; stroke: currentColor; stroke-width: 1.8; }
.steuerung { display: flex; gap: 6px; }
.knopf {
  border: 1px solid var(--rand); background: var(--panel-2); padding: 9px 13px; border-radius: 12px;
  cursor: pointer; font-weight: 600; transition: transform 0.1s, border-color 0.2s, background 0.2s;
}
.knopf:hover { border-color: var(--rand-hell); }
.knopf:active { transform: scale(0.96); }
.knopf.gold { background: linear-gradient(135deg, var(--orange), var(--gold)); color: #1b1206; border-color: transparent; box-shadow: 0 6px 18px rgba(255, 138, 61, 0.3); }
.tempo { display: flex; align-items: center; gap: 8px; color: var(--gedaempft); font-size: 12px; }
.tempo input { width: 120px; accent-color: var(--gold); }
.tempo output { color: var(--gold-hell); font-family: var(--mono); min-width: 52px; }

/* ---------- Karten ---------- */
.karte, .kpi {
  background: var(--panel); border: 1px solid var(--rand); border-radius: var(--radius);
  box-shadow: var(--schatten); backdrop-filter: blur(16px); -webkit-backdrop-filter: blur(16px); position: relative;
}
.karte { padding: 16px 18px; min-width: 0; }
.karten-kopf { display: flex; justify-content: space-between; align-items: flex-start; gap: 10px; margin-bottom: 10px; }
.karten-kopf h2 { font-size: 15px; font-weight: 600; }
.karten-kopf.klein { margin-top: 14px; }
.gross { font-size: 28px; font-weight: 600; margin-top: 4px; letter-spacing: -0.01em; }

/* KPIs wie Bild 1 */
.kpis { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 12px; }
.kpi { display: flex; align-items: center; gap: 14px; padding: 14px 16px; }
.kpi p { color: var(--gedaempft); font-size: 12px; }
.kpi h3 { font-size: 20px; font-weight: 700; margin: 2px 0 1px; white-space: nowrap; }
.kpi small { font-size: 12px; }
.kpi-icon {
  flex: none; width: 46px; height: 46px; border-radius: 50%; display: grid; place-items: center;
  font-size: 18px; font-weight: 800; color: #1b1206;
  background: radial-gradient(circle at 30% 30%, var(--gold-hell), var(--gold) 55%, #a8721c);
  box-shadow: 0 0 0 4px rgba(244, 183, 64, 0.12), 0 0 22px rgba(244, 183, 64, 0.35);
}
.auf { color: var(--gruen); }
.ab { color: var(--rot); }

/* Reihe 2 */
.reihe2 { display: grid; grid-template-columns: minmax(0, 1.6fr) minmax(0, 1fr) minmax(0, 0.95fr); gap: 14px; }
.chart { width: 100%; display: block; overflow: visible; }
.verlauf .chart { height: 290px; }
.tabs { display: flex; gap: 4px; background: rgba(0, 0, 0, 0.35); padding: 4px; border-radius: 12px; border: 1px solid var(--rand); }
.tabs button { border: 0; background: transparent; padding: 6px 12px; border-radius: 9px; color: var(--gedaempft); cursor: pointer; }
.tabs button.an { background: rgba(255, 255, 255, 0.1); color: var(--text); }
.legende { display: flex; gap: 16px; flex-wrap: wrap; margin-top: 8px; color: var(--gedaempft); font-size: 12px; }
.punkt { display: inline-block; width: 9px; height: 9px; border-radius: 50%; margin-right: 6px; vertical-align: 0; }
.punkt.gold { background: var(--gold); box-shadow: 0 0 8px var(--gold); }
.strich { display: inline-block; width: 18px; border-top: 2px dashed var(--gold); margin-right: 6px; vertical-align: 3px; }

/* HUD (Bild 3) */
.hud { background: rgba(6, 6, 8, 0.82); overflow: hidden; display: flex; flex-direction: column; min-height: 380px; }
.hud canvas { width: 100%; flex: 1; min-height: 260px; display: block; }
.hud-kopf { display: flex; justify-content: space-between; font: 600 11px/1 var(--mono); letter-spacing: 0.14em; color: var(--gedaempft); }
.hud-kopf span:first-child { color: var(--gold-hell); }
.hud-uhr { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; font-family: var(--mono); margin: 4px 0 10px; }
.hud-uhr #hud-zeit { font-size: 30px; color: var(--gold-hell); text-shadow: 0 0 14px rgba(244, 183, 64, 0.6); letter-spacing: 0.06em; }
.hud-uhr #hud-tag { font-size: 11px; color: var(--gedaempft); letter-spacing: 0.12em; text-transform: uppercase; }
.hud-fuss { display: flex; gap: 6px; flex-wrap: wrap; font: 11px/1 var(--mono); }
.hud-fuss span { padding: 5px 7px; border: 1px solid rgba(255, 255, 255, 0.12); color: var(--gedaempft); }
.hud-fuss b { color: var(--text); font-weight: 600; }
.ecke { position: absolute; width: 14px; height: 14px; border-color: var(--gold); border-style: solid; opacity: 0.8; pointer-events: none; }
.ecke.lo { left: 8px; top: 8px; border-width: 2px 0 0 2px; }
.ecke.ro { right: 8px; top: 8px; border-width: 2px 2px 0 0; }
.ecke.lu { left: 8px; bottom: 8px; border-width: 0 0 2px 2px; }
.ecke.ru { right: 8px; bottom: 8px; border-width: 0 2px 2px 0; }

/* Rangliste (Top Services in Bild 1) */
.rangliste ol { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 11px; }
.rangliste li { display: grid; grid-template-columns: 30px 1fr auto; gap: 2px 10px; align-items: center; cursor: pointer; }
.rang { grid-row: span 2; width: 30px; height: 30px; border-radius: 9px; display: grid; place-items: center; font-weight: 700; color: var(--gold); border: 1px solid var(--rand-hell); background: rgba(244, 183, 64, 0.07); }
.rangliste .name { font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.rangliste .betrag { font-weight: 600; font-family: var(--mono); }
.balken { grid-column: 2 / 4; height: 5px; border-radius: 3px; background: rgba(255, 255, 255, 0.07); overflow: hidden; }
.balken i { display: block; height: 100%; border-radius: 3px; background: linear-gradient(90deg, var(--orange), var(--gold)); }
.chart.klein { height: 120px; }

/* ---------- Bot-Raster ---------- */
.farblegende { display: flex; gap: 12px; font-size: 12px; color: var(--gedaempft); flex-wrap: wrap; }
.farblegende span::before { content: ""; display: inline-block; width: 10px; height: 10px; border-radius: 3px; margin-right: 5px; vertical-align: -1px; }
.farblegende .plus::before { background: var(--gruen); }
.farblegende .minus::before { background: var(--rot); }
.farblegende .ziel::before { background: var(--gold); }
.farblegende .leer::before { background: var(--grau); }
.raster { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 10px; }
.bot {
  --farbe: var(--grau);
  position: relative; padding: 11px 12px 10px; border-radius: 14px; cursor: pointer; min-width: 0;
  background: linear-gradient(160deg, rgba(255, 255, 255, 0.055), rgba(255, 255, 255, 0.015));
  border: 1px solid rgba(255, 255, 255, 0.08); transition: border-color 0.2s, box-shadow 0.2s, transform 0.15s;
}
.bot::before { content: ""; position: absolute; left: 0; top: 12px; bottom: 12px; width: 3px; border-radius: 0 3px 3px 0; background: var(--farbe); box-shadow: 0 0 10px var(--farbe); }
.bot:hover { transform: translateY(-1px); }
.bot.plus { --farbe: var(--gruen); }
.bot.minus { --farbe: var(--rot); }
.bot.ziel { --farbe: var(--gold); background: linear-gradient(160deg, rgba(244, 183, 64, 0.28), rgba(244, 183, 64, 0.06)); border-color: rgba(244, 183, 64, 0.6); box-shadow: 0 0 24px rgba(244, 183, 64, 0.25); }
.bot.leer { --farbe: var(--grau); opacity: 0.55; filter: grayscale(0.8); }
.bot.gewaehlt { border-color: var(--gold); box-shadow: 0 0 0 1px var(--gold), 0 0 22px rgba(244, 183, 64, 0.3); }
.bot-kopf { display: flex; justify-content: space-between; align-items: center; gap: 6px; }
.bot-kopf b { font-size: 13px; }
.chip { font-size: 10px; padding: 2px 7px; border-radius: 20px; border: 1px solid var(--rand-hell); color: var(--gold-hell); white-space: nowrap; }
.bot-regel { font-size: 11px; color: var(--schwach); margin: 1px 0 6px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.bot-zahl { display: flex; justify-content: space-between; align-items: baseline; gap: 6px; }
.bot-zahl .saldo { font-size: 19px; font-weight: 700; font-family: var(--mono); letter-spacing: -0.02em; }
.bot-zahl .pz { font-size: 12px; font-weight: 600; }
.bot svg.spark { width: 100%; height: 26px; display: block; margin: 4px 0; }
.fortschritt { height: 5px; border-radius: 3px; background: rgba(255, 255, 255, 0.07); overflow: hidden; }
.fortschritt i { display: block; height: 100%; background: linear-gradient(90deg, var(--orange), var(--gold-hell)); box-shadow: 0 0 8px var(--gold); }
.bot-fuss > span { white-space: nowrap; }
.bot-fuss { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; margin-top: 7px; font-size: 11px; color: var(--gedaempft); gap: 4px 6px; }
.bot-fuss > span:last-child { margin-left: auto; }
.status { display: inline-flex; align-items: center; gap: 5px; }
.status::before { content: ""; width: 7px; height: 7px; border-radius: 50%; background: var(--grau); }
.status.Läuft::before { background: var(--gruen); box-shadow: 0 0 6px var(--gruen); }
.status.Pausiert::before { background: var(--orange); }
.status.Ziel::before { background: var(--gold); box-shadow: 0 0 6px var(--gold); }
.status.Pleite::before { background: var(--rot); }
.offen-punkt { color: var(--gold-hell); font-weight: 700; }
.mini { border: 1px solid rgba(255, 255, 255, 0.12); background: rgba(0, 0, 0, 0.3); border-radius: 8px; width: 26px; height: 24px; cursor: pointer; font-size: 11px; display: inline-grid; place-items: center; }
.mini:hover { border-color: var(--gold); color: var(--gold); }
.mini:disabled { opacity: 0.35; cursor: default; }

/* ---------- Reihe 4 ---------- */
.reihe4 { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.25fr) minmax(0, 0.9fr); gap: 14px; }
.trades ul { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; }
.trades li { display: grid; grid-template-columns: 38px 1fr auto; gap: 0 10px; align-items: center; padding: 8px 10px; border-radius: 12px; background: rgba(255, 255, 255, 0.035); border: 1px solid rgba(255, 255, 255, 0.05); }
.avatar { grid-row: span 2; width: 38px; height: 38px; border-radius: 50%; display: grid; place-items: center; font-size: 11px; font-weight: 800; color: #1b1206; background: linear-gradient(135deg, var(--gold-hell), var(--orange)); }
.trades .t1 { font-weight: 600; }
.trades .t2 { font-size: 12px; color: var(--gedaempft); }
.trades .betrag { grid-row: span 2; font-family: var(--mono); font-weight: 600; text-align: right; }
.log #log { font: 12px/1.6 var(--mono); height: 330px; overflow-y: auto; color: var(--gedaempft); padding-right: 4px; }
.log #log div { border-bottom: 1px dashed rgba(255, 255, 255, 0.05); padding: 2px 0; }
.log #log .zeit { color: var(--schwach); margin-right: 8px; }
.log #log .ziel { color: var(--gold-hell); }
.log #log .pleite { color: var(--rot); }
.log #log .verkauf { color: var(--text); }
.log #log .info { color: var(--orange); }
.hud-rahmen { background: rgba(6, 6, 8, 0.82); }
.donut-wrap { display: flex; flex-direction: column; align-items: center; gap: 12px; }
#chart-donut { width: 190px; height: 190px; }
#donut-legende { list-style: none; padding: 0; margin: 0; width: 100%; display: grid; gap: 6px; font-size: 13px; }
#donut-legende li { display: flex; justify-content: space-between; gap: 8px; }
#donut-legende i { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 8px; }

/* Laufband (Bild 3, unten) */
.laufband { border-top: 1px solid var(--rand); padding-top: 10px; color: var(--schwach); font-size: 12px; }
#laufband { display: flex; gap: 18px; flex-wrap: wrap; font: 12px var(--mono); margin-bottom: 6px; color: var(--gedaempft); }
#laufband b { color: var(--text); }
#laufband i { display: inline-block; width: 9px; height: 9px; margin-right: 6px; vertical-align: 0; }

/* Chart-Elemente */
.achse text { fill: var(--schwach); font-size: 11px; font-family: var(--mono); }
.achse line { stroke: rgba(255, 255, 255, 0.06); }
.zielinie { stroke: var(--gold); stroke-dasharray: 6 5; stroke-width: 1.4; }
.tooltip-box rect { fill: #f4efe7; }
.tooltip-box text { fill: #15110b; font-size: 12px; font-weight: 600; }

/* Detail-Dialog */
dialog {
  width: min(980px, calc(100vw - 24px)); max-height: calc(100vh - 24px); overflow: auto;
  background: rgba(16, 14, 12, 0.97); color: var(--text); border: 1px solid var(--rand-hell);
  border-radius: 22px; padding: 20px; box-shadow: 0 30px 80px rgba(0, 0, 0, 0.7);
}
dialog::backdrop { background: rgba(0, 0, 0, 0.6); backdrop-filter: blur(4px); }
.detail-kopf { display: flex; justify-content: space-between; gap: 10px; align-items: flex-start; }
.detail-kopf h2 { font-size: 22px; }
.detail-kopf p { color: var(--gedaempft); }
.detail-knoepfe { display: flex; gap: 6px; }
.detail-zahlen { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 10px; margin: 14px 0; }
.detail-zahlen div { background: rgba(255, 255, 255, 0.04); border: 1px solid var(--rand); border-radius: 12px; padding: 10px 12px; }
.detail-zahlen small { display: block; font-size: 11px; }
.detail-zahlen b { font-size: 17px; font-family: var(--mono); }
.detail-charts { display: grid; grid-template-columns: 1.4fr 1fr; gap: 14px; }
.detail-charts .chart { height: 220px; background: rgba(0, 0, 0, 0.25); border-radius: 12px; border: 1px solid rgba(255, 255, 255, 0.05); }
dialog h3 { font-size: 13px; color: var(--gedaempft); font-weight: 600; margin: 10px 0 6px; }
.tabelle-wrap { max-height: 260px; overflow: auto; border-radius: 12px; border: 1px solid var(--rand); }
table { width: 100%; border-collapse: collapse; font-size: 12px; }
th { position: sticky; top: 0; background: #1d1913; color: var(--gedaempft); font-weight: 600; text-align: left; padding: 8px; }
td { padding: 7px 8px; border-top: 1px solid rgba(255, 255, 255, 0.05); font-family: var(--mono); white-space: nowrap; }
td.zahl, th.zahl { text-align: right; }

#toast { position: fixed; bottom: 18px; left: 50%; transform: translateX(-50%) translateY(20px); background: #f4efe7; color: #15110b; padding: 10px 16px; border-radius: 12px; font-weight: 600; transition: transform 0.3s, opacity 0.3s; z-index: 20; opacity: 0; visibility: hidden; }
#toast.zeigen { transform: translateX(-50%) translateY(0); opacity: 1; visibility: visible; }

/* ---------- Responsiv (iPad, Handy) ---------- */
@media (max-width: 1400px) {
  .kpis { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .reihe2 { grid-template-columns: minmax(0, 1.3fr) minmax(0, 1fr); }
  .rangliste { grid-column: 1 / -1; }
  .reihe4 { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); }
  .donut-karte { grid-column: 1 / -1; }
  .donut-wrap { flex-direction: row; justify-content: center; }
  #donut-legende { max-width: 280px; }
}
@media (max-width: 1100px) {
  .raster { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .reihe2 { grid-template-columns: minmax(0, 1fr); }
}
@media (max-width: 820px) {
  .seitenleiste { top: auto; bottom: 10px; left: 50%; transform: translateX(-50%); width: auto; height: 58px; flex-direction: row; padding: 0 14px; gap: 12px; }
  .seitenleiste nav { flex-direction: row; }
  .seitenleiste .unten { margin: 0; }
  main { margin-left: 0; padding: 14px 16px 90px; }
  .kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .raster { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .reihe4 { grid-template-columns: minmax(0, 1fr); }
  .kopf-rechts { width: 100%; justify-content: space-between; }
  .steuerung .knopf span { display: none; }
  .detail-zahlen { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .detail-charts { grid-template-columns: minmax(0, 1fr); }
  .kpi h3 { font-size: 17px; }
}
@media (prefers-reduced-motion: reduce) { * { transition: none !important; } }
'''

APP_JS = r'''/* Day-Trader-Rennen – Oberfläche. Liest den Rennstand per Polling von /api/zustand. */
"use strict";

const $ = (id) => document.getElementById(id);
const NS = "http://www.w3.org/2000/svg";
const ZIEL = 1000, START = 10;
const eur = new Intl.NumberFormat("de-DE", { style: "currency", currency: "EUR" });
const usd = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });
const zahl2 = new Intl.NumberFormat("de-DE", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const prozent = (x) => (x >= 0 ? "+" : "−") + zahl2.format(Math.abs(x)) + " %";
const AKTIEN_FARBEN = ["#f4b740", "#ff8a3d", "#ffd77a", "#c9772b", "#8a6a3a"];

const zustand = {
  daten: null, verlauf: {}, gewaehlt: null, ansicht: "alle", seq: 0, runde: 0,
  logZeilen: 0, kacheln: {}, detailId: null, fehler: false,
};

/* ---------------- Hilfen ---------------- */
function el(tag, attrs = {}, text) {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (text !== undefined) e.textContent = text;
  return e;
}
function leeren(svg) {
  while (svg.firstChild) svg.removeChild(svg.firstChild);
  const r = svg.getBoundingClientRect();
  const w = Math.max(50, r.width), h = Math.max(50, r.height);
  svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
  return { w, h };
}
function fortschritt(saldo) {
  if (saldo <= START) return 0;
  return Math.min(100, (100 * Math.log(saldo / START)) / Math.log(ZIEL / START));
}
function klasse(bot) {
  if (bot.status === "Ziel erreicht") return "ziel";
  if (bot.status === "Pleite") return "leer";
  if (bot.saldo > START + 1e-9) return "plus";
  if (bot.saldo < START - 1e-9) return "minus";
  return "";
}
function dauer(s) {
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(x).padStart(2, "0")}`;
}
function toast(text) {
  const t = $("toast");
  t.textContent = text;
  t.classList.add("zeigen");
  clearTimeout(toast.t);
  toast.t = setTimeout(() => t.classList.remove("zeigen"), 2600);
}
async function steuern(aktion, bot = null, wert = null) {
  try {
    const r = await fetch("/api/steuerung", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ aktion, bot, wert }),
    });
    if (!r.ok) throw new Error((await r.json()).fehler || r.status);
    zustand.runde = 0;
    holen();
  } catch (e) {
    toast("Steuerung fehlgeschlagen: " + e.message);
  }
}

/* ---------------- Polling ---------------- */
let holenTimer = null;
async function holen() {
  clearTimeout(holenTimer);
  const mitVerlauf = zustand.runde % 4 === 0;
  try {
    const r = await fetch(`/api/zustand?seit=${zustand.seq}${mitVerlauf ? "&verlauf=1" : ""}`, { cache: "no-store" });
    const d = await r.json();
    if (mitVerlauf) zustand.verlauf = d.verlauf;
    if (d.rennen !== zustand.daten?.rennen) { $("log").textContent = ""; zustand.logZeilen = 0; }
    zustand.daten = d;
    zustand.seq = d.seq;
    zustand.runde++;
    if (zustand.fehler) { zustand.fehler = false; toast("Verbindung wieder da"); }
    zeichnen(d, mitVerlauf);
  } catch (e) {
    if (!zustand.fehler) toast("Server nicht erreichbar – läuft start.py noch?");
    zustand.fehler = true;
  }
  holenTimer = setTimeout(holen, 800);
}

function zeichnen(d, mitVerlauf) {
  kopf(d);
  kpis(d);
  raster(d);
  rangliste(d);
  profile(d);
  trades(d);
  logAnhaengen(d.ereignisse);
  donut(d);
  laufband(d);
  hud(d);
  verlaufChart();
  if (zustand.detailId !== null && zustand.runde % 2 === 0) detailLaden(zustand.detailId);
}

/* ---------------- Kopf und KPIs ---------------- */
function kopf(d) {
  $("tag-text").textContent = `Tag ${d.tag} · ${d.tag_text} · ${d.echt ? "echte Kurse" : "simuliert"}`;
  const out = $("tempo-wert");
  if (document.activeElement !== $("tempo")) {
    $("tempo").value = Math.round((Math.log10(d.tempo) / 3) * 100);
  }
  out.textContent = `${Math.round(d.tempo)}/s`;
}
function kpis(d) {
  const bots = d.bots;
  const best = bots.reduce((a, b) => (b.saldo > a.saldo ? b : a));
  const schlecht = bots.reduce((a, b) => (b.saldo < a.saldo ? b : a));
  const diff = (d.gesamt / d.start - 1) * 100;
  $("k-gesamt").textContent = eur.format(d.gesamt);
  $("k-gesamt-d").innerHTML = `<span class="${diff >= 0 ? "auf" : "ab"}">${diff >= 0 ? "↑" : "↓"} ${prozent(diff)}</span> seit Start (${eur.format(d.start)})`;
  $("k-bester").textContent = eur.format(best.saldo);
  $("k-bester-d").textContent = `Bot ${best.id} · ${best.aktie} · ${best.profil}`;
  $("k-schlecht").textContent = eur.format(schlecht.saldo);
  $("k-schlecht-d").textContent = `Bot ${schlecht.id} · ${schlecht.aktie} · ${schlecht.profil}`;
  $("k-ziel").textContent = `${d.ziel} / 25`;
  $("k-pleite").textContent = `${d.pleite} / 25`;
  $("k-zeit").textContent = dauer(d.laufzeit);
  $("k-offen").textContent = `${d.offen} offene Trades · Rennen ${d.rennen}`;
}

/* ---------------- Bot-Kacheln ---------------- */
function raster(d) {
  const r = $("raster");
  for (const bot of d.bots) {
    let k = zustand.kacheln[bot.id];
    if (!k) {
      k = document.createElement("article");
      k.className = "bot";
      k.innerHTML = `
        <div class="bot-kopf"><b>Bot ${bot.id}</b><span class="chip">${bot.aktie}</span></div>
        <div class="bot-regel">${bot.profil} · ${bot.regel}</div>
        <div class="bot-zahl"><span class="saldo"></span><span class="pz"></span></div>
        <svg class="spark" preserveAspectRatio="none"></svg>
        <div class="fortschritt"><i></i></div>
        <div class="bot-fuss"><span class="status"></span><span class="anz"></span>
          <span><button class="mini umschalten" title="Start/Pause"></button> <button class="mini mehr" title="Details">⤢</button></span></div>`;
      k.addEventListener("click", (e) => {
        if (e.target.closest(".umschalten")) return steuern("umschalten", bot.id);
        if (e.target.closest(".mehr")) return detailOeffnen(bot.id);
        waehlen(bot.id);
      });
      k.addEventListener("dblclick", () => detailOeffnen(bot.id));
      r.appendChild(k);
      zustand.kacheln[bot.id] = k;
    }
    k.className = `bot ${klasse(bot)}${zustand.gewaehlt === bot.id ? " gewaehlt" : ""}`;
    k.querySelector(".saldo").textContent = eur.format(bot.saldo);
    const pz = (bot.saldo / START - 1) * 100;
    const pzEl = k.querySelector(".pz");
    pzEl.textContent = prozent(pz);
    pzEl.className = "pz " + (pz >= 0 ? "auf" : "ab");
    k.querySelector(".fortschritt i").style.width = fortschritt(bot.saldo) + "%";
    const st = k.querySelector(".status");
    st.textContent = bot.status;
    st.className = "status " + bot.status.split(" ")[0];
    k.querySelector(".anz").innerHTML = `${bot.trades} Trades${bot.offen ? ' · <span class="offen-punkt">offen</span>' : ""}`;
    const knopf = k.querySelector(".umschalten");
    knopf.textContent = bot.modus === "Läuft" ? "❚❚" : "▶";
    knopf.disabled = bot.status === "Ziel erreicht" || bot.status === "Pleite";
    const v = zustand.verlauf[bot.id];
    if (v) spark(k.querySelector(".spark"), v, klasse(bot));
  }
}
function spark(svg, punkte, kl) {
  const { w, h } = leeren(svg);
  if (punkte.length < 2) return;
  const ys = punkte.map((p) => Math.log10(Math.max(p[1], 0.05)));
  const lo = Math.min(...ys, 1) - 0.02, hi = Math.max(...ys, 1) + 0.02;
  const x = (i) => (i / (punkte.length - 1)) * w;
  const y = (v) => h - ((v - lo) / (hi - lo)) * (h - 2) - 1;
  const d = ys.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
  const farbe = kl === "minus" ? "#ff5f5f" : kl === "leer" ? "#7d7a76" : kl === "ziel" ? "#ffd77a" : "#3ddc97";
  svg.appendChild(el("line", { x1: 0, x2: w, y1: y(1), y2: y(1), stroke: "rgba(255,255,255,.12)", "stroke-dasharray": "2 3" }));
  svg.appendChild(el("path", { d, fill: "none", stroke: farbe, "stroke-width": 1.4 }));
}
function waehlen(id) {
  zustand.gewaehlt = zustand.gewaehlt === id ? null : id;
  for (const [bid, k] of Object.entries(zustand.kacheln)) k.classList.toggle("gewaehlt", Number(bid) === zustand.gewaehlt);
  verlaufChart();
}

/* ---------------- Kontoverlauf (Bild 2) ---------------- */
function verlaufChart() {
  const svg = $("chart-verlauf");
  const { w, h } = leeren(svg);
  const d = zustand.daten;
  const serien = zustand.verlauf;
  if (!d || !serien || !Object.keys(serien).length) return;
  const pad = { l: 52, r: 12, t: 14, b: 26 };
  const ids = Object.keys(serien).map(Number);
  const maxTag = Math.max(1, ...ids.map((i) => serien[i].at(-1)[0]));
  const X = (t) => pad.l + (t / maxTag) * (w - pad.l - pad.r);
  const defs = el("defs");
  const grad = el("linearGradient", { id: "flaeche", x1: 0, x2: 0, y1: 0, y2: 1 });
  grad.appendChild(el("stop", { offset: "0%", "stop-color": "#ff8a3d", "stop-opacity": 0.55 }));
  grad.appendChild(el("stop", { offset: "100%", "stop-color": "#ff8a3d", "stop-opacity": 0 }));
  defs.appendChild(grad);
  const glow = el("filter", { id: "glow" });
  glow.appendChild(el("feGaussianBlur", { stdDeviation: 3, result: "b" }));
  const merge = el("feMerge");
  merge.appendChild(el("feMergeNode", { in: "b" }));
  merge.appendChild(el("feMergeNode", { in: "SourceGraphic" }));
  glow.appendChild(merge);
  defs.appendChild(glow);
  svg.appendChild(defs);

  let Y, ticks, werteGesamt;
  if (zustand.ansicht === "gesamt") {
    const laenge = serien[ids[0]].length;
    werteGesamt = Array.from({ length: laenge }, (_, i) => [serien[ids[0]][i][0], ids.reduce((s, id) => s + (serien[id][i]?.[1] || 0), 0)]);
    const max = Math.max(...werteGesamt.map((p) => p[1])) * 1.08, min = Math.min(...werteGesamt.map((p) => p[1])) * 0.92;
    Y = (v) => pad.t + (1 - (v - min) / (max - min || 1)) * (h - pad.t - pad.b);
    ticks = Array.from({ length: 5 }, (_, i) => min + ((max - min) * i) / 4);
  } else {
    const alle = ids.flatMap((i) => serien[i].map((p) => p[1]));
    const lo = Math.log10(Math.max(0.1, Math.min(...alle) * 0.8)), hi = Math.log10(1500);
    Y = (v) => pad.t + (1 - (Math.log10(Math.max(v, 0.1)) - lo) / (hi - lo)) * (h - pad.t - pad.b);
    ticks = [0.1, 1, 5, 10, 20, 50, 100, 500, 1000].filter((v) => Math.log10(v) >= lo - 0.01);
  }
  const achse = el("g", { class: "achse" });
  for (const t of ticks) {
    achse.appendChild(el("line", { x1: pad.l, x2: w - pad.r, y1: Y(t), y2: Y(t) }));
    achse.appendChild(el("text", { x: pad.l - 8, y: Y(t) + 4, "text-anchor": "end" }, t >= 100 ? Math.round(t) + " €" : zahl2.format(t).replace(",00", "") + " €"));
  }
  const tagSchritt = Math.max(1, Math.ceil(maxTag / 8));
  for (let t = 0; t <= maxTag; t += tagSchritt) achse.appendChild(el("text", { x: X(t), y: h - 6, "text-anchor": "middle" }, `Tag ${t}`));
  svg.appendChild(achse);

  const pfad = (pts) => pts.map((p, i) => `${i ? "L" : "M"}${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join("");
  if (zustand.ansicht === "gesamt") {
    const p = pfad(werteGesamt);
    svg.appendChild(el("path", { d: `${p}L${X(werteGesamt.at(-1)[0])},${h - pad.b}L${X(0)},${h - pad.b}Z`, fill: "url(#flaeche)" }));
    svg.appendChild(el("path", { d: p, fill: "none", stroke: "#ff9a4d", "stroke-width": 2.2, filter: "url(#glow)" }));
    $("v-wert").textContent = eur.format(d.gesamt);
    $("v-sub").textContent = `Summe aller 25 Wallets · Start ${eur.format(d.start)}`;
  } else {
    svg.appendChild(el("line", { class: "zielinie", x1: pad.l, x2: w - pad.r, y1: Y(1000), y2: Y(1000) }));
    svg.appendChild(el("line", { x1: pad.l, x2: w - pad.r, y1: Y(10), y2: Y(10), stroke: "rgba(255,255,255,.25)", "stroke-dasharray": "2 4" }));
    const botNach = Object.fromEntries(d.bots.map((b) => [b.id, b]));
    for (const id of ids) {
      if (id === zustand.gewaehlt) continue;
      const kl = klasse(botNach[id]);
      const farbe = kl === "minus" ? "#ff5f5f" : kl === "leer" ? "#7d7a76" : kl === "ziel" ? "#ffd77a" : "#3ddc97";
      svg.appendChild(el("path", { d: pfad(serien[id]), fill: "none", stroke: farbe, "stroke-width": 1, "stroke-opacity": zustand.gewaehlt ? 0.15 : 0.45 }));
    }
    const g = zustand.gewaehlt;
    if (g && serien[g]) {
      const p = pfad(serien[g]);
      svg.appendChild(el("path", { d: `${p}L${X(serien[g].at(-1)[0])},${h - pad.b}L${X(0)},${h - pad.b}Z`, fill: "url(#flaeche)", opacity: 0.8 }));
      svg.appendChild(el("path", { d: p, fill: "none", stroke: "#f4b740", "stroke-width": 2.6, filter: "url(#glow)" }));
      const b = botNach[g];
      $("v-wert").textContent = eur.format(b.saldo);
      $("v-sub").innerHTML = `Bot ${b.id} · ${b.aktie} · ${b.profil} (${b.regel}) · <span class="${b.saldo >= 10 ? "auf" : "ab"}">${prozent((b.saldo / 10 - 1) * 100)}</span>`;
    } else {
      const best = d.bots.reduce((a, b) => (b.saldo > a.saldo ? b : a));
      $("v-wert").textContent = eur.format(best.saldo);
      $("v-sub").textContent = `Bester Bot: ${best.id} (${best.aktie}, ${best.profil}) · Bot antippen zum Hervorheben`;
    }
  }
  tooltip(svg, { X, Y, w, h, pad, maxTag, serien: zustand.ansicht === "gesamt" ? werteGesamt : serien[zustand.gewaehlt] });
}
function tooltip(svg, o) {
  if (!o.serien || o.serien.length < 2) return;
  const g = el("g", { class: "tooltip-box", visibility: "hidden" });
  const linie = el("line", { y1: o.pad.t, y2: o.h - o.pad.b, stroke: "rgba(255,255,255,.35)", "stroke-dasharray": "3 3" });
  const kreis = el("circle", { r: 5, fill: "#fff", stroke: "#f4b740", "stroke-width": 3 });
  const box = el("rect", { rx: 8, width: 150, height: 40 });
  const t1 = el("text", {}), t2 = el("text", {});
  g.append(linie, box, t1, t2, kreis);
  svg.appendChild(g);
  const flaeche = el("rect", { x: o.pad.l, y: 0, width: o.w - o.pad.l - o.pad.r, height: o.h, fill: "transparent" });
  svg.appendChild(flaeche);
  const zeigen = (ev) => {
    const r = svg.getBoundingClientRect();
    const mx = ((ev.clientX - r.left) / r.width) * o.w;
    const tag = ((mx - o.pad.l) / (o.w - o.pad.l - o.pad.r)) * o.maxTag;
    let p = o.serien[0];
    for (const q of o.serien) if (Math.abs(q[0] - tag) < Math.abs(p[0] - tag)) p = q;
    const x = o.X(p[0]), y = o.Y(p[1]);
    linie.setAttribute("x1", x); linie.setAttribute("x2", x);
    kreis.setAttribute("cx", x); kreis.setAttribute("cy", y);
    const bx = Math.min(Math.max(x - 75, o.pad.l), o.w - 152), by = Math.max(2, y - 54);
    box.setAttribute("x", bx); box.setAttribute("y", by);
    t1.setAttribute("x", bx + 10); t1.setAttribute("y", by + 16); t1.textContent = `Tag ${p[0]}`;
    t2.setAttribute("x", bx + 10); t2.setAttribute("y", by + 32); t2.textContent = eur.format(p[1]);
    g.setAttribute("visibility", "visible");
  };
  flaeche.addEventListener("pointermove", zeigen);
  flaeche.addEventListener("pointerdown", zeigen);
  flaeche.addEventListener("pointerleave", () => g.setAttribute("visibility", "hidden"));
}

/* ---------------- Rangliste und Profile (Bild 1) ---------------- */
function rangliste(d) {
  const top = [...d.bots].sort((a, b) => b.saldo - a.saldo).slice(0, 5);
  const max = Math.max(...top.map((b) => b.saldo), START);
  $("rangliste").innerHTML = top.map((b, i) => `
    <li data-id="${b.id}"><span class="rang">${i + 1}</span>
      <span class="name">Bot ${b.id} · ${b.aktie} <small>${b.profil}</small></span>
      <span class="betrag ${b.saldo >= START ? "auf" : "ab"}">${eur.format(b.saldo)}</span>
      <span class="balken"><i style="width:${Math.max(3, fortschritt(b.saldo) || (b.saldo / max) * 30)}%"></i></span></li>`).join("");
  for (const li of $("rangliste").children) li.onclick = () => waehlen(Number(li.dataset.id));
}
function profile(d) {
  const svg = $("chart-profile");
  const { w, h } = leeren(svg);
  const werte = d.profile;
  const max = Math.max(...werte.map((p) => p.schnitt), START) * 1.1;
  const breite = (w - 10) / werte.length;
  const besterWert = Math.max(...werte.map((p) => p.schnitt));
  const defs = el("defs");
  for (const [id, a, b] of [["bg", "#4a3a26", "#1a1510"], ["bbest", "#3ddc97", "#0d3a26"]]) {
    const gr = el("linearGradient", { id, x1: 0, x2: 0, y1: 0, y2: 1 });
    gr.appendChild(el("stop", { offset: "0%", "stop-color": a }));
    gr.appendChild(el("stop", { offset: "100%", "stop-color": b, "stop-opacity": 0.4 }));
    defs.appendChild(gr);
  }
  svg.appendChild(defs);
  werte.forEach((p, i) => {
    const bh = Math.max(3, (p.schnitt / max) * (h - 34));
    const x = 5 + i * breite + breite * 0.14, bw = breite * 0.72, y = h - 18 - bh;
    const best = p.schnitt === besterWert;
    svg.appendChild(el("rect", { x, y, width: bw, height: bh, rx: 6, fill: best ? "url(#bbest)" : "url(#bg)" }));
    if (best) svg.appendChild(el("rect", { x, y, width: bw, height: 3, rx: 1.5, fill: "#3ddc97" }));
    svg.appendChild(el("text", { x: x + bw / 2, y: y - 4, "text-anchor": "middle", fill: best ? "#3ddc97" : "#a39b8f", "font-size": 11, "font-family": "monospace" }, zahl2.format(p.schnitt)));
    svg.appendChild(el("text", { x: x + bw / 2, y: h - 4, "text-anchor": "middle", fill: "#6d675f", "font-size": 11 }, p.name));
  });
}

/* ---------------- Trades, Log, Donut, Laufband ---------------- */
function trades(d) {
  const liste = [...d.trades].reverse();
  $("trade-liste").innerHTML = liste.length ? liste.map((t) => `
    <li><span class="avatar">${t.aktie.slice(0, 4)}</span>
      <span class="t1">Bot ${t.bot} · ${t.grund === "Ziel" ? "🏁 Ziel" : t.grund === "Stop" ? "🛑 Stop" : "⏰ 15:55"}</span>
      <span class="betrag ${t.ergebnis >= 0 ? "auf" : "ab"}">${t.ergebnis >= 0 ? "+" : "−"}${eur.format(Math.abs(t.ergebnis))}<br><small>${t.r >= 0 ? "+" : ""}${zahl2.format(t.r)} R</small></span>
      <span class="t2">${t.tag} · ${t.zeit}–${t.ende} · ${usd.format(t.einstieg)} → ${usd.format(t.ausstieg)}</span></li>`).join("")
    : `<li><span class="avatar">…</span><span class="t1">Noch keine Trades</span><span></span><span class="t2">Start drücken: die Bots warten auf den Ausbruch aus der Eröffnungsspanne.</span></li>`;
}
function logAnhaengen(ereignisse) {
  const log = $("log");
  if (!ereignisse.length) return;
  const unten = log.scrollHeight - log.scrollTop - log.clientHeight < 30;
  const frag = document.createDocumentFragment();
  for (const e of ereignisse.slice(-150)) {
    const z = document.createElement("div");
    z.className = e.art;
    z.innerHTML = `<span class="zeit">${e.zeit}</span>`;
    z.appendChild(document.createTextNode(e.text));
    frag.appendChild(z);
  }
  log.appendChild(frag);
  while (log.children.length > 300) log.removeChild(log.firstChild);
  zustand.logZeilen += ereignisse.length;
  $("log-zahl").textContent = `${zustand.logZeilen} Ereignisse`;
  if (unten) log.scrollTop = log.scrollHeight;
}
function donut(d) {
  const svg = $("chart-donut");
  while (svg.firstChild) svg.removeChild(svg.firstChild);
  const proAktie = {};
  for (const b of d.bots) proAktie[b.aktie] = (proAktie[b.aktie] || 0) + b.saldo;
  const teile = Object.entries(proAktie);
  const summe = teile.reduce((s, [, v]) => s + v, 0) || 1;
  let winkel = -Math.PI / 2;
  const R = 82, r = 56, cx = 100, cy = 100;
  teile.forEach(([sym, v], i) => {
    const a = (v / summe) * Math.PI * 2;
    const a2 = winkel + a - 0.03;
    const p = (rad, w) => `${cx + rad * Math.cos(w)},${cy + rad * Math.sin(w)}`;
    const gross = a > Math.PI ? 1 : 0;
    svg.appendChild(el("path", {
      d: `M${p(R, winkel)}A${R},${R} 0 ${gross} 1 ${p(R, a2)}L${p(r, a2)}A${r},${r} 0 ${gross} 0 ${p(r, winkel)}Z`,
      fill: AKTIEN_FARBEN[i % AKTIEN_FARBEN.length],
    }));
    winkel += a;
  });
  svg.appendChild(el("text", { x: 100, y: 98, "text-anchor": "middle", fill: "#f4efe7", "font-size": 19, "font-weight": 700 }, eur.format(summe)));
  svg.appendChild(el("text", { x: 100, y: 116, "text-anchor": "middle", fill: "#a39b8f", "font-size": 11 }, "Gesamtkapital"));
  $("donut-legende").innerHTML = teile.map(([sym, v], i) =>
    `<li><span><i style="background:${AKTIEN_FARBEN[i % AKTIEN_FARBEN.length]}"></i>${sym} · ${d.bots.filter((b) => b.aktie === sym).length} Bots</span><b>${eur.format(v)} (${zahl2.format((v / summe) * 100)} %)</b></li>`).join("");
}
function laufband(d) {
  $("laufband").innerHTML = d.aktien.map((a, i) =>
    `<span><i style="background:${AKTIEN_FARBEN[i]}"></i><b>${a.sym}</b> ${usd.format(a.kurs)} · ${a.echte_tage} echte Tage (${a.quelle})</span>`).join("")
    + `<span>Kerze ${d.uhr} NY · Tempo ${Math.round(d.tempo)}/s</span>`;
}

/* ---------------- HUD mit Weltkugel (Bild 3) ---------------- */
function hud(d) {
  $("hud-zeit").textContent = d.uhr;
  $("hud-tag").textContent = `${d.echt ? "echter" : "simulierter"} Tag ${d.tag} · ${d.tag_text}`;
  $("hud-quelle").textContent = d.echt ? "LIVE-REPLAY" : "TIME MACHINE";
  $("hud-fuss").innerHTML = `<span>OFFEN <b>${d.offen}</b></span><span>ZIEL <b>${d.ziel}</b></span><span>PLEITE <b>${d.pleite}</b></span>`
    + d.aktien.map((a) => `<span>${a.sym} <b>${usd.format(a.kurs)}</b></span>`).join("");
  globus.offen = d.offen;
}
const LAND = { // grobe Landmaske: Breitenband → Längenbereiche
  85: [[-70, -20]], 75: [[-125, -65], [-60, -20], [15, 30], [55, 140]],
  65: [[-165, -60], [-50, -25], [-24, -14], [5, 180]], 55: [[-165, -155], [-130, -60], [-8, -2], [5, 165]],
  45: [[-125, -65], [-5, 135], [140, 145]], 35: [[-120, -77], [-10, 40], [40, 120], [127, 140]],
  25: [[-112, -98], [-82, -80], [-15, 35], [38, 57], [68, 92], [100, 122]], 15: [[-92, -84], [-17, 42], [75, 80], [98, 108]],
  5: [[-77, -52], [-10, 45], [100, 118]], "-5": [[-80, -35], [10, 40], [105, 150]],
  "-15": [[-76, -40], [13, 40], [44, 50], [125, 145]], "-25": [[-70, -45], [15, 33], [114, 153]],
  "-35": [[-73, -57], [18, 22], [116, 150], [173, 178]], "-45": [[-74, -65], [167, 172]], "-55": [[-72, -66]],
  "-65": [[-180, 180]], "-75": [[-180, 180]], "-85": [[-180, 180]],
};
const globus = { punkte: [], offen: 0, rot: -60 };
for (let lat = -87.5; lat <= 87.5; lat += 2.5) {
  const band = Math.max(-85, Math.min(85, Math.round((lat - 5) / 10) * 10 + 5));
  const bereiche = LAND[band] || [];
  const schritt = 2.5 / Math.max(0.25, Math.cos((lat * Math.PI) / 180));
  for (let lon = -180; lon < 180; lon += schritt) {
    if (bereiche.some(([a, b]) => lon >= a && lon <= b)) globus.punkte.push([lat, lon]);
  }
}
function globusZeichnen(zeit) {
  const c = $("globus");
  const dpr = window.devicePixelRatio || 1;
  const w = c.clientWidth, h = c.clientHeight;
  if (c.width !== Math.round(w * dpr) || c.height !== Math.round(h * dpr)) { c.width = w * dpr; c.height = h * dpr; }
  const ctx = c.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  const R = Math.min(w, h) * 0.42, cx = w * 0.56, cy = h * 0.5;
  const lon0 = -74 + Math.sin(zeit / 9000) * 70, lat0 = 22;
  const rad = Math.PI / 180, sl0 = Math.sin(lat0 * rad), cl0 = Math.cos(lat0 * rad);
  const proj = (lat, lon) => {
    const la = lat * rad, lo = (lon - lon0) * rad;
    const cosc = sl0 * Math.sin(la) + cl0 * Math.cos(la) * Math.cos(lo);
    return [cx + R * Math.cos(la) * Math.sin(lo), cy - R * (cl0 * Math.sin(la) - sl0 * Math.cos(la) * Math.cos(lo)), cosc];
  };
  // Kugel mit Leuchten
  const g = ctx.createRadialGradient(cx - R * 0.35, cy - R * 0.4, R * 0.1, cx, cy, R * 1.05);
  g.addColorStop(0, "rgba(60,52,40,.9)"); g.addColorStop(0.7, "rgba(14,13,12,.95)"); g.addColorStop(1, "rgba(5,5,6,1)");
  ctx.fillStyle = g; ctx.beginPath(); ctx.arc(cx, cy, R, 0, 7); ctx.fill();
  ctx.strokeStyle = "rgba(244,183,64,.35)"; ctx.lineWidth = 1.2; ctx.shadowColor = "rgba(244,183,64,.6)"; ctx.shadowBlur = 18;
  ctx.beginPath(); ctx.arc(cx, cy, R, 0, 7); ctx.stroke(); ctx.shadowBlur = 0;
  // Gradnetz
  ctx.strokeStyle = "rgba(255,255,255,.10)"; ctx.lineWidth = 0.8;
  const linie = (fn) => { ctx.beginPath(); let an = false; for (let t = 0; t <= 360; t += 4) { const [x, y, z] = fn(t); if (z > 0) { an ? ctx.lineTo(x, y) : ctx.moveTo(x, y); an = true; } else an = false; } ctx.stroke(); };
  for (let la = -60; la <= 60; la += 30) linie((t) => proj(la, t - 180));
  for (let lo = -180; lo < 180; lo += 30) linie((t) => proj(t / 2 - 90, lo));
  // Kontinente als Punkte
  for (const [la, lo] of globus.punkte) {
    const [x, y, z] = proj(la, lo);
    if (z <= 0) continue;
    ctx.fillStyle = `rgba(235,225,210,${0.25 + z * 0.6})`;
    ctx.fillRect(x - 0.9, y - 0.9, 1.8, 1.8);
  }
  // Bogen Frankfurt → New York
  const ny = proj(40.7, -74), ff = proj(50.1, 8.7);
  if (ny[2] > 0 && ff[2] > 0) {
    ctx.strokeStyle = "rgba(255,138,61,.7)"; ctx.lineWidth = 1.2; ctx.setLineDash([4, 4]);
    ctx.beginPath(); ctx.moveTo(ff[0], ff[1]);
    ctx.quadraticCurveTo((ff[0] + ny[0]) / 2, Math.min(ff[1], ny[1]) - R * 0.35, ny[0], ny[1]); ctx.stroke(); ctx.setLineDash([]);
  }
  // NYSE: pulsierender Marker und Säulen je offenem Trade
  if (ny[2] > 0) {
    const puls = (zeit / 1200) % 1;
    ctx.strokeStyle = `rgba(244,183,64,${1 - puls})`; ctx.lineWidth = 1.5;
    ctx.beginPath(); ctx.arc(ny[0], ny[1], 4 + puls * 22, 0, 7); ctx.stroke();
    for (let i = 0; i < Math.max(globus.offen, 3); i++) {
      const hoch = i < globus.offen ? 22 + ((i * 37) % 40) : 8;
      const x = ny[0] + (i - 5) * 3.2;
      const gr = ctx.createLinearGradient(x, ny[1], x, ny[1] - hoch);
      gr.addColorStop(0, "rgba(255,138,61,.95)"); gr.addColorStop(1, "rgba(255,215,122,0)");
      ctx.fillStyle = gr; ctx.fillRect(x, ny[1] - hoch, 1.8, hoch);
    }
    ctx.fillStyle = "#ffd77a"; ctx.shadowColor = "#f4b740"; ctx.shadowBlur = 14;
    ctx.beginPath(); ctx.arc(ny[0], ny[1], 3.5, 0, 7); ctx.fill(); ctx.shadowBlur = 0;
    ctx.fillStyle = "#ffd77a"; ctx.font = "600 10px ui-monospace, monospace"; ctx.fillText("NYSE", ny[0] + 8, ny[1] + 14);
  }
  if (ff[2] > 0) { ctx.fillStyle = "#ff8a3d"; ctx.beginPath(); ctx.arc(ff[0], ff[1], 2.6, 0, 7); ctx.fill(); }
  // Außenring mit Teilstrichen
  ctx.strokeStyle = "rgba(255,255,255,.18)"; ctx.lineWidth = 1;
  for (let i = 0; i < 72; i++) {
    const a = (i / 72) * Math.PI * 2 + zeit / 20000, l = i % 6 ? 4 : 9;
    ctx.beginPath(); ctx.moveTo(cx + Math.cos(a) * (R + 10), cy + Math.sin(a) * (R + 10));
    ctx.lineTo(cx + Math.cos(a) * (R + 10 + l), cy + Math.sin(a) * (R + 10 + l)); ctx.stroke();
  }
}
let letzterFrame = 0;
function schleife(t) {
  if (!document.hidden && t - letzterFrame > 33) { globusZeichnen(t); letzterFrame = t; }
  requestAnimationFrame(schleife);
}

/* ---------------- Detailansicht ---------------- */
async function detailOeffnen(id) {
  zustand.detailId = id;
  const dlg = $("detail");
  if (!dlg.open) dlg.showModal();
  await detailLaden(id);
}
async function detailLaden(id) {
  try {
    const d = await (await fetch(`/api/bot/${id}`, { cache: "no-store" })).json();
    if (zustand.detailId !== id) return;
    $("d-titel").textContent = `Bot ${d.id} · ${d.aktie}`;
    $("d-sub").textContent = `${d.wallet} · ${d.profil} (${d.profil_kurz}) · Daten: ${d.quelle}`;
    $("d-umschalten").textContent = d.modus === "Läuft" ? "❚❚ Pause" : "▶ Start";
    $("d-umschalten").disabled = d.status === "Ziel erreicht" || d.status === "Pleite";
    $("d-umschalten").onclick = () => steuern("umschalten", d.id).then(() => detailLaden(d.id));
    const gew = d.trades.filter((t) => t.ergebnis > 0).length;
    const zahlen = [
      ["Kontostand", eur.format(d.saldo)], ["seit Start", prozent((d.saldo / 10 - 1) * 100)],
      ["Status", d.status], ["Trades", `${d.trades.length} (${gew} im Plus)`],
      ["bis 1.000 €", zahl2.format(fortschritt(d.saldo)) + " %"],
    ];
    $("d-zahlen").innerHTML = zahlen.map(([a, b]) => `<div><small>${a}</small><b>${b}</b></div>`).join("");
    $("d-kerzen-titel").textContent = `${d.tag_text} · ${d.echt ? "echte Kerzen" : "simuliert"} · Eröffnungsspanne, Einstieg, Stop, Ziel`;
    kerzenChart(d);
    kontoChart(d);
    $("d-trades").innerHTML = [...d.trades].reverse().map((t) => `<tr>
      <td>${t.tag}</td><td>${t.zeit}–${t.ende}</td><td>${t.aktie}</td><td class="zahl">${zahl2.format(t.menge)}</td>
      <td class="zahl">${usd.format(t.einstieg)}</td><td class="zahl">${usd.format(t.ausstieg)}</td><td>${t.grund}</td>
      <td class="zahl ${t.r >= 0 ? "auf" : "ab"}">${zahl2.format(t.r)}</td>
      <td class="zahl ${t.ergebnis >= 0 ? "auf" : "ab"}">${t.ergebnis >= 0 ? "+" : "−"}${eur.format(Math.abs(t.ergebnis))}</td></tr>`).join("")
      || `<tr><td colspan="9">Noch keine abgeschlossenen Trades.</td></tr>`;
  } catch (e) { /* nächster Versuch beim nächsten Takt */ }
}
function kerzenChart(d) {
  const svg = $("d-kerzen");
  const { w, h } = leeren(svg);
  const k = d.kerzen;
  if (!k.length) { svg.appendChild(el("text", { x: w / 2, y: h / 2, "text-anchor": "middle", fill: "#6d675f" }, "Markt öffnet um 9:30 New York")); return; }
  const heute = d.trades.filter((t) => t.tag === d.tag_text);
  const pos = d.position || heute.at(-1);
  const preise = k.flatMap((b) => [b.h, b.l]);
  if (pos) preise.push(pos.stop, pos.ziel);
  const lo = Math.min(...preise) * 0.999, hi = Math.max(...preise) * 1.001;
  const pad = { l: 8, r: 76, t: 8, b: 18 };
  const X = (i) => pad.l + ((i + 0.5) / 78) * (w - pad.l - pad.r);
  const Y = (v) => pad.t + (1 - (v - lo) / (hi - lo)) * (h - pad.t - pad.b);
  const bw = Math.max(1.5, ((w - pad.l - pad.r) / 78) * 0.65);
  if (d.spanne) {
    const n = { Früh: 1, Geduld: 6 }[d.profil] || 3;
    svg.appendChild(el("rect", { x: X(0) - bw, y: Y(d.spanne[0]), width: X(n - 1) - X(0) + 2 * bw, height: Y(d.spanne[1]) - Y(d.spanne[0]), fill: "rgba(244,183,64,.12)", stroke: "rgba(244,183,64,.5)" }));
    svg.appendChild(el("line", { x1: X(0), x2: w - pad.r, y1: Y(d.spanne[0]), y2: Y(d.spanne[0]), stroke: "rgba(244,183,64,.35)", "stroke-dasharray": "2 3" }));
  }
  k.forEach((b, i) => {
    const auf = b.c >= b.o, farbe = auf ? "#3ddc97" : "#ff5f5f";
    svg.appendChild(el("line", { x1: X(i), x2: X(i), y1: Y(b.h), y2: Y(b.l), stroke: farbe }));
    svg.appendChild(el("rect", { x: X(i) - bw / 2, y: Y(Math.max(b.o, b.c)), width: bw, height: Math.max(1, Math.abs(Y(b.o) - Y(b.c))), fill: farbe }));
  });
  if (pos) {
    for (const [wert, farbe, text] of [[pos.ziel, "#3ddc97", "Ziel"], [pos.einstieg, "#ffd77a", "Einstieg"], [pos.stop, "#ff5f5f", "Stop"]]) {
      svg.appendChild(el("line", { x1: pad.l, x2: w - pad.r, y1: Y(wert), y2: Y(wert), stroke: farbe, "stroke-dasharray": "5 4" }));
      svg.appendChild(el("text", { x: w - pad.r + 4, y: Y(wert) + 4, fill: farbe, "font-size": 10, "font-family": "monospace" }, `${text} ${wert.toFixed(2)}`));
    }
  }
  svg.appendChild(el("text", { x: pad.l, y: h - 4, fill: "#6d675f", "font-size": 10 }, "9:30"));
  svg.appendChild(el("text", { x: w - pad.r, y: h - 4, fill: "#6d675f", "font-size": 10, "text-anchor": "end" }, "16:00"));
}
function kontoChart(d) {
  const svg = $("d-konto");
  const { w, h } = leeren(svg);
  const v = d.verlauf;
  if (v.length < 2) return;
  const pad = { l: 46, r: 8, t: 10, b: 18 };
  const maxT = v.at(-1)[0] || 1;
  const werte = v.map((p) => p[1]);
  const lo = Math.min(...werte, 10) * 0.95, hi = Math.max(...werte, 10) * 1.05;
  const X = (t) => pad.l + (t / maxT) * (w - pad.l - pad.r);
  const Y = (x) => pad.t + (1 - (x - lo) / (hi - lo)) * (h - pad.t - pad.b);
  const defs = el("defs");
  const gr = el("linearGradient", { id: "dflaeche", x1: 0, x2: 0, y1: 0, y2: 1 });
  gr.appendChild(el("stop", { offset: "0%", "stop-color": "#f4b740", "stop-opacity": 0.45 }));
  gr.appendChild(el("stop", { offset: "100%", "stop-color": "#f4b740", "stop-opacity": 0 }));
  defs.appendChild(gr); svg.appendChild(defs);
  const p = v.map((q, i) => `${i ? "L" : "M"}${X(q[0])},${Y(q[1])}`).join("");
  svg.appendChild(el("line", { x1: pad.l, x2: w - pad.r, y1: Y(10), y2: Y(10), stroke: "rgba(255,255,255,.25)", "stroke-dasharray": "2 4" }));
  svg.appendChild(el("path", { d: `${p}L${X(maxT)},${h - pad.b}L${X(0)},${h - pad.b}Z`, fill: "url(#dflaeche)" }));
  svg.appendChild(el("path", { d: p, fill: "none", stroke: "#f4b740", "stroke-width": 2 }));
  for (const t of [lo, (lo + hi) / 2, hi]) svg.appendChild(el("text", { x: pad.l - 6, y: Y(t) + 4, "text-anchor": "end", fill: "#6d675f", "font-size": 10, "font-family": "monospace" }, zahl2.format(t)));
  svg.appendChild(el("text", { x: w - pad.r, y: h - 4, "text-anchor": "end", fill: "#6d675f", "font-size": 10 }, `Tag ${maxT}`));
}

/* ---------------- Ereignisse der Bedienelemente ---------------- */
document.querySelectorAll(".steuerung .knopf").forEach((b) => b.addEventListener("click", () => {
  const a = b.dataset.aktion;
  if (a === "reset") {
    // zweimal tippen statt confirm(): eingebettete Browser (Pythonista, Pyto) zeigen keine Dialoge
    if (!b.dataset.scharf) {
      b.dataset.scharf = "1";
      toast("Nochmal auf Reset tippen: alle Bots zurück auf 10 €");
      setTimeout(() => delete b.dataset.scharf, 3000);
      return;
    }
    delete b.dataset.scharf;
  }
  steuern(a);
}));
$("tempo").addEventListener("input", (e) => { $("tempo-wert").textContent = `${Math.round(10 ** ((e.target.value / 100) * 3))}/s`; });
$("tempo").addEventListener("change", (e) => steuern("tempo", null, Math.round(10 ** ((e.target.value / 100) * 3))));
$("v-tabs").addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  zustand.ansicht = b.dataset.ansicht;
  for (const x of $("v-tabs").children) x.classList.toggle("an", x === b);
  verlaufChart();
});
$("d-zu").addEventListener("click", () => $("detail").close());
$("detail").addEventListener("close", () => { zustand.detailId = null; });
$("detail").addEventListener("click", (e) => { if (e.target === $("detail")) $("detail").close(); });
window.addEventListener("resize", () => { clearTimeout(window.rz); window.rz = setTimeout(() => zustand.daten && zeichnen(zustand.daten, true), 150); });
document.querySelectorAll(".seitenleiste nav a").forEach((a) => a.addEventListener("click", () => {
  document.querySelectorAll(".seitenleiste nav a").forEach((x) => x.classList.toggle("aktiv", x === a));
}));

holen();
requestAnimationFrame(schleife);
'''


DATEIEN = {
    "index.html": ("text/html", INDEX_HTML),
    "app.css": ("text/css", APP_CSS),
    "app.js": ("application/javascript", APP_JS),
}


# =====================================================================================
# Teil 6 – Start und Anzeige (Pythonista, Pyto, sonst Browser)
# =====================================================================================

def freier_server(rennen, host, port):
    for p in [port] + list(range(port + 1, port + 20)) + [0]:
        try:
            return starten(rennen, host, p)
        except OSError:
            continue
    raise SystemExit("kein freier Port gefunden")


def in_app_anzeigen(url):
    """Zeigt das Dashboard in der App. True = Fenster wurde wieder geschlossen, False = keine App-Ansicht."""
    try:
        import ui  # Pythonista
    except ImportError:
        ui = None
    if ui is not None:
        ansicht = ui.WebView(name="Day-Trader-Rennen")
        ansicht.background_color = "#060608"
        ansicht.load_url(url)
        ansicht.present("fullscreen")
        ansicht.wait_modal()
        return True
    try:
        import pyto_ui  # Pyto
    except ImportError:
        pyto_ui = None
    if pyto_ui is not None:
        ansicht = pyto_ui.WebView()
        ansicht.load_url(url)
        pyto_ui.show_view(ansicht, pyto_ui.PRESENTATION_MODE_FULLSCREEN)  # kehrt beim Schließen zurück
        return True
    return False


def text_stand(rennen, seit):
    """Rennstand als Text für die Ausgabe der App. Gibt die neue Ereignisnummer zurück."""
    s = rennen.schnappschuss(seit)
    rang = sorted(s["bots"], key=lambda b: b["saldo"], reverse=True)
    def euro(x):
        return f"{x:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")
    zeilen = ["", "─" * 44,
              f"Tag {s['tag']} ({s['tag_text']}, {'echt' if s['echt'] else 'simuliert'}) · {s['uhr']} New York",
              f"Gesamt {euro(s['gesamt'])} von {euro(s['start'])} · Ziel {s['ziel']}/25 · Pleite {s['pleite']}/25"
              f" · offen {s['offen']}"]
    for i, b in enumerate(rang[:5], 1):
        zeilen.append(f"  {i}. Bot {b['id']:2} {b['aktie']:5} {b['profil']:9} {euro(b['saldo']):>12}  {b['trades']} Trades")
    letzte = rang[-1]
    zeilen.append(f"  … Letzter: Bot {letzte['id']} {letzte['aktie']} {letzte['profil']} {euro(letzte['saldo'])}")
    wichtig = [e for e in s["ereignisse"] if e["art"] in ("verkauf", "ziel", "pleite", "info")]
    for e in wichtig[-4:]:
        zeilen.append(f"  {e['zeit']}  {e['text']}")
    print("\n".join(zeilen), flush=True)
    return s["seq"]


def lan_adresse():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))
            return s.getsockname()[0]
    except OSError:
        return None


def main():
    p = argparse.ArgumentParser(description="Day-Trader-Rennen: 25 Bots × 10 € → 1.000 €")
    p.add_argument("--aktien", default=",".join(STANDARD_AKTIEN))
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--offline", action="store_true")
    p.add_argument("--tempo", type=float, default=40)
    p.add_argument("--kein-browser", action="store_true")
    p.add_argument("--wlan", action="store_true", help="auch für andere Geräte im WLAN erreichbar")
    p.add_argument("--textintervall", type=float, default=5, help="Sekunden zwischen Textmeldungen")
    a, _ = p.parse_known_args()  # Pythonista und Pyto übergeben manchmal eigene Argumente

    aktien = [s.strip().upper() for s in a.aktien.split(",") if s.strip()]
    if len(aktien) != 5:
        raise SystemExit("--aktien braucht genau 5 Ticker")
    print("Lade 60 Tage Fünf-Minuten-Kerzen …")
    maerkte = []
    for sym in aktien:
        tage, quelle, daten_sym = sitzungen(sym, offline=a.offline)
        print(f"  {sym if daten_sym == sym else sym + '→' + daten_sym:10} {len(tage):3} Handelstage ({quelle})")
        maerkte.append(Markt(daten_sym, tage, quelle))

    rennen = Rennen(maerkte)
    rennen.steuern("tempo", wert=a.tempo)
    rennen.starten_thread()
    rennen.steuern("start")

    srv = None
    try:
        srv = freier_server(rennen, "0.0.0.0" if a.wlan else "127.0.0.1", a.port)
    except (OSError, SystemExit) as fehler:
        print(f"Webserver nicht möglich ({fehler}): zeige das Rennen nur als Text.")
    url = None
    if srv:
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True, name="Webserver").start()
        url = f"http://127.0.0.1:{port}/"
        print(f"\nDashboard: {url}")
        if a.wlan and lan_adresse():
            print(f"Im WLAN:   http://{lan_adresse()}:{port}/")
    try:
        if url and not a.kein_browser and in_app_anzeigen(url):
            return
        if url and not a.kein_browser:
            try:
                webbrowser.open(url)
            except Exception:
                pass
            print("Falls sich kein Browser öffnet: Adresse oben in Safari öffnen. Der Stand kommt auch hier als Text.")
        print("Beenden mit dem Stopp-Knopf der App (oder Strg+C).")
        seit = 0
        while True:
            seit = text_stand(rennen, seit)
            time.sleep(a.textintervall)
    except KeyboardInterrupt:
        pass
    finally:
        rennen.beenden()
        if srv:
            srv.shutdown()
            srv.server_close()
        print("Beendet.")


if __name__ == "__main__":
    main()
