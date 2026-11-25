/* Day-Trader-Rennen – Engine im Browser.
 *
 * Läuft komplett in der Seite: Nach dem Laden braucht sie keinen Server mehr. Das ist auf dem
 * iPad wichtig, weil iOS die Python-App im Hintergrund anhält.
 *
 * Handelsregeln aus day-trader-skill (MIT), wie die Time Machine (trader-timemachine/timemachine.py):
 *   opening_range, rule_stop (mit cents_away), Einstieg beim ersten Schluss über dem Spannen-Hoch,
 *   Stop zuerst, dann Ziel, glatt um 15:55, ein Trade pro Tag, nur Kauf.
 *   Simulierte Tage nach Art von build_pool: jede Kerze aus den echten Kerzen derselben Tageszeit.
 *
 * Echtgeld-Simulation: Je Broker werden Gebühren, Spread/Slippage, Ausführung zum nächsten
 * Eröffnungskurs, Kurslücken über Stop/Ziel, Wechselkurs EUR/USD und ganze bzw. Bruchstück-Aktien
 * nachgebildet. „Ohne Kosten“ rechnet exakt wie die Time Machine (Test: gleiche Trades wie
 * history_replay).
 */
"use strict";
(function (global) {
  const SESSION_BARS = 78, OPEN_MIN = 9 * 60 + 30;
  const FLAT_SLOT = (15 * 60 + 55 - OPEN_MIN) / 5 - 1;      // 76: Kerze 15:50–15:55 (trader-exit flat_by)
  const LETZTER_EINSTIEG = (15 * 60 + 30 - OPEN_MIN) / 5;    // 72: keine Einstiege nach 15:30 (trader-entry)
  const START_EUR = 10, ZIEL_EUR = 1000, LEER_EUR = 0.10, MAX_PUNKTE = 600;

  const PROFILE = [
    { name: "Lehrbuch", kurz: "OR15 · Mitte · 2R", or_minutes: 15, stop_rule: "or_mid", target_r: 2 },
    { name: "Reel", kurz: "OR15 · Mitte · 1R", or_minutes: 15, stop_rule: "or_mid", target_r: 1 },
    { name: "Früh", kurz: "OR5 · Tief · 3R", or_minutes: 5, stop_rule: "or_low", target_r: 3 },
    { name: "Geduld", kurz: "OR30 · Mitte · 2R", or_minutes: 30, stop_rule: "or_mid", target_r: 2 },
    { name: "Eng", kurz: "OR15 · 0,5 % · 4R", or_minutes: 15, stop_rule: "pct", stop_pct: 0.5, target_r: 4 },
  ];

  /* Broker-Modelle. Gebührensätze sind Näherungen (Stand 2026), keine Zusage des Brokers. */
  const BROKER = {
    alpaca: {
      name: "Alpaca (USA)", kurz: "Bruchstück-Aktien · 0 $ Provision · Konto in USD",
      konto: "USD", bruch: true, provisionUSD: 0, slippage: 0.0005, fxGebuehr: 0.005,
      secSatz: 0.0000278, tafProAktie: 0.000195, tafMax: 9.79, mindestUSD: 1,
      naechsterOpen: true, luecken: true,
      text: "Einzahlung von 10 € wird einmal in Dollar getauscht (0,5 % Wechselgebühr). Market-Orders füllen zum nächsten Eröffnungskurs plus 0,05 % Slippage, Stop-Orders bei einer Lücke zum Eröffnungskurs. Beim Verkauf fallen SEC- und FINRA-Gebühren an. Mindestorder 1 $.",
    },
    neobroker: {
      name: "Neobroker DE", kurz: "nur ganze Aktien · 1 € pro Order · Konto in EUR",
      konto: "EUR", bruch: false, provisionEUR: 1, slippage: 0.0005, spread: 0.001,
      naechsterOpen: true, luecken: true,
      text: "Wie Trade Republic oder Scalable: 1 € Fremdkostenpauschale pro Order, Handel in Euro mit 0,1 % Spread, Einzelorders nur in ganzen Aktien. Mit 10 € reicht es meist für keine einzige Aktie.",
    },
    ideal: {
      name: "Ohne Kosten", kurz: "Time-Machine-Rechnung · Bruchstücke · keine Gebühren",
      konto: "USD", bruch: true, provisionUSD: 0, slippage: 0, fxGebuehr: 0,
      secSatz: 0, tafProAktie: 0, tafMax: 0, mindestUSD: 0, naechsterOpen: false, luecken: false,
      text: "Rechnet wie die Time Machine von day-trader-skill: Einstieg zum Schlusskurs, Stop und Ziel genau zum Preis, keine Gebühren. Zum Vergleich, kein Echtgeld.",
    },
  };

  /* ---------- Hilfen (wie Python) ---------- */
  function rundeCent(x) { return Number(x.toFixed(2)); }                       // round(x, 2)
  function centsAwayLong(x) { return Math.floor(Number((x * 100).toFixed(4))) / 100; }  // cents_away(x, True)
  function uhr(slot) { const m = OPEN_MIN + 5 * slot; return `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`; }
  function hash(text) { let h = 2166136261; for (let i = 0; i < text.length; i++) { h ^= text.charCodeAt(i); h = Math.imul(h, 16777619); } return h >>> 0; }
  function zufall(seed) {   // mulberry32
    let a = seed >>> 0;
    return function () { a = (a + 0x6D2B79F5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
  }
  function openingRange(kerzen, n) {
    let hoch = -Infinity, tief = Infinity;
    for (let i = 0; i < n; i++) { hoch = Math.max(hoch, kerzen[i].h); tief = Math.min(tief, kerzen[i].l); }
    return [hoch, tief];
  }
  function ruleStop(regel, oh, ol, entry) {
    if (regel.stop_rule === "or_mid") return centsAwayLong((oh + ol) / 2);
    if (regel.stop_rule === "or_low") return centsAwayLong(ol);
    return centsAwayLong(entry * (1 - regel.stop_pct / 100));
  }
  function euroText(x, vz) {
    const t = Math.abs(x).toLocaleString("de-DE", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + " €";
    return vz ? (x >= 0 ? "+" : "−") + t : t;
  }
  function usdText(x) { return "$" + x.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }

  /* ---------- Markt: echte Tage, danach simulierte ---------- */
  class Markt {
    constructor(daten, fx) {
      this.sym = daten.sym;
      this.quelle = daten.quelle;
      this.echt = daten.tage.map(([datum, k]) => [datum, k.map((b, i) => ({ slot: i, o: b[0], h: b[1], l: b[2], c: b[3] }))]);
      if (!this.echt.length) throw new Error(this.sym + ": keine Handelstage");
      this.fx = fx;
      this.pool = Array.from({ length: SESSION_BARS }, () => []);
      for (const [, k] of this.echt) for (let i = 1; i < SESSION_BARS; i++) {
        const pc = k[i - 1].c;
        this.pool[i].push([k[i].o / pc, k[i].h / pc, k[i].l / pc, k[i].c / pc]);
      }
      this.luecken = [];
      for (let j = 1; j < this.echt.length; j++) {
        const pc = this.echt[j - 1][1][SESSION_BARS - 1].c, b = this.echt[j][1][0];
        this.luecken.push([b.o / pc, b.h / pc, b.l / pc, b.c / pc]);
      }
      if (!this.luecken.length) this.luecken.push([1, 1, 1, 1]);
      this.sim = new Map();
    }
    tag(index) {
      if (index < this.echt.length) {
        const [datum, k] = this.echt[index];
        return { text: datum, echt: true, kerzen: k, fx: this.fx.kurs(datum) };
      }
      if (!this.sim.has(index)) {
        const vortag = this.tag(index - 1).kerzen;
        const rnd = zufall(hash(`${this.sym}-${index}`));
        let preis = vortag[SESSION_BARS - 1].c;
        const k = [];
        for (let i = 0; i < SESSION_BARS; i++) {
          const quelle = i === 0 ? this.luecken : this.pool[i];
          const [o, h, l, c] = quelle[Math.floor(rnd() * quelle.length)];
          k.push({ slot: i, o: preis * o, h: preis * h, l: preis * l, c: preis * c });
          preis *= c;
        }
        for (const alt of this.sim.keys()) if (alt < index - 1) this.sim.delete(alt);
        this.sim.set(index, k);
      }
      return { text: `Sim-Tag ${index - this.echt.length + 1}`, echt: false, kerzen: this.sim.get(index), fx: this.fx.letzter };
    }
  }

  class Wechselkurs {
    constructor(fx) {
      this.quelle = fx.quelle;
      this.tage = Object.keys(fx.kurse).sort();
      this.kurse = fx.kurse;
      this.letzter = this.tage.length ? this.kurse[this.tage[this.tage.length - 1]] : fx.annahme;
      this.annahme = fx.annahme;
    }
    kurs(datum) {   // letzter bekannter Kurs bis zu diesem Datum (USD je EUR)
      let r = null;
      for (const t of this.tage) { if (t <= datum) r = this.kurse[t]; else break; }
      return r || (this.tage.length ? this.kurse[this.tage[0]] : this.annahme);
    }
  }

  /* ---------- Bot ---------- */
  class Bot {
    constructor(id, markt, profil, broker, rnd, fxStart) {
      this.id = id; this.markt = markt; this.profil = profil; this.broker = broker;
      this.regel = profil;
      this.wallet = "W-" + Math.floor(rnd() * 0xffffffff).toString(16).toUpperCase().padStart(8, "0");
      this.zuruecksetzen(fxStart);
    }
    zuruecksetzen(fxStart) {
      const b = this.broker;
      this.bargeld = b.konto === "USD" ? START_EUR * fxStart * (1 - b.fxGebuehr) : START_EUR;
      this.kostenEUR = b.konto === "USD" ? START_EUR * b.fxGebuehr : 0;   // Wechselgebühr der Einzahlung
      this.position = null; this.wartend = null;
      this.trades = []; this.status = null; this.modus = "Gestoppt";
      this.wert = this.bargeld / (b.konto === "USD" ? fxStart : 1);
      this.verlauf = [[0, START_EUR]];
      this.gehandelt = false; this.spanne = null; this.zuWenig = false;
    }
    neuerTag() { this.gehandelt = false; this.spanne = null; this.zuWenig = false; }

    /* Preis in Kontowährung (USD-Kurs → EUR beim Neobroker) */
    inKonto(usd, fx) { return this.broker.konto === "EUR" ? usd / fx : usd; }

    kerze(k, tag, ereig) {
      if (this.status) return;
      const b = tag.kerzen[k], br = this.broker, fx = tag.fx;
      const n = this.regel.or_minutes / 5;
      // 1) wartende Market-Order zum Eröffnungskurs dieser Kerze ausführen
      if (this.wartend) { this.ausfuehren(this.wartend, b.o, k, tag, ereig); this.wartend = null; }
      // 2) offene Position: Stop zuerst, dann Ziel, dann 15:55
      if (this.position) {
        const p = this.position;
        if (b.l <= p.stop || (br.luecken && b.o <= p.stop)) {
          const fuell = br.luecken && b.o < p.stop ? b.o : p.stop;
          this.schliessen(fuell, true, br.luecken && b.o < p.stop ? "Stop (Lücke)" : "Stop", k, tag, ereig);
        } else if (b.h >= p.ziel) {
          const fuell = br.luecken && b.o > p.ziel ? b.o : p.ziel;   // Limit: mindestens das Ziel
          this.schliessen(fuell, false, "Ziel", k, tag, ereig);
        } else if (k >= FLAT_SLOT) {
          this.schliessen(b.c, true, "15:55", k, tag, ereig);
        }
      } else if (this.modus === "Läuft" && !this.gehandelt && !this.wartend && k >= n && k <= this.letzterEinstieg) {
        // 3) Einstiegssignal: Schluss über dem Hoch der Eröffnungsspanne
        if (!this.spanne) this.spanne = openingRange(tag.kerzen, n);
        const [oh, ol] = this.spanne;
        if (b.c > oh) {
          this.gehandelt = true;
          const e = rundeCent(b.c);
          const stop = ruleStop(this.regel, oh, ol, e);
          const risiko = e - stop;
          if (risiko > 0) {
            const plan = { einstieg: e, stop, ziel: rundeCent(e + this.regel.target_r * risiko), signal: uhr(k + 1), spanne: [oh, ol] };
            if (br.naechsterOpen && k + 1 < SESSION_BARS) this.wartend = plan;     // Order nach Kerzenschluss → nächster Open
            else this.ausfuehren(plan, e, k, tag, ereig);                          // wie die Time Machine: zum Schluss, gerundet
          }
        }
      }
      // 4) Bewertung in Euro
      const kurs = b.c;
      const wertKonto = this.bargeld + (this.position ? this.position.anteile * this.inKonto(kurs, fx) * (br.konto === "EUR" ? (1 - br.spread / 2) : 1) : 0);
      this.wert = br.konto === "USD" ? wertKonto / fx : wertKonto;
      if (!this.position && !this.wartend) {
        const minimum = br.konto === "USD" ? Math.max(br.mindestUSD, LEER_EUR * fx) : LEER_EUR;
        if (this.bargeld < minimum - 1e-12 && this.trades.length) {
          this.status = "Pleite";
          ereig.push(["pleite", this.id, `💀 Bot ${this.id} ist pleite (${euroText(this.wert)} übrig).`]);
        }
      }
    }

    ausfuehren(plan, preisUSD, k, tag, ereig) {
      const br = this.broker, fx = tag.fx;
      let fuell, anteile, kosten = 0;
      if (br.konto === "USD") {
        fuell = preisUSD * (1 + br.slippage);
        if (this.bargeld < br.mindestUSD || this.bargeld <= 0) return;
        anteile = this.bargeld / fuell;
        kosten = this.bargeld - anteile * preisUSD;   // Slippage-Kosten in USD
        this.bargeld = 0;
      } else {
        fuell = this.inKonto(preisUSD, fx) * (1 + br.spread / 2 + br.slippage);
        anteile = Math.floor((this.bargeld - br.provisionEUR) / fuell);
        if (anteile < 1) {
          if (!this.zuWenig) ereig.push(["info", this.id, `Bot ${this.id}: Signal ${this.markt.sym} zu ${usdText(preisUSD)}, aber ${euroText(this.bargeld)} reichen nicht für 1 Aktie + 1 € Gebühr`]);
          this.zuWenig = true;
          return;
        }
        kosten = br.provisionEUR + anteile * (fuell - this.inKonto(preisUSD, fx));
        this.bargeld -= anteile * fuell + br.provisionEUR;
      }
      this.kostenEUR += br.konto === "USD" ? kosten / fx : kosten;
      this.position = Object.assign({}, plan, { anteile, fuell, fuellUSD: br.konto === "USD" ? fuell : fuell * fx, einsatz: br.konto === "USD" ? anteile * fuell : anteile * fuell + br.provisionEUR, zeit: uhr(k + (br.naechsterOpen ? 0 : 1)), tag: tag.text, fxStart: fx });
      ereig.push(["kauf", this.id, `Bot ${this.id} kauft ${anteile.toLocaleString("de-DE", { maximumFractionDigits: 4 })} ${this.markt.sym} zu ${usdText(br.konto === "USD" ? fuell : fuell * fx)} (Stop ${usdText(plan.stop)}, Ziel ${usdText(plan.ziel)})`]);
    }

    schliessen(preisUSD, market, grund, k, tag, ereig) {
      const br = this.broker, fx = tag.fx, p = this.position;
      let erloes, kosten = 0, fuellUSD;
      if (br.konto === "USD") {
        fuellUSD = market ? preisUSD * (1 - br.slippage) : preisUSD;
        const brutto = p.anteile * fuellUSD;
        const sec = brutto * br.secSatz, taf = Math.min(p.anteile * br.tafProAktie, br.tafMax);
        erloes = brutto - sec - taf;
        kosten = (market ? p.anteile * (preisUSD - fuellUSD) : 0) + sec + taf;
      } else {
        const fuell = this.inKonto(preisUSD, fx) * (1 - br.spread / 2 - (market ? br.slippage : 0));
        fuellUSD = fuell * fx;
        erloes = p.anteile * fuell - br.provisionEUR;
        kosten = br.provisionEUR + p.anteile * (this.inKonto(preisUSD, fx) - fuell);
      }
      this.kostenEUR += br.konto === "USD" ? kosten / fx : kosten;
      const ergebnisKonto = erloes - p.einsatz;
      const ergebnisEUR = br.konto === "USD" ? erloes / fx - p.einsatz / p.fxStart : ergebnisKonto;
      const r = (fuellUSD - p.fuellUSD) / (p.einstieg - p.stop);
      this.bargeld += erloes;
      this.position = null;
      this.trades.push({
        nr: Bot.nr++, tag: tag.text, zeit: p.zeit, ende: uhr(k + 1), aktie: this.markt.sym, menge: p.anteile,
        plan: p.einstieg, einstieg: p.fuellUSD, stop: p.stop, ziel: p.ziel, ausstieg: fuellUSD, grund,
        r: Math.round(r * 100) / 100, ergebnis: ergebnisEUR, kosten: kosten / (br.konto === "USD" ? fx : 1),
      });
      const zeichen = grund === "Ziel" ? "🏁" : grund.startsWith("Stop") ? "🛑" : "⏰";
      ereig.push(["verkauf", this.id, `${zeichen} Bot ${this.id} verkauft ${this.markt.sym} zu ${usdText(fuellUSD)} (${grund}, ${r >= 0 ? "+" : ""}${r.toFixed(2)} R, ${euroText(ergebnisEUR, true)})`]);
      const wertEUR = br.konto === "USD" ? this.bargeld / fx : this.bargeld;
      if (wertEUR >= ZIEL_EUR) {
        this.status = "Ziel erreicht";
        ereig.push(["ziel", this.id, `🏆 Bot ${this.id} hat 1.000 € erreicht!`]);
      }
    }

    tagEnde(t) {
      this.verlauf.push([t + 1, Math.round(this.wert * 10000) / 10000]);
      if (this.verlauf.length > MAX_PUNKTE) {
        const v = this.verlauf;
        this.verlauf = [v[0]].concat(v.slice(1, -1).filter((_, i) => i % 2 === 0), [v[v.length - 1]]);
      }
    }
    anzeigeStatus() { return this.status || this.modus; }
    kompakt() {
      return { id: this.id, wallet: this.wallet, aktie: this.markt.sym, profil: this.profil.name, regel: this.profil.kurz,
        saldo: this.wert, status: this.anzeigeStatus(), modus: this.modus, trades: this.trades.length,
        offen: !!(this.position || this.wartend), gewinner: this.trades.filter((t) => t.ergebnis > 0).length, kosten: this.kostenEUR };
    }
  }
  Bot.nr = 1;

  /* ---------- Rennen ---------- */
  class Rennen {
    constructor(daten, brokerSchluessel, optionen = {}) {
      this.daten = daten;
      this.brokerSchluessel = brokerSchluessel in BROKER ? brokerSchluessel : "alpaca";
      this.broker = BROKER[this.brokerSchluessel];
      this.fx = new Wechselkurs(daten.fx);
      this.maerkte = daten.aktien.map((a) => new Markt(a, this.fx));
      this.letzterEinstieg = optionen.letzterEinstieg || LETZTER_EINSTIEG;
      this.tempo = 40; this.rennenNr = 1; this.ereignisse = []; this.seq = 0;
      const rnd = zufall(7);
      this.bots = [];
      const fxStart = this.maerkte[0].tag(0).fx;
      this.maerkte.forEach((m, i) => PROFILE.forEach((p, j) => this.bots.push(new Bot(i * PROFILE.length + j + 1, m, p, this.broker, rnd, fxStart))));
      for (const b of this.bots) b.letzterEinstieg = this.letzterEinstieg;
      this.neu();
    }
    neu() { this.tagIndex = 0; this.slot = 0; this.laufzeit = 0; this.seit = null; }

    steuern(aktion, botId = null, wert = null) {
      const ziele = this.bots.filter((b) => botId === null || b.id === botId);
      if (aktion === "start" || aktion === "pause" || aktion === "stop") {
        const modus = { start: "Läuft", pause: "Pausiert", stop: "Gestoppt" }[aktion];
        for (const b of ziele) b.modus = modus;
        this.log("info", null, `${botId === null ? "Alle Bots" : "Bot " + botId}: ${modus}`);
      } else if (aktion === "umschalten") {
        for (const b of ziele) b.modus = b.modus === "Läuft" ? "Pausiert" : "Läuft";
      } else if (aktion === "reset") {
        const fxStart = this.maerkte[0].tag(0).fx;
        for (const b of this.bots) b.zuruecksetzen(fxStart);
        this.neu(); this.rennenNr++;
        this.log("info", null, `Neues Rennen Nr. ${this.rennenNr}: alle Wallets wieder 10 €`);
      } else if (aktion === "tempo") {
        this.tempo = Math.max(1, Math.min(2000, Number(wert)));
      } else {
        throw new Error("unbekannte Aktion " + aktion);
      }
      this.uhr();
    }
    aktiv() { return this.bots.some((b) => (b.modus === "Läuft" && !b.status) || b.position || b.wartend); }
    uhr() {
      const an = this.bots.some((b) => b.modus === "Läuft" && !b.status);
      if (an && this.seit === null) this.seit = Date.now();
      else if (!an && this.seit !== null) { this.laufzeit += (Date.now() - this.seit) / 1000; this.seit = null; }
    }
    uhrzeitText() { return `${this.maerkte[0].tag(this.tagIndex).text} ${uhr(this.slot + 1)}`; }

    schritt() {
      const neu = [], zeit = this.uhrzeitText();
      const tage = new Map(this.maerkte.map((m) => [m.sym, m.tag(this.tagIndex)]));
      for (const b of this.bots) b.kerze(this.slot, tage.get(b.markt.sym), neu);
      this.slot++;
      if (this.slot > FLAT_SLOT) {
        for (const b of this.bots) { b.tagEnde(this.tagIndex); b.neuerTag(); }
        this.tagIndex++; this.slot = 0;
      }
      for (const [art, id, text] of neu) this.log(art, id, text, zeit);
    }
    log(art, bot, text, zeit) {
      this.seq++;
      this.ereignisse.push({ seq: this.seq, art, bot, text, zeit: zeit || this.uhrzeitText() });
      if (this.ereignisse.length > 400) this.ereignisse.splice(0, this.ereignisse.length - 400);
    }
    laufzeitS() { return this.laufzeit + (this.seit ? (Date.now() - this.seit) / 1000 : 0); }

    schnappschuss(seitSeq = 0, mitVerlauf = false) {
      const tag = this.maerkte[0].tag(this.tagIndex);
      const bots = this.bots.map((b) => b.kompakt());
      const profile = PROFILE.map((p) => {
        const w = this.bots.filter((b) => b.profil === p).map((b) => b.wert);
        return { name: p.name, kurz: p.kurz, schnitt: w.reduce((s, x) => s + x, 0) / w.length };
      });
      const slot = Math.min(this.slot, SESSION_BARS - 1);
      const s = {
        rennen: this.rennenNr, tag: this.tagIndex + 1, tag_text: tag.text, echt: tag.echt,
        uhr: uhr(slot), slot: this.slot, laufzeit: Math.round(this.laufzeitS()), tempo: this.tempo,
        gesamt: bots.reduce((x, b) => x + b.saldo, 0), start: START_EUR * bots.length,
        kosten: bots.reduce((x, b) => x + b.kosten, 0),
        ziel: this.bots.filter((b) => b.status === "Ziel erreicht").length,
        pleite: this.bots.filter((b) => b.status === "Pleite").length,
        offen: this.bots.filter((b) => b.position || b.wartend).length,
        broker: Object.assign({ schluessel: this.brokerSchluessel }, this.broker),
        fx: { kurs: tag.fx, quelle: this.fx.quelle },
        aktien: this.maerkte.map((m) => ({ sym: m.sym, quelle: m.quelle, echte_tage: m.echt.length, kurs: m.tag(this.tagIndex).kerzen[slot].c })),
        profile, bots,
        trades: this.bots.flatMap((b) => b.trades.slice(-3).map((t) => Object.assign({ bot: b.id }, t))).sort((a, b) => a.nr - b.nr).slice(-8),
        ereignisse: this.ereignisse.filter((e) => e.seq > seitSeq), seq: this.seq,
      };
      if (mitVerlauf) {
        s.verlauf = {};
        for (const b of this.bots) s.verlauf[b.id] = duenn(b.verlauf, 240);
      }
      return s;
    }
    details(id) {
      const b = this.bots.find((x) => x.id === id);
      const tag = b.markt.tag(this.tagIndex);
      return Object.assign(b.kompakt(), {
        profil_kurz: b.profil.kurz, quelle: b.markt.quelle, tag_text: tag.text, echt: tag.echt,
        kerzen: tag.kerzen.slice(0, Math.min(this.slot, SESSION_BARS)), or_n: b.regel.or_minutes / 5,
        position: b.position || b.wartend, spanne: b.spanne, trades: b.trades.slice(-200), verlauf: duenn(b.verlauf, 400),
        broker: this.broker.name,
      });
    }
  }
  function duenn(p, n) {
    if (p.length <= n) return p;
    const s = (p.length - 1) / (n - 1);
    return Array.from({ length: n }, (_, i) => p[Math.round(i * s)]);
  }

  const DTR = { Rennen, BROKER, PROFILE, SESSION_BARS, FLAT_SLOT, LETZTER_EINSTIEG, START_EUR, ZIEL_EUR, openingRange, ruleStop };
  if (typeof module !== "undefined" && module.exports) module.exports = DTR;
  global.DTR = DTR;
})(typeof window !== "undefined" ? window : globalThis);
