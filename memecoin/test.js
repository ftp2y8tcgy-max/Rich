// Tests der Memecoin-Engine (läuft unter Node, ohne Netz): node memecoin/test.js
"use strict";
const fs = require("fs");
const path = require("path");
const assert = require("assert");
const html = fs.readFileSync(path.join(__dirname, "index.html"), "utf8");
const MB = new Function("module", html.match(/<script id="engine">([\s\S]*?)<\/script>/)[1] + "\nreturn globalThis.MB;")({});

const T0 = Date.UTC(2026, 10, 25, 12);
function paar(adr, o) {
  o = Object.assign({ preis: 0.001, liq: 60000, mcap: 400000, alterMin: 90, m5: 8, h1: 20, kaeufe: 150, verkaeufe: 60, vol5: 30000, dex: "raydium" }, o);
  return { chainId: "solana", dexId: o.dex, url: "https://dexscreener.com/solana/" + adr, baseToken: { address: adr, symbol: adr.toUpperCase(), name: adr },
    priceUsd: String(o.preis), liquidity: { usd: o.liq }, marketCap: o.mcap, pairCreatedAt: o.jetzt - o.alterMin * 60000,
    priceChange: { m5: o.m5, h1: o.h1 }, txns: { m5: { buys: o.kaeufe, sells: o.verkaeufe } }, volume: { m5: o.vol5 } };
}
function welt(coins, rug) {
  // coins: {adr: (jetzt, schritt) => optionen oder null (Paar fehlt)}
  const w = { jetzt: T0, schritt: 0, rugAnfragen: 0 };
  w.api = {
    profile: async () => Object.keys(coins).map((a) => ({ chainId: "solana", tokenAddress: a })),
    boosts: async () => [],
    tokens: async (adr) => adr.map((a) => { const o = coins[a] && coins[a](w.jetzt, w.schritt); return o ? paar(a, Object.assign({ jetzt: w.jetzt }, o)) : null; }).filter(Boolean),
    rug: async (a) => { w.rugAnfragen++; return rug[a] || { score_normalised: 1, risks: [], lpLockedPct: 100 }; },
    sol: async () => 100,
  };
  return w;
}
async function laufen(z, w, schritte) {
  for (let i = 0; i < schritte; i++) { w.jetzt += 10001; w.schritt++; await MB.takt(z, w.api, w.jetzt); }
}
const trades = (z) => z.agenten.flatMap((a) => a.trades);
const agent = (z, id) => z.agenten[MB.AGENTEN.findIndex((a) => a.id === id)];

