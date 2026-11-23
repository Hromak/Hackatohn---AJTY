// Voice command -> shot fields. Deterministic and offline: no AI model, no API key in the browser.
// "domácí gól 90 asistence 98 čas 5:38" -> { team: 'home', result: 'goal', shooter: 90, assist: 98, time: '05:38' }
// Players are jersey numbers here; the app maps them to roster ids and flags unknown numbers.

const UNITS = { nula: 0, jedna: 1, jeden: 1, jedno: 1, dva: 2, dve: 2, tri: 3, ctyri: 4, pet: 5, sest: 6, sedm: 7, osm: 8, devet: 9,
  deset: 10, jedenact: 11, dvanact: 12, trinact: 13, ctrnact: 14, patnact: 15, sestnact: 16, sedmnact: 17, osmnact: 18, devatenact: 19 };
const TENS = { dvacet: 20, tricet: 30, ctyricet: 40, padesat: 50, sedesat: 60, sedmdesat: 70, osmdesat: 80, devadesat: 90 };

const norm = (s) => String(s).toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '')
  .replace(/[,;!?"„“]/g, ' ').split(/\s+/).map((t) => (/^\d+\.\d{2}$/.test(t) ? t : t.replace(/\.$/, ''))).filter(Boolean);

export function wordsToNumbers(text) {
  const t = norm(text);
  const out = [];
  for (let i = 0; i < t.length; i++) {
    const back = t[i].match(/^(jedn|dva|tri|ctyri|pet|sest|sedm|osm|devet)a([a-z]+)$/); // "jednadevadesát", "dvaadvacet"
    if (back && TENS[back[2]]) out.push(String(TENS[back[2]] + (back[1] === 'jedn' ? 1 : UNITS[back[1]])));
    else if (TENS[t[i]] != null) {
      const u = UNITS[t[i + 1]];
      if (u != null && u > 0 && u < 10) { out.push(String(TENS[t[i]] + u)); i++; } else out.push(String(TENS[t[i]]));
    } else out.push(UNITS[t[i]] != null ? String(UNITS[t[i]]) : t[i]);
  }
  return out.join(' ');
}

const isNum = (t) => /^\d{1,2}$/.test(t ?? '');
const TIME = /^(\d{1,2})[:.](\d{2})$/;
const fmt = (m, s) => (Number(s) < 60 ? `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}` : null);

// ctx.names: { home: ['Draci'], away: ['Vlci'] } – team short names the scorer may say instead of domácí/hosté
export function parseCommand(text, ctx = { names: { home: [], away: [] } }) {
  const t = wordsToNumbers(text).split(' ');
  const used = new Set();
  const r = { team: null, result: null, shooter: null, assist: null, noAssist: false, time: null, strength: null };
  const found = new Set();
  const words = (side) => (ctx.names?.[side] ?? []).flatMap((n) => norm(n)).filter((w) => w.length >= 3);
  const shared = new Set(words('home').filter((w) => words('away').includes(w))); // e.g. "florbal" in both names
  const names = { home: words('home').filter((w) => !shared.has(w)), away: words('away').filter((w) => !shared.has(w)) };
  const nextNum = (i) => { let j = i + 1; if (t[j] === 'cislo') j++; return isNum(t[j]) ? j : -1; };

  for (let i = 0; i < t.length; i++) {
    const w = t[i];
    const tm = w.match(TIME);
    if (tm && !used.has(i)) { r.time = fmt(tm[1], tm[2]); used.add(i); continue; }
    if (w.startsWith('cas')) {
      const n = t[i + 1];
      const tm2 = n?.match(TIME);
      if (tm2) { r.time = fmt(tm2[1], tm2[2]); used.add(i + 1); continue; }
      if (isNum(n)) {
        let j = i + 2;
        if (t[j]?.startsWith('min')) j++;
        const sec = isNum(t[j]) ? t[j] : '0';
        r.time = fmt(n, sec);
        used.add(i + 1); if (isNum(t[j])) used.add(j);
      }
      continue;
    }
    if (w.startsWith('asist') || w.startsWith('nahra') || w.startsWith('prihr')) {
      if (t[i - 1] === 'bez') { r.noAssist = true; continue; }
      const j = nextNum(i);
      if (j >= 0) { r.assist = Number(t[j]); used.add(j); }
      continue;
    }
    if (w.startsWith('domac')) r.team = 'home';
    else if (w.startsWith('host')) r.team = 'away';
    else for (const side of ['home', 'away']) if (names[side].some((n) => w === n || (n.length >= 4 && w.startsWith(n.slice(0, 4))))) r.team = side;
    if (w.startsWith('gol')) found.add('goal');
    if (w === 'mimo' || w === 'vedle') found.add('miss');
    if (w.startsWith('tyc') || w.startsWith('brevn')) found.add('post');
    if (w.startsWith('chyt') || w.startsWith('zakrok') || w.startsWith('zasah') || (t[i - 1] === 'na' && w.startsWith('bran'))) found.add('on_goal');
    if (w.startsWith('presilov')) r.strength = 'power_play';
    if (w.startsWith('oslab')) r.strength = 'short_handed';
    if (w.startsWith('vyrovn')) r.strength = 'even';
  }
  r.result = ['goal', 'post', 'miss', 'on_goal'].find((k) => found.has(k)) ?? null;
  const shooterAt = t.findIndex((w, i) => isNum(w) && !used.has(i));
  if (shooterAt >= 0) r.shooter = Number(t[shooterAt]);
  return r;
}
