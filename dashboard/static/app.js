/* Day-Trader-Rennen – Oberfläche. Liest den Rennstand per Polling von /api/zustand. */
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
  if (a === "reset" && !confirm("Alle 25 Bots auf 10 € zurücksetzen und ein neues Rennen starten?")) return;
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