const tests = {
  async "kauft nur, was Regeln und Rug-Check besteht"() {
    const w = welt({ gut: () => ({}), rug: () => ({}), schwach: () => ({ m5: 1 }), kurve: () => ({ liq: 0, dex: "pumpfun", alterMin: 20, mcap: 60000 }) },
      { rug: { score_normalised: 45, risks: [{ name: "Creator history of rugged tokens", level: "danger" }], lpLockedPct: 100 } });
    const z = MB.neuerZustand(); z.laeuft = true;
    await laufen(z, w, 1);
    const gekauft = (id) => agent(z, id).positionen.map((p) => p.adr).sort();
    assert.deepStrictEqual(gekauft("vorsicht"), ["gut"]);
    assert.deepStrictEqual(gekauft("momentum"), ["gut"]);
    assert.deepStrictEqual(gekauft("frueh"), []);                    // 90 min alt: zu alt für „Früh“
    assert.deepStrictEqual(gekauft("curve"), ["gut", "kurve"]);      // nur Curve kauft auf der pump.fun-Kurve
    assert.ok(z.log.some((l) => l.art === "skip" && l.text.includes("Creator history of rugged tokens")));
    assert.ok(!z.log.some((l) => l.text.includes("kauft $SCHWACH")));
  },

  async "Kosten: Kauf und sofortiger Verkauf zum gleichen Kurs verliert Geld"() {
    const w = welt({ gut: () => ({}) }, {});
    const z = MB.neuerZustand(); z.laeuft = true;
    await laufen(z, w, 1);
    const a = agent(z, "vorsicht"), pos = a.positionen[0];
    assert.ok(pos.kaufPreis > 0.001 * 1.01, "Kauf teurer als Signal (Latenz + Preiseinfluss)");
    MB.verkaufen(z, a, MB.AGENTEN[0], pos, 1, z.coins.gut, "Test", w.jetzt);
    const t = a.trades[0];
    // $3.13 Einsatz: 2 × 0,25 % DEX + 2 × 1 % Verzögerung + 2 × $0.05 Netzwerk (≈ 3,2 %) ≈ −5,7 %
    assert.ok(t.ergebnis < 0 && t.pz < -0.04 && t.pz > -0.08, "Verlust " + t.pz);
    assert.ok(Math.abs(t.kosten + t.ergebnis) < 1e-9, "Verlust = Kosten");
  },

  async "Gewinnmitnahme zur Hälfte, dann Trailing-Stop"() {
    const kurs = (j, s) => ({ preis: s <= 1 ? 0.001 : s <= 3 ? 0.0018 : s === 4 ? 0.0024 : 0.0018 });
    const w = welt({ gut: kurs }, {});
    const z = MB.neuerZustand(); z.laeuft = true;
    await laufen(z, w, 6);
    const t = agent(z, "vorsicht").trades[0];
    assert.ok(z.log.some((l) => l.text.includes("verkauft 50 % von $GUT – Gewinnmitnahme")));
    assert.ok(t && t.grund.startsWith("Trailing-Stop"), t && t.grund);
    assert.ok(t.ergebnis > 0);
  },

  async "Stop bei −25 %"() {
    const w = welt({ gut: (j, s) => ({ preis: s <= 1 ? 0.001 : 0.00074 }) }, {});
    const z = MB.neuerZustand(); z.laeuft = true;
    await laufen(z, w, 2);
    assert.strictEqual(agent(z, "vorsicht").trades[0].grund, "Stop -25 %");
  },

  async "Rug: Liquidität abgezogen und Paar verschwunden"() {
    const w = welt({ a: (j, s) => ({ liq: s <= 1 ? 60000 : 5000 }), b: (j, s) => (s <= 1 ? {} : null) }, {});
    const z = MB.neuerZustand(); z.laeuft = true;
    await laufen(z, w, 5);
    const gruende = trades(z).map((t) => t.adr + ":" + t.grund);
    assert.ok(gruende.includes("a:Rug: Liquidität abgezogen"), gruende);
    assert.ok(gruende.some((g) => g.startsWith("b:Paar verschwunden")), gruende);
    assert.ok(trades(z).filter((t) => t.adr === "b").every((t) => t.pz < -0.6));
  },

  async "Zeit-Stop nach 45 Minuten ohne Bewegung"() {
    const w = welt({ gut: () => ({}) }, {});
    const z = MB.neuerZustand(); z.laeuft = true;
    await laufen(z, w, 1);
    w.jetzt += 46 * 60000;
    await laufen(z, w, 1);
    assert.ok(agent(z, "vorsicht").trades[0].grund.startsWith("Zeit-Stop"));
  },

  async "Bilanz: ohne Trades genau das Startkapital, höchstens 3 Positionen je Agent"() {
    const z0 = MB.neuerZustand({ start: 50 });
    assert.strictEqual(MB.bilanz(z0).wert, 50);
    const coins = {}; for (let i = 0; i < 8; i++) coins["c" + i] = () => ({});
    const w = welt(coins, {});
    const z = MB.neuerZustand(); z.laeuft = true;
    await laufen(z, w, 1);
    for (const a of z.agenten) assert.ok(a.positionen.length <= 3);
    const b = MB.bilanz(z);
    assert.ok(b.wert < 50 && b.wert > 45, "Wert nach Kaufkosten " + b.wert);
    assert.ok(w.rugAnfragen <= 4, "höchstens 4 Rug-Checks pro Takt");
  },

  async "kauft denselben Coin nicht zweimal hintereinander"() {
    const w = welt({ gut: (j, s) => ({ preis: s === 2 ? 0.0007 : 0.001 }) }, {});
    const z = MB.neuerZustand(); z.laeuft = true;
    await laufen(z, w, 6);
    assert.strictEqual(agent(z, "vorsicht").trades.length, 1);
    assert.strictEqual(agent(z, "vorsicht").positionen.length, 0);
  },
};

(async () => {
  let fehler = 0;
  for (const [name, fn] of Object.entries(tests)) {
    try { await fn(); console.log("ok  ", name); } catch (e) { fehler++; console.log("FEHLER", name, "\n  ", e.message); }
  }
  console.log(fehler ? `${fehler} Fehler` : "alle Tests bestanden");
  process.exit(fehler ? 1 : 0);
})();
