// Hilfsskript für die Python-Tests: spielt ein Rennen mit engine.js durch und gibt die Trades als JSON aus.
// Aufruf: node lauf.js <daten.json> <broker> <schritte> [letzterEinstieg]
const fs = require("fs");
const path = require("path");
const DTR = require(path.join(__dirname, "..", "static", "engine.js"));
const [daten, broker, schritte, letzter] = process.argv.slice(2);
const r = new DTR.Rennen(JSON.parse(fs.readFileSync(daten, "utf8")), broker, letzter ? { letzterEinstieg: Number(letzter) } : {});
r.steuern("start");
for (let i = 0; i < Number(schritte); i++) r.schritt();
const s = r.schnappschuss(0);
process.stdout.write(JSON.stringify({
  bots: r.bots.map((b) => ({ id: b.id, profil: b.profil.name, regel: b.regel, wert: b.wert, status: b.status, kosten: b.kostenEUR, trades: b.trades })),
  ereignisse: s.ereignisse.map((e) => e.text), gesamt: s.gesamt, kosten: s.kosten,
}));
