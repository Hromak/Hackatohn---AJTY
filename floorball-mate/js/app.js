import { createApi } from './api.js';
import { filterShots, summarize, SLOT_M, filterLog, timeOnIce, shiftPlusMinus, playerPlusMinus } from './stats.js';
import { parseCommand } from './voice.js';
import { Outbox } from './queue.js';
import { suggest, replacementsFor } from './predict.js';
import { RINK, seconds, lineupAt, shotBody, subBody, mergeEvents, sortEvents, nextTime, teamSituation, stepTime, orderLineup, SLOT_LABEL, SLOTS, initLines, assignSlot, linePlayers } from './model.js';

const $app = document.getElementById('app');
const $dlg = document.getElementById('dlg');
const $toast = document.getElementById('toast');
const store = {
  get: (k, d) => { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } },
  set: (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* full or blocked */ } },
};
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
const SIDE = { home: 'Domácí', away: 'Hosté' };
const RESULT = { miss: 'Mimo', on_goal: 'Na branku', post: 'Tyčka', goal: 'Gól' };
const STRENGTH = { even: 'Vyrovnaný stav', power_play: 'Přesilovka', short_handed: 'Oslabení' };
const other = (t) => (t === 'home' ? 'away' : 'home');
// one line-icon set (lucide shapes): same stroke everywhere, colour from the surrounding text
const icon = (d, size = 20) => `<svg class="ic" viewBox="0 0 24 24" width="${size}" height="${size}" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="${d}"/></svg>`;
const I = {
  down: 'm6 9 6 6 6-6',
  up: 'm18 15-6-6-6 6',
  swap: 'M8 3 4 7l4 4M4 7h16M16 21l4-4-4-4M20 17H4',
  undo: 'M19 12H5M12 19l-7-7 7-7',
  x: 'M18 6 6 18M6 6l12 12',
  plus: 'M12 5v14M5 12h14',
  lock: 'M5 11h14a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2ZM7 11V7a5 5 0 0 1 10 0v4',
  unlock: 'M5 11h14a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2ZM7 11V7a5 5 0 0 1 9.9-1',
  mic: 'M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3ZM19 10v2a7 7 0 0 1-14 0v-2M12 19v3',
  full: 'M8 3H5a2 2 0 0 0-2 2v3M21 8V5a2 2 0 0 0-2-2h-3M3 16v3a2 2 0 0 0 2 2h3M16 21h3a2 2 0 0 0 2-2v-3',
  unfull: 'M8 3v3a2 2 0 0 1-2 2H3M21 8h-3a2 2 0 0 1-2-2V3M3 16h3a2 2 0 0 1 2 2v3M16 21v-3a2 2 0 0 1 2-2h3',
};

const api = createApi({ token: () => store.get('fm.token', 'demo') });
const outbox = new Outbox({ send: api.send });
let S = null; // current match state

// ---------- sending ----------
let pumpTimer = null;
async function pump() {
  clearTimeout(pumpTimer);
  const { waitMs } = await outbox.flush();
  if (waitMs) pumpTimer = setTimeout(pump, waitMs);
  else if (S) refreshEvents();
}
outbox.onchange = () => S && render();
addEventListener('online', pump);
setInterval(() => outbox.pending().length && pump(), 15000);

async function refreshEvents() {
  try {
    const r = await api.get(`/matches/${S.id}/events`);
    S.server = r.events;
    store.set(`fm.events.${S.id}`, S.server);
    // the server now has everything that was confirmed; keep only what is still open
    outbox.items = outbox.items.filter((i) => i.match_id !== S.id || i.status !== 'done');
    outbox.save();
  } catch { /* offline: keep the cached copy */ }
}

// ---------- match list ----------
async function showList() {
  S = null;
  $app.innerHTML = `<div class="list"><h1>Floorball Mate</h1><p class="muted">Načítám utkání…</p></div>`;
  let matches = store.get('fm.matches', []);
  let msg = '';
  try { matches = (await api.get('/me')).matches; store.set('fm.matches', matches); }
  catch (e) { msg = `<p class="err">${esc(e.status === 401 ? 'Neplatný token' : 'Bez spojení – ukazuji uložený seznam')}</p>`; }
  $app.innerHTML = `<div class="list">
    <h1>Floorball Mate</h1>
    <div class="row"><label>Token týmu <input id="token" value="${esc(store.get('fm.token', 'demo'))}" autocomplete="off"></label>
      <button id="saveToken">Uložit</button></div>
    ${msg}
    ${matches.map((m) => `<button data-id="${m.id}"><b>${esc(m.home)} – ${esc(m.away)}</b><span class="muted">${esc(m.date)}</span></button>`).join('')}
  </div>`;
  $app.querySelector('#saveToken').onclick = () => { store.set('fm.token', $app.querySelector('#token').value.trim()); showList(); };
  $app.querySelectorAll('[data-id]').forEach((b) => (b.onclick = () => openMatch(Number(b.dataset.id))));
}

// ---------- open match ----------
async function openMatch(id) {
  $app.innerHTML = `<div class="list"><p class="muted">Načítám utkání…</p></div>`;
  let data = store.get(`fm.match.${id}`, null);
  try {
    // one after another: the API allows only 4 requests in flight per team
    const header = await api.get(`/matches/${id}`);
    const roster = await api.get(`/matches/${id}/roster`);
    const formations = await api.get(`/matches/${id}/formations`);
    data = { header, roster, formations };
    store.set(`fm.match.${id}`, data);
  } catch (e) {
    if (!data) { $app.innerHTML = `<div class="list"><p class="err">${esc(e.message)}</p><button id="back">Zpět</button></div>`; $app.querySelector('#back').onclick = showList; return; }
  }
  const saved = store.get(`fm.state.${id}`, {});
  S = {
    id, ...data,
    server: store.get(`fm.events.${id}`, []),
    players: new Map([...data.roster.home, ...data.roster.away].map((p) => [p.id, p])),
    period: saved.period ?? 1,
    view: saved.view ?? 'shots',
    situation: saved.situation ?? 'even',
    flipped: saved.flipped ?? false,
    goalie: saved.goalie ?? { home: firstGoalie(data.roster.home), away: firstGoalie(data.roster.away) },
    locked: saved.locked ?? [], // periods closed for shot entry (lock button next to the time)
    mic: saved.mic ?? false, // voice mode: a tap on the rink starts listening
    timeOverride: null, // what the scorer typed; null = last recorded time + 5 s
    // prepared lines: start from the coach presets, edits stay on this tablet (the API cannot store them)
    lines: store.get(`fm.lines.${id}`, null) ?? { home: initLines(data.formations.home), away: initLines(data.formations.away) },
    edit: null, // line editor: { team, sel: player id | null }
    nsub: null, // new substitution being built: { team, players, goalie, sel: { side: 'new' | 'pool', id } }
    gk: store.get(`fm.gk.${id}`, {}), // goalie chosen with each substitution, client_id -> player id | null (empty net)
    more: { home: false, away: false }, // "Zobrazit další střídání"
    af: { periods: [], team: null, strengths: [], results: [], players: [] }, // Analýza filter, same rules as Zápis
    lf: { periods: [], kinds: [], team: null }, // Zápis filter: lists = several at once (empty = all), team = one or both
  };
  await refreshEvents();
  render();
  pump();
}
const firstGoalie = (list) => list.find((p) => p.position === 'G')?.id ?? null;
const saveLines = () => store.set(`fm.lines.${S.id}`, S.lines);
const saveUi = () => store.set(`fm.state.${S.id}`, { period: S.period, view: S.view, situation: S.situation, flipped: S.flipped, goalie: S.goalie, locked: S.locked, mic: S.mic });

// ---------- time: two boxes, minutes and seconds ----------
const periodLength = (p) => seconds(S.header.periods.find((x) => x.period === p)?.length ?? '20:00');
const currentTime = () => S.timeOverride ?? nextTime(events(), S.period, periodLength(S.period));
// id 't' = top bar; id 'd' = dialog (for a new event it writes back to the top bar)
const timeBoxes = (id, t) => `<span class="tm" data-tm="${id}">
  <button class="step" data-step="${id}:-60" aria-label="Minuta zpět">${icon(I.down)}</button><input id="${id}m" data-mm maxlength="2" inputmode="numeric" value="${esc(t.slice(0, 2))}" aria-label="Minuty"><button class="step" data-step="${id}:60" aria-label="Minuta dopředu">${icon(I.up)}</button>
  <b>:</b>
  <button class="step" data-step="${id}:-10" aria-label="10 sekund zpět">−10</button><button class="step" data-step="${id}:-1" aria-label="1 sekunda zpět">−1</button><input id="${id}s" maxlength="2" inputmode="numeric" value="${esc(t.slice(3))}" aria-label="Sekundy"><button class="step" data-step="${id}:1" aria-label="1 sekunda dopředu">+1</button><button class="step" data-step="${id}:10" aria-label="10 sekund dopředu">+10</button>
</span>`;
const boxPeriod = (id) => (id === 'd' ? Number($dlg.dataset.period) : S.period);
function readTime(id, period = boxPeriod(id)) {
  const m = document.getElementById(`${id}m`).value.trim(), s = document.getElementById(`${id}s`).value.trim();
  if (!/^\d{1,2}$/.test(m) || !/^\d{1,2}$/.test(s) || Number(s) > 59) return null;
  const t = `${m.padStart(2, '0')}:${s.padStart(2, '0')}`;
  return seconds(t) < periodLength(period) ? t : null;
}
function writeTime(id, t) {
  document.getElementById(`${id}m`).value = t.slice(0, 2);
  document.getElementById(`${id}s`).value = t.slice(3);
  timeChanged(id, t);
}
function timeChanged(id, t) {
  if (id === 't' || $dlg.dataset.sync === '1') S.timeOverride = t;
  if (id === 'd' && $dlg.dataset.sync === '1') { const m = document.getElementById('tm'); if (m) { m.value = t.slice(0, 2); document.getElementById('ts').value = t.slice(3); } }
}
// two digits of minutes typed -> jump to seconds; focusing a box selects it so typing replaces
document.addEventListener('input', (e) => {
  const box = e.target.closest('.tm');
  if (!box) return;
  if (e.target.matches('[data-mm]') && e.target.value.length === 2) box.querySelector('input:not([data-mm])').focus();
  const t = readTime(box.dataset.tm);
  if (t) timeChanged(box.dataset.tm, t);
});
document.addEventListener('focusin', (e) => { if (e.target.matches('.tm input')) e.target.select(); });
// steppers: one step per tap, holding repeats
let repeat = null;
document.addEventListener('pointerdown', (e) => {
  const b = e.target.closest('[data-step]');
  if (!b || !S) return;
  e.preventDefault();
  const [id, delta] = b.dataset.step.split(':');
  const step = () => { const t = readTime(id) ?? currentTime(); writeTime(id, stepTime(t, Number(delta), periodLength(boxPeriod(id)))); };
  step();
  clearTimeout(repeat?.t); clearInterval(repeat?.i);
  repeat = { t: setTimeout(() => (repeat.i = setInterval(step, 110)), 450) };
});
const stopRepeat = () => {
  if (!repeat) return;
  clearTimeout(repeat.t); clearInterval(repeat.i); repeat = null;
  if (S?.view === 'subs' && !$dlg.open) render(); // suggestions depend on the time
};
['pointerup', 'pointercancel'].forEach((ev) => document.addEventListener(ev, stopRepeat));

// ---------- derived ----------
const events = () => mergeEvents(S.server, outbox.forMatch(S.id));
const field = (team) => S.roster[team].filter((p) => p.position !== 'G');
const goalies = (team) => S.roster[team].filter((p) => p.position === 'G');
const jersey = (id) => S.players.get(id)?.jersey ?? '?';
const pname = (id) => { const p = S.players.get(id); return p ? `${p.jersey} ${p.last_name}` : `#${id}`; };
const chips = (ids) => `<div class="chips">${[...ids].sort((a, b) => jersey(a) - jersey(b)).map((id) => `<span class="chip">${esc(jersey(id))}</span>`).join('')}</div>`;

function score(evs) {
  const g = { home: 0, away: 0 };
  for (const e of evs) if (e.type === 'shot' && e.result === 'goal') g[e.team]++;
  return g;
}

function suggestionsFor(team, evs, time) {
  const subs = sortEvents(evs.filter((e) => e.type === 'substitution' && e.team === team && e.status !== 'rejected'));
  const before = subs.filter((e) => e.period < S.period || (e.period === S.period && seconds(e.time) <= seconds(time)));
  const current = lineupAt(before, team, S.period, time);
  const { size } = teamSituation(S.situation, team);
  return { current, list: suggest({ history: before.map((e) => e.players), current, formations: S.lines[team], size }) };
}

// ---------- render ----------
function render() {
  if (!S || $dlg.open) return;
  const evs = events();
  const g = score(evs);
  const time = currentTime();
  const pending = evs.filter((e) => e.status === 'pending').length + outbox.forMatch(S.id).filter((i) => i.op === 'delete' && i.status === 'pending').length;
  const rejected = evs.filter((e) => e.status === 'rejected').length;
  const sync = rejected ? ['bad', `Odmítnuto: ${rejected}`] : pending ? ['wait', `Čeká: ${pending}`] : ['', 'Odesláno'];
  const focused = document.activeElement?.id;

  $app.innerHTML = `
  <div class="top">
    <button id="back" aria-label="Zpět na výběr zápasu" title="Zpět na výběr zápasu"><span class="logo" aria-hidden="true"></span></button>
    <div class="match"><b>${esc(S.header.home.short_name ?? S.header.home.name)}</b> <span class="score">${g.home} : ${g.away}</span> <b>${esc(S.header.away.short_name ?? S.header.away.name)}</b></div>
    <div class="row">${S.header.periods.map((p) => `<button data-period="${p.period}" class="${p.period === S.period ? 'on' : ''}">${p.overtime ? 'P' : p.period + '.'}</button>`).join('')}</div>
    <div class="row tabs"><button data-view="shots" class="${S.view === 'shots' ? 'on' : ''}">Střely</button><button data-view="subs" class="${S.view === 'subs' ? 'on' : ''}">Střídání</button><button data-view="log" class="${S.view === 'log' ? 'on' : ''}">Zápis${rejected ? ` <span class="badge">${rejected}</span>` : ''}</button><button data-view="stats" class="${S.view === 'stats' ? 'on' : ''}">Analýza</button></div>
    ${S.view === 'shots' || S.view === 'subs' ? `${timeBoxes('t', time)}<button id="lock" class="lock ${isLocked() ? 'on' : ''}" aria-pressed="${isLocked()}">${isLocked() ? `${LOCK} Zamčeno` : `${icon(I.unlock)} Zamknout`}</button>${S.view === 'shots' ? `<button id="mic" class="lock mic ${S.mic ? 'on' : ''}" aria-pressed="${S.mic}" aria-label="Hlasový zápis střel" title="${S.mic ? 'Mikrofon zapnutý – po ťuknutí na hřiště mluvte' : 'Zapnout hlasový zápis'}">${MIC}</button>` : ''}` : ''}
    ${sync[0] ? `<span class="sync ${sync[0]}">${esc(sync[1])}</span>` : ''}<button id="fs" class="fsbtn" aria-label="${isFull() ? 'Ukončit celou obrazovku' : 'Celá obrazovka'}">${isFull() ? FS_EXIT : FS_ENTER}</button>
  </div>
  ${S.view === 'shots' ? shotsView(evs) : S.view === 'stats' ? statsView(evs) : S.view === 'log' ? logView(evs) : S.edit ? editorView() : subsView(evs, time)}`;

  $app.querySelector('#back').onclick = () => { saveUi(); showList(); };
  $app.querySelector('#fs').onclick = toggleFull;
  $app.querySelectorAll('[data-period]').forEach((b) => (b.onclick = () => { S.period = Number(b.dataset.period); S.timeOverride = null; S.pend = null; saveUi(); render(); }));
  $app.querySelectorAll('[data-view]').forEach((b) => (b.onclick = () => { S.view = b.dataset.view; saveUi(); render(); }));
  $app.querySelectorAll('#tm, #ts').forEach((i) => {
    i.onchange = () => { if (!readTime('t', S.period)) toast('Čas zadejte jako minuty a sekundy v rámci části'); else if (S.view === 'subs') render(); };
  });
  // a background send re-renders the page: keep the scorer's cursor in the time box
  if (['tm', 'ts', 'vf-shooter', 'vf-assist'].includes(focused) && $app.querySelector(`#${focused}`)) { const el = $app.querySelector(`#${focused}`); el.focus(); el.setSelectionRange(el.value.length, el.value.length); }
  $app.querySelectorAll('[data-edit]').forEach((b) => (b.onclick = () => editEvent(b.dataset.edit)));
  $app.querySelectorAll('[data-del]').forEach((b) => (b.onclick = () => deleteEvent(b.dataset.del)));
  $app.querySelectorAll('[data-retry]').forEach((b) => (b.onclick = () => { outbox.retry(b.dataset.retry); pump(); }));
  $app.querySelector('#mic')?.addEventListener('click', () => { S.mic = !S.mic; stopListening(); if (S.pend?.step === 'vpop') S.pend = null; saveUi(); render(); if (S.mic) micCheck(); });
  $app.querySelector('#lock')?.addEventListener('click', () => {
    S.locked = isLocked() ? S.locked.filter((x) => x !== S.period) : [...S.locked, S.period];
    Object.assign(S, { pend: null, vtype: false });
    saveUi(); render();
  });
  if (S.view === 'shots') {
    $app.querySelector('#rink')?.addEventListener('pointerup', onRinkTap); // no rink while the roster half is open
    $app.querySelector('#flip')?.addEventListener('click', () => { S.flipped = !S.flipped; saveUi(); render(); }); // not shown mid-shot
    $app.querySelectorAll('[data-pick]').forEach((b) => (b.onclick = () => onPick(b.dataset.pick)));
    $app.querySelectorAll('[data-qresult]').forEach((b) => (b.onclick = () => onResult(b.dataset.qresult)));
    $app.querySelectorAll('[data-qstrength]').forEach((b) => (b.onclick = () => { S.pend.strength = b.dataset.qstrength; render(); }));
    $app.querySelector('[data-qnoassist]')?.addEventListener('click', () => { S.pend.assist_id = null; saveShot(S.pend); });
    $app.querySelector('[data-qcancel]')?.addEventListener('click', () => { stopListening(); S.pend = null; render(); });
    $app.querySelector('[data-vswap]')?.addEventListener('click', (ev) => { // slide first, then redraw with the other team
      const sw = ev.currentTarget, team = other(S.pend.team);
      Object.assign(S.pend, { team, strength: teamSituation(S.situation, team).strength });
      sw.classList.toggle('right'); sw.querySelectorAll('span').forEach((s) => s.classList.toggle('cur'));
      sw.querySelector('.thumb').className = `thumb ${team}`; sw.closest('.vpop').classList.replace(other(team), team);
      setTimeout(render, 220);
    });
    $app.querySelectorAll('[data-vres]').forEach((b) => (b.onclick = () => { S.pend.result = b.dataset.vres; render(); }));
    $app.querySelectorAll('#vf-shooter, #vf-assist').forEach((inp) => (inp.oninput = () => { S.pend[inp.id === 'vf-shooter' ? 'shooterNo' : 'assistNo'] = inp.value.replace(/\D/g, ''); render(); }));
    $app.querySelector('[data-vagain]')?.addEventListener('click', () => { stopListening(); Object.assign(S.pend, { team: S.pend.tapTeam, result: null, shooterNo: '', assistNo: '' }); listen(S.pend); render(); });
    $app.querySelector('[data-vsave]')?.addEventListener('click', saveVoice);
    $app.querySelector('[data-qswitch]')?.addEventListener('click', () => { const p = S.pend; const team = other(p.team); Object.assign(p, { team, step: 'shooter', shooter_id: null, assist_id: null, strength: teamSituation(S.situation, team).strength }); render(); });
    $app.querySelector('[data-qback]')?.addEventListener('click', () => { Object.assign(S.pend, { step: 'result', shooter_id: null, assist_id: null }); render(); });
  } else if (S.view === 'log') {
    $app.querySelectorAll('[data-lf]').forEach((b) => (b.onclick = () => { const [k, raw] = b.dataset.lf.split(':'); toggleFilter(S.lf, k, raw); render(); }));
  } else if (S.view === 'stats') {
    $app.querySelectorAll('[data-af]').forEach((b) => (b.onclick = () => { const [k, raw] = b.dataset.af.split(':'); toggleFilter(S.af, k, raw); render(); }));
    $app.querySelector('[data-aplayers]')?.addEventListener('click', playersDialog);
    $app.querySelectorAll('[data-aplayerbtn]').forEach((b) => (b.onclick = () => { toggleFilter(S.af, 'players', b.dataset.aplayerbtn); render(); }));
  } else {
    // power play of one team = the other one is short-handed; tapping the active one goes back to even
    $app.querySelectorAll('[data-pp]').forEach((b) => (b.onclick = () => { const pp = `pp_${b.dataset.pp}`; S.situation = S.situation === pp ? 'even' : pp; saveUi(); render(); }));
    $app.querySelector('[data-sublock]')?.addEventListener('click', lockedSubs); // taps on the locked panels explain why
    $app.querySelectorAll('[data-newsub]').forEach((b) => (b.onclick = () => {
      if (lockedSubs()) return;
      const team = b.dataset.newsub;
      const onRink = teamSituation(S.situation, team).strength === 'short_handed' ? [] : lineupAt(events(), team, S.period, topTime() ?? currentTime()) ?? [];
      S.nsub = { team, players: [...onRink], goalie: S.goalie[team], sel: null };
      render();
    }));
    $app.querySelectorAll('[data-more]').forEach((b) => (b.onclick = () => { S.more[b.dataset.more] = !S.more[b.dataset.more]; render(); }));
    $app.querySelectorAll('[data-less]').forEach((b) => (b.onclick = () => { S.more[b.dataset.less] = false; render(); scrollTo({ top: 0 }); }));
    floatLess();
    $app.querySelectorAll('[data-shift]').forEach((b) => (b.onclick = () => editEvent(b.dataset.shift)));
    $app.querySelectorAll('[data-nsp]').forEach((b) => (b.onclick = () => onNewPlayer(Number(b.dataset.nsp))));
    $app.querySelectorAll('[data-npool]').forEach((b) => (b.onclick = () => onPoolPlayer(Number(b.dataset.npool))));
    $app.querySelector('[data-nextra]')?.addEventListener('click', () => { S.nsub.sel = S.nsub.sel?.side === 'extra' ? null : { side: 'extra' }; render(); });
    $app.querySelectorAll('[data-ngk]').forEach((b) => (b.onclick = () => {
      const n = S.nsub; n.goalie = b.dataset.ngk ? Number(b.dataset.ngk) : null;
      if (n.goalie != null && n.players.length > baseField(n)) n.players = n.players.slice(0, baseField(n)); // goalie back: one field player less
      render();
    }));
    $app.querySelectorAll('[data-nline]').forEach((b) => (b.onclick = () => {
      const [k, i] = b.dataset.nline.split(':'), team = S.nsub.team;
      S.nsub.players = k === 'ai' ? [...suggestionsFor(team, events(), topTime() ?? currentTime()).list[Number(i)].players] : linePlayers(S.lines[team][Number(k)]);
      S.nsub.sel = null; render();
    }));
    $app.querySelector('[data-nremove]')?.addEventListener('click', () => { S.nsub.players = S.nsub.players.filter((x) => x !== S.nsub.sel.id); S.nsub.sel = null; render(); });
    $app.querySelector('[data-ncancel]')?.addEventListener('click', () => { S.nsub = null; render(); });
    $app.querySelector('[data-nsave]')?.addEventListener('click', () => {
      if (lockedSubs()) return;
      const t = topTime();
      const { team, players, goalie } = S.nsub;
      // the substitution before this one: remember the goalie who was playing then (older ones have none stored)
      const prev = sortEvents(events().filter((e) => e.type === 'substitution' && e.team === team && e.period === S.period && e.status !== 'rejected' && t && seconds(e.time) < seconds(t))).pop();
      const id = t && recordSub(team, [...players], undefined, t);
      if (!id) return;
      if (prev && !(prev.client_id in S.gk)) S.gk[prev.client_id] = S.goalie[team];
      // the goalie goes into the shots (goalkeeper_id of the opponent's shots) and the shift list (B)
      S.gk[id] = goalie; store.set(`fm.gk.${S.id}`, S.gk);
      S.goalie[team] = goalie; saveUi();
      S.nsub = null; render();
    });
    $app.querySelectorAll('[data-editlines]').forEach((b) => (b.onclick = () => { S.nsub = null; S.edit = S.edit?.team === b.dataset.editlines ? null : { team: b.dataset.editlines, sel: null, target: null }; render(); }));
    $app.querySelectorAll('[data-slot]').forEach((b) => (b.onclick = () => onSlot(...b.dataset.slot.split(':'))));
    $app.querySelectorAll('[data-bench]').forEach((b) => (b.onclick = () => onEditPlayer(Number(b.dataset.bench))));
    $app.querySelector('[data-clearsel]')?.addEventListener('click', () => { const { team, sel } = S.edit; S.lines[team] = S.lines[team].map((l) => Object.fromEntries(Object.entries(l).map(([k, v]) => [k, k !== 'line' && v === sel ? null : v]))); S.edit.sel = null; saveLines(); render(); });
    $app.querySelector('[data-resetlines]')?.addEventListener('click', () => { if (confirm('Vrátit řady podle předvoleb trenéra z API?')) { S.lines[S.edit.team] = initLines(S.formations[S.edit.team]); S.edit.sel = null; saveLines(); render(); } });
  }
}

// the time in the top bar, as typed right now (also when not yet confirmed with Enter)
function topTime() {
  if (!document.getElementById('tm')) return currentTime(); // time boxes are shown on Střely and Střídání
  const t = readTime('t', S.period);
  if (!t) toast('Čas zadejte jako minuty a sekundy v rámci části');
  return t;
}

// full screen: our own (Fullscreen API) or the browser's (F11), which only shows as a window as big as the screen
const FS_ENTER = icon(I.full);
const FS_EXIT = icon(I.unfull);
const isFull = () => !!document.fullscreenElement || (Math.abs(innerHeight - screen.height) < 2 && Math.abs(innerWidth - screen.width) < 2);
function toggleFull() {
  if (document.fullscreenElement) document.exitFullscreen();
  else if (isFull()) toast('Celou obrazovku zapnutou klávesou F11 ukončíte zase klávesou F11');
  else document.documentElement.requestFullscreen?.().catch(() => toast('Prohlížeč celou obrazovku nepovolil'));
}
function updateFs() {
  const b = document.getElementById('fs');
  if (b) { b.innerHTML = isFull() ? FS_EXIT : FS_ENTER; b.setAttribute('aria-label', isFull() ? 'Ukončit celou obrazovku' : 'Celá obrazovka'); }
}
addEventListener('resize', updateFs);
document.addEventListener('fullscreenchange', updateFs);

const isLocked = () => S.locked.includes(S.period);
const periodName = () => S.header.periods.find((x) => x.period === S.period)?.label ?? `${S.period}. třetina`;
const lockedTxt = () => `${periodName()} je ${periodName().endsWith('í') ? 'zamčené' : 'zamčená'}`; // "Prodloužení je zamčené"
// display only (API coordinates never change): odd periods home on the left, even ones on the right;
// "Prohodit strany" inverts this for every period if the hall is the other way round
const flipped = () => (S.period % 2 === 1) !== !!S.flipped;
const mapFlipped = () => !flipped(); // the map is the other way round than the columns: each team shoots away from its side
const LOCK = icon(I.lock);

// Shape = result, colour = team (readable for colour-blind people and in sunlight: white outline).
function marker(x, y, result, team, k = 1) {
  const c = `var(--${team})`;
  const line = (d, w) => `<path d="${d}" fill="none" stroke="#fff" stroke-width="${w + 4 * k}" stroke-linecap="round" stroke-linejoin="round"/><path d="${d}" fill="none" stroke="${c}" stroke-width="${w}" stroke-linecap="round" stroke-linejoin="round"/>`;
  // floorball ball: a circle with holes
  const ball = (r, fill, holes) => `<circle cx="${x}" cy="${y}" r="${r}" fill="${fill}" stroke="${fill === '#fff' ? c : '#fff'}" stroke-width="${2 * k}"/>`
    + [[-0.38, -0.3], [0.38, -0.3], [0, 0.42]].map(([a, b]) => `<circle cx="${x + a * r}" cy="${y + b * r}" r="${r * 0.2}" fill="${holes}"/>`).join('');
  const frame = (w, h) => `M${x - w / 2} ${y + h / 2}V${y - h / 2}H${x + w / 2}V${y + h / 2}`; // posts + crossbar
  if (result === 'goal') {
    const w = 34 * k, h = 24 * k;
    return `<rect x="${x - w / 2}" y="${y - h / 2}" width="${w}" height="${h}" fill="${c}" stroke="#fff" stroke-width="${2 * k}"/>${line(frame(w, h), 3.5 * k)}${ball(6.5 * k, '#fff', c)}`;
  }
  if (result === 'post') return line(frame(26 * k, 19 * k), 3.5 * k);
  if (result === 'on_goal') return ball(8 * k, c, '#fff');
  const r = 7 * k;
  return line(`M${x - r} ${y - r}L${x + r} ${y + r}M${x + r} ${y - r}L${x - r} ${y + r}`, 4 * k);
}
const legendIcon = (result) => `<svg viewBox="-14 -14 28 28" width="26" height="26" aria-hidden="true">${marker(0, 0, result, 'ink', 0.75)}</svg>`;

function shotsView(evs) {
  const left = flipped() ? 'home' : 'away';
  const shots = evs.filter((e) => e.type === 'shot' && e.period === S.period);
  const dispX = (x) => (mapFlipped() ? RINK.w - x : x);
  // goals drawn last so they are never hidden under other marks
  const order = { miss: 0, post: 1, on_goal: 2, goal: 3 };
  const p = S.pend;
  if (p && (p.step === 'shooter' || p.step === 'assist')) return pickView(p, left);
  const px = p?.x != null ? (dispX(p.x) / RINK.w) * 100 : 0, py = p?.y != null ? (p.y / RINK.h) * 100 : 0;
  // small result menu next to the tapped spot, kept inside the rink
  const pop = p?.step === 'result' ? `<div class="qpop" style="left:${px}%;top:${py}%;transform:translate(${px > 60 ? 'calc(-100% - 18px)' : '18px'},${py > 50 ? 'calc(-100% - 18px)' : '18px'})">
      ${['goal', 'on_goal', 'post', 'miss'].map((k) => `<button data-qresult="${k}" class="res-${k}">${legendIcon(k)}${RESULT[k]}</button>`).join('')}
    </div>` : '';
  const vpop = p?.step === 'vpop' ? voicePop(p, px, py) : '';
  return `<div class="shotsview">
    ${lineCol(left, evs)}
    <div class="center">
      <div class="rink ${mapFlipped() ? 'flipped' : ''} ${isLocked() ? 'locked' : ''}" id="rink">${isLocked() ? `<div class="lockmsg">${LOCK} ${lockedTxt()}</div>` : ''}
        <img src="img/hriste-890x501.png" alt="">
        <svg viewBox="0 0 ${RINK.w} ${RINK.h}" aria-label="Hřiště – ťuknutím zapíšete střelu">
          ${[...shots].sort((a, b) => order[a.result] - order[b.result]).map((e) => marker(dispX(e.x), e.y, e.result, e.team)).join('')}
          ${p?.x != null ? `<circle cx="${dispX(p.x)}" cy="${p.y}" r="16" fill="none" stroke="var(--${p.team})" stroke-width="4" stroke-dasharray="6 4"/><circle cx="${dispX(p.x)}" cy="${p.y}" r="4" fill="var(--${p.team})"/>` : ''}
        </svg>${pop}${vpop}
      </div>
      ${actionBar(left)}
    </div>
    ${lineCol(other(left), evs)}
  </div>`;
}

function lineCol(team, evs) {
  const lineup = lineupAt(evs, team, S.period, currentTime());
  const p = S.pend;
  const active = p && p.team === team && p.step === 'result';
  const { strength, size } = teamSituation(S.situation, team);
  const rows = lineup ? orderLineup(lineup, S.lines[team], S.players).map(({ slot, id }) => {
    const pl = S.players.get(id);
    const off = p?.step === 'assist' && (p.team !== team || id === p.shooter_id);
    return `<button class="pl" data-pick="${team}:${id}" ${off ? 'disabled' : ''} ${p?.shooter_id === id && p.team === team ? 'aria-pressed="true"' : ''}><span class="slot">${SLOT_LABEL[slot]}</span><span class="n">${esc(pl?.jersey ?? '?')}</span><span class="nm">${esc(pl?.last_name ?? '')}</span></button>`;
  }).join('') : `<p class="muted nolineup">Sestava není zapsaná. Zapište ji v části Střídání.</p>`;
  const g = S.goalie[team] ? S.players.get(S.goalie[team]) : null;
  return `<aside class="linecol ${team} ${active ? 'active' : ''}">
    <div class="colhead">${esc(SIDE[team])} · ${esc(S.header[team].short_name ?? S.header[team].name)}</div>
    ${strength !== 'even' ? `<div class="sitnote ${strength}">${esc(STRENGTH[strength])} · ${size}</div>` : ''}
    ${rows}
    <div class="gk-sep">Brankář</div>
    <div class="pl goalie"><span class="slot">B</span><span class="n">${esc(g?.jersey ?? '–')}</span><span class="nm">${esc(g?.last_name ?? 'prázdná branka')}</span></div>
  </aside>`;
}

function actionBar(left) {
  const p = S.pend;
  const flip = `<button id="flip" class="small">${icon(I.swap)} Prohodit strany</button>`;
  if (isLocked()) return `<div class="bar locked"><span class="hint">${LOCK} <b>${lockedTxt()}</b> – další střely nejde zapsat. Opravy jsou dál v záložce Zápis.</span></div>`;
  if (!p) return `<div class="bar slim">${flip}
      <span class="legend">${Object.entries(RESULT).map(([k, l]) => `<span>${legendIcon(k)}${l}</span>`).join('')}
      <span><i class="sw home"></i>Domácí</span><span><i class="sw away"></i>Hosté</span></span></div>`;
  return `<div class="bar active ${p.team}"><span class="hint"><b>Střela ${p.team === 'home' ? 'domácích' : 'hostů'}</b> – ${p.step === 'vpop' ? 'zkontrolujte údaje v okénku a potvrďte' : 'vyberte výsledek v menu u místa střely'}</span><button data-qcancel class="small">Zrušit</button></div>`;
}

// half of the screen: the whole roster of the shooting team, players on the rink first;
// the other half switches to the other team (same sides as on the rink)
function pickView(p, left) {
  const opp = other(p.team);
  const sw = `<button class="switchteam ${opp}" data-qswitch>Střílel druhý tým<b>${esc(SIDE[opp])} · ${esc(S.header[opp].short_name ?? S.header[opp].name)}</b><span>ťukněte pro přepnutí</span></button>`;
  const panel = rosterPanel(p);
  return `<div class="pickview">${p.team === left ? panel + sw : sw + panel}</div>`;
}

function rosterPanel(p) {
  const assist = p.step === 'assist';
  const ice = lineupAt(events(), p.team, S.period, currentTime()) ?? [];
  const onIce = orderLineup(ice, S.lines[p.team], S.players);
  const rest = field(p.team).filter((pl) => !ice.includes(pl.id)).sort((a, b) => a.jersey - b.jersey);
  const btn = (id, slot, cls = '') => { const pl = S.players.get(id);
    return `<button class="rp ${cls}" data-pick="${p.team}:${id}" ${assist && id === p.shooter_id ? 'disabled' : ''}>${slot ? `<small>${SLOT_LABEL[slot]}</small>` : ''}<b>${esc(pl?.jersey ?? '?')}</b><span>${esc(pl?.last_name ?? '')}</span></button>`; };
  return `<section class="rosterpanel ${p.team}">
    <div class="rp-head">${legendIcon(p.result)} <b>${esc(RESULT[p.result])}</b> · ${esc(SIDE[p.team])} · ${esc(S.header[p.team].short_name ?? S.header[p.team].name)}${p.strength !== 'even' ? ` · <span class="pill ${p.strength}">${esc(STRENGTH[p.strength])}</span>` : ''}
      <span class="rp-q">${assist ? `Gól ${esc(pname(p.shooter_id))} – kdo asistoval?` : 'Kdo střílel?'}</span></div>
    <div class="rp-sec">Na hřišti</div>
    <div class="rp-grid ice">${onIce.map(({ slot, id }) => btn(id, slot, 'ice')).join('') || '<span class="muted">Sestava není zapsaná – vyberte z ostatních</span>'}</div>
    <div class="rp-sec">Ostatní hráči <span class="muted">(když střídání nestihlo)</span></div>
    <div class="rp-grid">${rest.map((pl) => btn(pl.id)).join('')}</div>
    <div class="rp-sec">Brankáři</div><div class="rp-grid">${goalies(p.team).map((pl) => btn(pl.id, null, S.goalie[p.team] === pl.id ? 'ice gk-on' : 'gk')).join('')}</div>
    <div class="row rp-foot">${assist ? '<button data-qnoassist class="big">Bez asistence</button>' : ''}<button data-qback class="small">${icon(I.undo)} Jiný výsledek</button><button data-qcancel class="small">Zrušit</button></div>
  </section>`;
}

// ---------- voice mode: mic on -> a tap on the rink starts listening -> small popup with what was heard
// and editable fields -> the scorer confirms. Nothing is saved without "Uložit". ----------
const SR = globalThis.SpeechRecognition || globalThis.webkitSpeechRecognition;
const MIC = icon(I.mic);
const byJersey = (team, n) => (team && n !== '' && n != null ? S.roster[team].find((p) => p.jersey === Number(n)) : null);
const stopListening = () => { try { S.pend?.rec?.abort(); } catch { /* already stopped */ } };

// Why speech cannot work here, in words the scorer can act on (null = it can)
function micProblem() {
  if (!SR) return 'Tento prohlížeč neumí rozpoznávat řeč – použijte Chrome nebo Edge';
  if (!isSecureContext) return 'Mikrofon funguje jen na https:// nebo localhost. Na tabletu: zrcadlení z PC, nebo v Chrome otevřete chrome://flags, „Insecure origins treated as secure“ a přidejte tuto adresu.';
  return null;
}

// When the mic is switched on: check the browser and ask for the permission now, not in the middle of a shot
async function micCheck() {
  const problem = micProblem();
  if (problem) { toast(problem); return; }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    stream.getTracks().forEach((t) => t.stop());
    toast('Mikrofon je připravený – ťukněte na místo střely a mluvte');
  } catch (e) {
    toast(e.name === 'NotAllowedError' ? 'Mikrofon je zakázaný – povolte ho u adresy (ikona vlevo v adresním řádku) a ve Windows/Androidu' : 'Mikrofon nejde zapnout – zkontrolujte, že je připojený');
  }
}

const MIC_ERRORS = {
  'not-allowed': 'Mikrofon je zakázaný – povolte ho u adresy (ikona vlevo v adresním řádku).',
  'service-not-allowed': 'Rozpoznávání řeči je v tomto prohlížeči vypnuté.',
  network: 'Rozpoznávání řeči v Chrome potřebuje internet.',
  'audio-capture': 'Nenašel jsem mikrofon – zkontrolujte, že je připojený a povolený.',
  'no-speech': 'Nic nezaznělo.',
  'language-not-supported': 'Čeština není v tomto prohlížeči k dispozici.',
};

// Listens while the scorer speaks (pauses between words are fine) and fills the fields as the words come;
// stops 1.8 s after the last word. Nothing is saved until "Uložit".
function listen(p) {
  Object.assign(p, { listening: true, note: null, heard: '' });
  const problem = micProblem();
  if (problem) { Object.assign(p, { listening: false, note: problem }); return; }
  const rec = new SR();
  Object.assign(rec, { lang: 'cs-CZ', interimResults: true, maxAlternatives: 3, continuous: true });
  p.rec = rec;
  const finals = [];
  let timer = setTimeout(() => rec.stop(), 7000); // nothing said at all
  rec.onresult = (e) => {
    let interim = '';
    for (let i = e.resultIndex; i < e.results.length; i++) {
      const r = e.results[i];
      if (r.isFinal) finals[i] = [...r].map((a) => a.transcript.trim());
      else interim += ` ${r[0].transcript}`;
    }
    // Chrome's guesses for the last finished phrase, each joined with what was said before it
    const done = finals.filter(Boolean);
    const before = done.slice(0, -1).map((a) => a[0]).join(' ');
    const guesses = (done.at(-1) ?? ['']).map((alt) => `${before} ${alt} ${interim}`.replace(/\s+/g, ' ').trim());
    heard(p, guesses, false);
    clearTimeout(timer);
    timer = setTimeout(() => rec.stop(), 1800);
  };
  rec.onerror = (e) => {
    if (S.pend !== p || e.error === 'aborted') return;
    clearTimeout(timer);
    Object.assign(p, { listening: false, note: `${MIC_ERRORS[e.error] ?? `Rozpoznávání řeči selhalo (${e.error}).`} Vyplňte políčka.` });
    render();
  };
  rec.onend = () => { clearTimeout(timer); if (S.pend === p && p.listening) { p.listening = false; render(); } };
  try { rec.start(); } catch { Object.assign(p, { listening: false, note: 'Mikrofon se nepodařilo spustit – zkuste „Znovu“' }); }
}

// Fills the popup from what was heard. Chrome gives up to 3 guesses; take the one whose shooter is on the roster.
// done = false while the scorer is still speaking (the fields update live).
function heard(p, alternatives, done = true) {
  if (S.pend !== p) return;
  const names = { home: [S.header.home.short_name, S.header.home.name], away: [S.header.away.short_name, S.header.away.name] };
  const fill = (text) => { const c = parseCommand(text, { names }); const n = c.shooter ?? '';
    // team not said: the tapped half, unless the number is only on the other team's roster
    const team = c.team ?? (!byJersey(p.tapTeam, n) && byJersey(other(p.tapTeam), n) ? other(p.tapTeam) : p.tapTeam);
    return { heard: text, team, result: c.result, shooterNo: c.shooter ?? '', assistNo: c.assist ?? '', strength: c.strength, time: c.time }; };
  const score = (f) => (byJersey(f.team, f.shooterNo) ? 2 : 0) + (f.result ? 1 : 0);
  const best = alternatives.map(fill).sort((a, b) => score(b) - score(a))[0];
  Object.assign(p, best, { listening: !done, strength: best.strength ?? teamSituation(S.situation, best.team).strength,
    time: best.time && seconds(best.time) < periodLength(S.period) ? best.time : undefined });
  render();
}

function voiceReady(p) {
  const sh = byJersey(p.team, p.shooterNo), as = byJersey(p.team, p.assistNo);
  const assistOk = p.result !== 'goal' || p.assistNo === '' || p.assistNo == null || (as && as.id !== sh?.id);
  return p.team && p.result && sh && assistOk ? { sh, as: p.result === 'goal' ? as : null } : null;
}

function voicePop(p, px, py) {
  const sh = byJersey(p.team, p.shooterNo), as = byJersey(p.team, p.assistNo);
  const left = flipped() ? 'home' : 'away'; // the switch has the teams on the same sides as the columns
  const field = (id, label, value, person, placeholder) => { const bad = value !== '' && value != null && !person;
    return `<div class="vrow"><span>${label}</span><input id="${id}" inputmode="numeric" maxlength="2" value="${esc(value ?? '')}" placeholder="${placeholder}" class="${bad ? 'bad' : ''}" autocomplete="off">
      <span class="vname ${bad ? 'bad' : ''}">${person ? esc(person.last_name) : bad ? `č. ${esc(value)} není na soupisce` : ''}</span></div>`; };
  // beside the spot, vertically centred on the rink (the popup is tall)
  return `<div class="qpop vpop ${p.team}" style="left:${px}%;top:50%;transform:translate(${px > 50 ? 'calc(-100% - 24px)' : '24px'},-50%)">
    <div class="vheard">${MIC} <span id="vheard">${p.heard ? `„${esc(p.heard)}“` : p.listening ? 'Mluvte… např. „gól devadesát asistence 98“' : esc(p.note ?? 'Nic nezaznělo – vyplňte políčka')}</span>${p.listening ? '<span class="live">poslouchám</span>' : ''}</div>
    <div class="vrow"><span>Tým</span><button class="tswitch ${p.team === left ? '' : 'right'}" data-vswap role="switch" aria-checked="${p.team !== left}" aria-label="Střílející tým – ťuknutím přepnete">
      <i class="thumb ${p.team}"></i>${[left, other(left)].map((t) => `<span class="${p.team === t ? 'cur' : ''}">${esc(S.header[t].short_name ?? SIDE[t])}</span>`).join('')}</button></div>
    <div class="vrow vres"><span>Výsledek</span>${['goal', 'on_goal', 'post', 'miss'].map((k) => `<button data-vres="${k}" class="${p.result === k ? 'on' : ''}">${legendIcon(k)}${RESULT[k]}</button>`).join('')}</div>
    ${field('vf-shooter', 'Střelec č.', p.shooterNo, sh, '?')}
    ${p.result === 'goal' ? field('vf-assist', 'Asistence č.', p.assistNo, as, 'bez') : ''}
    <div class="vrow vact"><button data-vagain>${MIC} Znovu</button><button data-qcancel>Zrušit</button><button class="primary" data-vsave ${voiceReady(p) ? '' : 'disabled'}>Uložit</button></div>
  </div>`;
}

function saveVoice() {
  const p = S.pend, ok = voiceReady(p);
  if (!ok) return;
  stopListening();
  saveShot({ team: p.team, result: p.result, shooter_id: ok.sh.id, assist_id: ok.as?.id ?? null, x: p.x, y: p.y, period: p.period, strength: p.strength, time: p.time });
}

// ---------- quick shot: map -> player -> result (-> assist) ----------
function onRinkTap(ev) {
  const r = ev.currentTarget.getBoundingClientRect();
  let x = ((ev.clientX - r.left) / r.width) * RINK.w;
  const y = ((ev.clientY - r.top) / r.height) * RINK.h;
  if (mapFlipped()) x = RINK.w - x; // display only: the API always gets home attacking right
  if (isLocked()) { toast(`${lockedTxt()}. Odemknete tlačítkem se zámkem vedle času.`); return; }
  if (ev.target.closest('.qpop')) return; // a tap on a menu is not a new spot
  const team = x >= RINK.center ? 'home' : 'away';
  if (S.mic) {
    stopListening();
    S.pend = { team, tapTeam: team, step: 'vpop', strength: teamSituation(S.situation, team).strength, x: Math.round(x), y: Math.round(y), period: S.period, result: null, shooterNo: '', assistNo: '' };
    listen(S.pend);
    render();
    return;
  }
  // a new tap moves the spot (and the menu) and takes the team from that half
  S.pend = { team, step: 'result', strength: teamSituation(S.situation, team).strength, x: Math.round(x), y: Math.round(y), period: S.period };
  render();
}

function onPick(value) {
  const [team, idStr] = value.split(':');
  const id = Number(idStr);
  const p = S.pend;
  if (!p) { toast('Nejdřív ťukněte na místo střely na hřišti'); return; }
  if (p.step === 'assist') { if (team === p.team && id !== p.shooter_id) { p.assist_id = id; saveShot(p); } return; }
  if (p.step === 'vpop') { // a tap on a player column fills the shooter of the voice popup
    if (team !== p.team) Object.assign(p, { team, strength: teamSituation(S.situation, team).strength });
    p.shooterNo = String(S.players.get(id)?.jersey ?? ''); render(); return;
  }
  if (p.step === 'result') { toast('Nejdřív vyberte výsledek v menu u místa střely'); return; }
  if (team !== p.team) Object.assign(p, { team, strength: teamSituation(S.situation, team).strength });
  p.shooter_id = id;
  if (p.result === 'goal') { p.step = 'assist'; render(); } else saveShot(p);
}

function onResult(result) {
  S.pend.result = result;
  S.pend.step = 'shooter';
  render();
}

// shared by the quick flow and the dialog; s.time unset = take the top bar
function saveShot(shot, client_id = null) {
  const s = { ...shot };
  s.time ??= topTime();
  if (!s.time) return false;
  const evs = events();
  const opp = other(s.team);
  const oppLine = lineupAt(evs, opp, s.period, s.time);
  if (!(client_id && s.goalkeeper_id !== undefined)) s.goalkeeper_id = oppLine?.length === 6 ? null : S.goalie[opp];
  if (s.result === 'goal') {
    const side = (team) => { const l = lineupAt(evs, team, s.period, s.time); return l && (l.length < 6 && S.goalie[team] ? [...l, S.goalie[team]] : l); };
    const h = side('home'), a = side('away');
    s.on_ice = h && a ? { home: h, away: a } : null;
  }
  const id = client_id ?? crypto.randomUUID();
  S.pend = null;
  // a new shot moves the top bar to its time + 5 s (capped at the end of the period); a correction does not
  if (!client_id) S.timeOverride = stepTime(s.time, 5, periodLength(s.period));
  outbox.put(S.id, id, shotBody(s));
  toast(`${RESULT[s.result]} ${pname(s.shooter_id)} ${s.time} zapsáno`, () => deleteEvent(id, true));
  pump();
  return true;
}

// ---------- analysis: the map for any filter + summary per team ----------
const SLOT_PATHS = (() => {
  const r = SLOT_M * (RINK.w / 40), k = r * Math.SQRT1_2;
  return [`M813 250L${813 - k} ${250 - k}A${r} ${r} 0 0 0 ${813 - k} ${250 + k}Z`, `M76 250L${76 + k} ${250 - k}A${r} ${r} 0 0 1 ${76 + k} ${250 + k}Z`];
})();

const mmssOf = (sec) => `${String(Math.floor(sec / 60)).padStart(2, '0')}:${String(sec % 60).padStart(2, '0')}`;
function toiMap(evs) {
  const live = Math.max(1, ...evs.map((e) => e.period));
  const endOf = (p) => {
    if (p < live || S.locked.includes(p)) return periodLength(p);
    const last = Math.max(0, ...evs.filter((e) => e.period === p).map((e) => seconds(e.time)));
    return Math.min(periodLength(p), Math.max(last, p === S.period ? seconds(currentTime()) : 0));
  };
  return timeOnIce(evs, { periods: S.af.periods, strengths: S.af.strengths }, endOf);
}

function statsView(evs) {
  const f = S.af;
  const shots = filterShots(evs, f);
  const left = flipped() ? 'home' : 'away';
  const chip = (key, value, label) => fchip('af', f, key, value, label);
  const picked = f.players.map((id) => `<button class="small on" data-af="players:${id}" aria-label="Odebrat hráče ${esc(pname(id))}">${esc(pname(id))} ${icon(I.x)}</button>`).join('');
  const order = { miss: 0, post: 1, on_goal: 2, goal: 3 };
  const toi = toiMap(evs);
  return `<div class="statsview">
   <div class="statsgrid">
    ${statCard(left, shots, toi)}
    <div class="statscenter">
    <div class="filters grouped">
      <div class="frow">${fgroup('Část', periodChips('af', f))}${fgroup('Výsledek', chip('results', null, 'Vše') + Object.entries(RESULT).map(([k, l]) => chip('results', k, `${legendIcon(k)}${l}`)).join(''))}${fgroup('Tým', teamChips('af', f))}</div>
      <div class="frow">${fgroup('Hráči', `<button class="small ${f.players.length ? '' : 'on'}" data-af="players:">Všichni</button>${picked}<button class="small pickbtn" data-aplayers>${f.players.length ? 'Změnit…' : 'Vybrat…'}</button>`)}${fgroup('Poměr sil', chip('strengths', null, 'Vše') + Object.entries(STRENGTH).map(([k, l]) => chip('strengths', k, l)).join(''))}</div>
    </div>
      <div class="rink" id="arink">
        <img src="img/hriste-890x501.png" alt="" class="${mapFlipped() ? 'mirror' : ''}">
        <svg viewBox="0 0 ${RINK.w} ${RINK.h}" aria-label="Mapa střel podle filtru"><g ${mapFlipped() ? `transform="matrix(-1 0 0 1 ${RINK.w} 0)"` : ''}>
          ${SLOT_PATHS.map((d) => `<path d="${d}" class="slotzone"/>`).join('')}
          ${[...shots].sort((a, b) => order[a.result] - order[b.result]).map((e) => marker(e.x, e.y, e.result, e.team)).join('')}
        </g></svg>
      </div>
    </div>
    ${statCard(other(left), shots, toi)}
   </div>
   <p class="muted slotnote">Šrafovaná výseč = slot: do ${SLOT_M} m od branky a nejvýš 45° z osy. Jednoduché pravidlo místo xG – na spolehlivé xG máme z jednoho zápasu málo dat.</p>
  </div>`;
}

function playersDialog() {
  const left = flipped() ? 'home' : 'away';
  const draw = () => {
    const base = filterShots(events(), { ...S.af, players: [] });
    const toi = toiMap(events());
    const count = new Map();
    for (const sh of base) count.set(sh.shooter_id, (count.get(sh.shooter_id) ?? 0) + 1);
    const pm = playerPlusMinus(events(), { periods: S.af.periods });
    const sign = (v) => (v > 0 ? `+${v}` : v < 0 ? `−${-v}` : '0');
    const col = (team) => {
      const pmOf = (p) => pm.get(p.id) ?? 0; // no substitution yet = 0
      const key = { jersey: (p) => p.jersey, shots: (p) => -(count.get(p.id) ?? 0), toi: (p) => -(toi.get(p.id) ?? 0), pm: (p) => -pmOf(p) }[S.psort ?? 'jersey'];
      const list = [...field(team).sort((a, b) => key(a) - key(b) || a.jersey - b.jersey), ...goalies(team)];
      const byPm = S.psort === 'pm';
      return `<section class="rosterpanel ${team}"><div class="rp-head"><b>${esc(SIDE[team])} · ${esc(S.header[team].short_name ?? S.header[team].name)}</b></div>
        <div class="rp-grid">${list.map((pl) => { const n = count.get(pl.id) ?? 0; const on = S.af.players.includes(pl.id);
          return `<button class="rp ${on ? 'sel' : ''} ${n ? '' : 'none'} ${pl.position === 'G' ? 'gk' : ''}" data-pp-player="${pl.id}" aria-pressed="${on}"><b>${esc(pl.jersey)}</b><span>${esc(pl.last_name)}</span><small>${n ? `${n}× střela` : 'bez střel'}${pl.position === 'G' ? '' : ` · ${mmssOf(toi.get(pl.id) ?? 0)}`}</small>${byPm && pl.position !== 'G' ? `<small class="pmv ${pmOf(pl) > 0 ? 'plus' : pmOf(pl) < 0 ? 'minus' : ''}">${sign(pmOf(pl))} na hřišti</small>` : ''}</button>`; }).join('')}</div></section>`;
    };
    $dlg.className = 'players-dlg';
    $dlg.innerHTML = `<h2>Hráči pro analýzu <span class="muted">– vyberte jednoho nebo víc (vybráno ${S.af.players.length})</span></h2>
      <div class="row psort"><span class="muted">Seřadit:</span>${[['jersey', 'podle čísla'], ['shots', 'nejvíc střel'], ['toi', 'nejvíc minut na hřišti'], ['pm', 'nejvíc gólů na hřišti (+/−)']].map(([k, l]) => `<button class="small ${(S.psort ?? 'jersey') === k ? 'on' : ''}" data-psort="${k}">${l}</button>`).join('')}</div>
      <div class="pickview dlg">${col(left)}${col(other(left))}</div>
      <div class="actions"><button id="pclear">Všichni hráči</button><button class="primary" id="pdone">Hotovo</button></div>`;
    $dlg.querySelectorAll('[data-pp-player]').forEach((b) => (b.onclick = () => { toggleFilter(S.af, 'players', b.dataset.ppPlayer); draw(); }));
    $dlg.querySelector('#pclear').onclick = () => { S.af.players = []; draw(); };
    $dlg.querySelectorAll('[data-psort]').forEach((b) => (b.onclick = () => { S.psort = b.dataset.psort; draw(); }));
    $dlg.querySelector('#pdone').onclick = closeDlg;
  };
  draw();
  $dlg.showModal();
}

function statCard(team, shots, toi) {
  const mine = shots.filter((s) => s.team === team);
  if (S.af.team && S.af.team !== team) return `<aside class="statcard ${team} off"><h3>${esc(SIDE[team])}</h3><p class="muted">Skryto filtrem</p></aside>`;
  const m = summarize(mine);
  const by = new Map();
  for (const s of mine) { const r = by.get(s.shooter_id) ?? { shots: 0, goals: 0 }; r.shots++; if (s.result === 'goal') r.goals++; by.set(s.shooter_id, r); }
  const top = [...by].sort((a, b) => b[1].goals - a[1].goals || b[1].shots - a[1].shots).slice(0, 3);
  const mins = field(team).filter((p) => toi.get(p.id)).sort((a, b) => toi.get(b.id) - toi.get(a.id)).slice(0, 3);
  const kpi = (v, l) => `<div><b>${v}</b><span>${l}</span></div>`;
  return `<aside class="statcard ${team}">
    <h3>${esc(SIDE[team])} · ${esc(S.header[team].short_name ?? S.header[team].name)}</h3>
    <div class="kpis">${kpi(m.shots, 'střel')}${kpi(m.onTarget, 'na branku')}${kpi(m.goals, 'gólů')}${kpi(`${m.shootingPct} %`, 'úspěšnost')}${kpi(`${m.slotPct} %`, 'ze slotu')}${kpi(m.shots ? `${String(m.avgDist).replace('.', ',')} m` : '–', 'prům. vzdál.')}</div>
    <div class="leaders"><span class="muted">Nejvíc střel</span>${top.map(([id, r]) => `<button class="small ${S.af.players.includes(id) ? 'on' : ''}" data-aplayerbtn="${id}"><b>${esc(jersey(id))}</b> ${esc(S.players.get(id)?.last_name ?? '')} <span>${r.shots}× ${r.goals ? `· ${r.goals} G` : ''}</span></button>`).join('') || '<span class="muted">zatím žádné střely</span>'}</div>
    <div class="leaders"><span class="muted">Nejvíc minut na hřišti</span>${mins.map((p) => `<button class="small ${S.af.players.includes(p.id) ? 'on' : ''}" data-aplayerbtn="${p.id}"><b>${esc(p.jersey)}</b> ${esc(p.last_name)} <span>${mmssOf(toi.get(p.id))}</span></button>`).join('') || '<span class="muted">zatím žádná střídání</span>'}</div>
  </aside>`;
}

function fchip(attr, f, key, value, label) {
  const cur = f[key];
  const on = Array.isArray(cur) ? (value == null ? !cur.length : cur.includes(value)) : cur === value;
  return `<button class="small ${on ? 'on' : ''}" aria-pressed="${on}" data-${attr}="${key}:${value ?? ''}">${label}</button>`;
}
const fgroup = (label, chips) => `<div class="fgroup"><span class="fl">${label}</span>${chips}</div>`;
function toggleFilter(f, key, raw) {
  const v = key === 'periods' || key === 'players' ? Number(raw) : raw;
  if (!Array.isArray(f[key])) f[key] = raw === '' || f[key] === v ? null : v; // one team only
  else f[key] = raw === '' ? [] : f[key].includes(v) ? f[key].filter((x) => x !== v) : [...f[key], v];
}
const teamChips = (attr, f) => fchip(attr, f, 'team', null, 'Oba') + ['home', 'away'].map((t) => fchip(attr, f, 'team', t, esc(S.header[t].short_name ?? SIDE[t]))).join('');
const periodChips = (attr, f) => fchip(attr, f, 'periods', null, 'Vše') + S.header.periods.map((p) => fchip(attr, f, 'periods', p.period, p.overtime ? 'P' : `${p.period}.`)).join('');

function logView(evs) {
  const f = S.lf;
  const shown = filterLog(evs, f);
  // rejected events always stay on top: they need the scorer's attention whatever the filter
  const log = [...evs.filter((e) => e.status === 'rejected'), ...shown.filter((e) => e.status !== 'rejected').reverse()];
  const chip = (key, value, label) => fchip('lf', f, key, value, label);
  return `<div class="logview">
    <div class="filters grouped">
      ${fgroup('Část', periodChips('lf', f))}
      ${fgroup('Tým', teamChips('lf', f))}
      ${fgroup('Typ', chip('kinds', null, 'Vše') + chip('kinds', 'substitution', 'Střídání') + chip('kinds', 'shot', 'Všechny střely') + Object.entries(RESULT).map(([k, l]) => chip('kinds', k, `${legendIcon(k)}${l}`)).join(''))}
    </div>
    <div class="log"><h3>Zápis (${shown.length}${shown.length !== evs.length ? ` z ${evs.length}` : ''})</h3>${log.map(logRow).join('') || '<p class="muted">Nic neodpovídá filtru</p>'}</div>
  </div>`;
}

function subsView(evs, time) {
  const left = flipped() ? 'home' : 'away'; // same sides as on the rink
  const n = S.nsub;
  // while a new substitution is built, the other half shows that team's line-ups to pick from
  const half = (team) => (n && team !== n.team ? subPicker(n.team, evs, time) : teamPanel(team, evs, time));
  return `<div class="subsview ${isLocked() ? 'locked' : ''}">
    <div class="teams">${half(left)}${half(other(left))}
      ${isLocked() ? `<div class="sublock" data-sublock></div><div class="lockmsg">${LOCK} ${lockedTxt()}</div>` : ''}</div>
    ${['home', 'away'].filter((t) => S.more[t]).map((t) => `<button class="floatless ${t}" data-less="${t}" hidden>Skrýt starší střídání</button>`).join('')}
  </div>`;
}

const overlap = (a, b) => { const s = new Set(a); return b.filter((x) => s.has(x)).length / Math.max(a.length, b.length, 1); };
const cellOf = (id, slot) => { const p = S.players.get(id); return `<span class="cell">${slot ? `<small>${SLOT_LABEL[slot]}</small>` : ''}<b>${esc(p?.jersey ?? '?')}</b><i>${esc(p?.last_name ?? '')}</i></span>`; };

function teamPanel(team, evs, time) {
  const { current } = suggestionsFor(team, evs, time);
  const { strength, size } = teamSituation(S.situation, team);
  const lines = S.lines[team];
  const onIce = current ? orderLineup(current, lines, S.players) : null;
  const gk = S.goalie[team] ? S.players.get(S.goalie[team]) : null;
  const asc = sortEvents(evs.filter((e) => e.type === 'substitution' && e.team === team && e.status !== 'rejected' && e.period === S.period));
  const cur = [...asc].reverse().find((e) => seconds(e.time) <= seconds(time)); // the line-up on the rink now
  const desc = [...asc].reverse();
  const subs = cur ? [cur, ...desc.filter((e) => e !== cur)] : desc;
  const pm = shiftPlusMinus(evs);
  // collapsed: the shift on the rink and the one before it
  const shown = S.more[team] ? subs : subs.slice(0, 4); // collapsed: the shift on the rink + 3 before it
  const building = S.nsub?.team === team;
  const gkChanged = (e) => {
    const g = S.gk[e.client_id];
    const before = asc.slice(0, asc.indexOf(e)).map((x) => S.gk[x.client_id]).filter((x) => x != null).pop();
    return g != null && before != null && g !== before;
  };
  const shiftRow = (e) => { const v = pm.get(e.client_id) ?? 0;
    return `<button class="shift ${e === cur && !building ? 'cur' : ''}" data-shift="${e.client_id}" aria-label="Opravit střídání ${e.period}. ${e.time}">
      <span class="pm ${v > 0 ? 'plus' : v < 0 ? 'minus' : ''}">${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v)}${gkChanged(e) ? '<span class="gkb" title="Střídal se brankář">B</span>' : ''}</span><span class="stime">${esc(e.time)}</span>
      ${orderLineup(e.players, lines, S.players).map(({ slot, id }) => cellOf(id, slot)).join('')}</button>`; };
  return `<section class="team ${team}">
    <div class="row teamhead"><h2>${esc(SIDE[team])} · ${esc(S.header[team].short_name ?? S.header[team].name)}</h2>
      <button data-pp="${team}" class="ppbtn ${strength === 'power_play' ? 'on' : ''}" aria-pressed="${strength === 'power_play'}">Přesilovka</button></div>
    <div class="row onice-row"><span class="muted">Na hřišti:</span> ${onIce ? onIce.map(({ slot, id }) => `<span class="chip"><small>${SLOT_LABEL[slot]}</small> ${esc(jersey(id))}</span>`).join('') : `<b>${S.period}. část nezačala – přidejte první střídání</b>`}
      <span class="chip gk"><small>B</small> ${esc(gk?.jersey ?? '–')}</span></div>
    ${S.nsub?.team === team ? builder(team, time) : `<button class="newsub" data-newsub="${team}">${icon(I.plus, 24)} Přidat nové střídání${strength === 'power_play' ? ' přesilovky' : strength === 'short_handed' ? ' oslabení' : ''}</button>`}
    <div class="shifts">${shown.map(shiftRow).join('') || '<p class="muted">Zatím žádné střídání</p>'}</div>
    ${subs.length > shown.length || S.more[team] ? `<button class="morebtn" data-more="${team}">${S.more[team] ? 'Skrýt starší střídání' : `Zobrazit další střídání (${subs.length - shown.length})`}</button>` : ''}
    <button data-editlines="${team}" class="editbtn">Upravit řady</button>
  </section>`;
}

// the new substitution: starts as the players on the rink now
const baseField = (n) => teamSituation(S.situation, n.team).size; // 5, or 4 short-handed
const maxField = (n) => baseField(n) + (n.goalie == null ? 1 : 0); // without the goalie one more (6, short-handed 5)

function builder(team, time) {
  const n = S.nsub;
  const size = maxField(n);
  const ok = n.players.length >= 3 && n.players.length <= size;
  const g = n.goalie != null ? S.players.get(n.goalie) : null;
  return `<div class="builder ${team}">
    <div class="bhead"><b>Nové střídání</b> · ${esc(time)} · ${n.players.length} z ${size} · ${g ? `brankář ${esc(g.jersey)} ${esc(g.last_name)}` : '<b>bez brankáře</b>'}
      <span class="muted">– ťukněte na hráče tady a pak v sestavách na druhé straně: prohodí se</span></div>
    <div class="rp-grid five">${orderLineup(n.players, S.lines[team], S.players).map(({ slot, id }) => { const p = S.players.get(id);
      return `<button class="rp ice ${n.sel?.side === 'new' && n.sel.id === id ? 'sel' : ''}" data-nsp="${id}"><small>${SLOT_LABEL[slot]}</small><b>${esc(p?.jersey ?? '?')}</b><span>${esc(p?.last_name ?? '')}</span></button>`; }).join('')}
      ${'<span class="rp empty">+</span>'.repeat(Math.max(0, size - n.players.length))}
      ${n.goalie != null ? `<button class="rp empty extra ${n.sel?.side === 'extra' ? 'sel' : ''}" data-nextra aria-label="Místo navíc – hra bez brankáře"><b>+</b><span>bez brankáře</span></button>` : ''}</div>
    <div class="row bact">${n.sel?.side === 'new' ? `<button data-nremove>Odebrat ${esc(jersey(n.sel.id))}</button>` : ''}<button data-ncancel>Zrušit</button>
      <button class="primary" data-nsave ${ok ? '' : 'disabled'}>Zapsat střídání</button></div>
  </div>`;
}

// the other half while building: prepared lines (whole line in one tap), AI suggestion, other players
function subPicker(team, evs, time) {
  const n = S.nsub;
  const lines = S.lines[team];
  const inNew = new Set(n.players);
  const pbtn = (id, slot) => { const p = S.players.get(id);
    return `<button class="rp ${inNew.has(id) ? 'innew' : ''} ${rec.has(id) ? 'rec' : ''} ${n.sel?.side === 'pool' && n.sel.id === id ? 'sel' : ''}" data-npool="${id}">${slot ? `<small>${SLOT_LABEL[slot]}</small>` : ''}<b>${esc(p?.jersey ?? '?')}</b><span>${esc(p?.last_name ?? '')}</span></button>`; };
  const inLines = new Set(lines.flatMap(linePlayers));
  // a player in the new substitution is selected: suggest who usually came on for him
  const history = sortEvents(evs.filter((e) => e.type === 'substitution' && e.team === team && e.status !== 'rejected'));
  const recs = n.sel?.side === 'new' ? replacementsFor(history, n.sel.id, (players, id) => orderLineup(players, lines, S.players).find((x) => x.id === id)?.slot).filter((r) => !inNew.has(r.id)).slice(0, 3) : [];
  const rec = new Set(recs.map((r) => r.id));
  return `<section class="rosterpanel subpicker ${team}">
    <div class="rp-head"><b>Sestavy – ${esc(SIDE[team])} · ${esc(S.header[team].short_name ?? S.header[team].name)}</b>
      <span class="rp-q">Ťukněte na hráče, nebo vložte celou sestavu</span>
      ${n.sel?.side === 'new' ? `<span class="rechint">${recs.length ? `Za ${esc(jersey(n.sel.id))} obvykle chodí: <b>${recs.map((r) => esc(jersey(r.id))).join(', ')}</b> (zvýraznění)` : `Za ${esc(jersey(n.sel.id))} zatím nikdo nestřídal – vyberte kohokoli`}</span>` : ''}</div>
    ${lines.map((l, i) => { const pl = linePlayers(l);
      return `<div class="pline"><div class="plhead"><b>${i + 1}. řada</b><button class="small" data-nline="${i}" ${pl.length < 3 ? 'disabled' : ''}>Celá sestava</button></div>
        <div class="rp-grid five">${SLOTS.map((s) => (l[s] != null ? pbtn(l[s], s) : '<span class="rp empty">–</span>')).join('')}</div></div>`; }).join('')}
    <div class="rp-sec">Ostatní hráči</div>
    <div class="rp-grid">${field(team).filter((p) => !inLines.has(p.id)).sort((a, b) => a.jersey - b.jersey).map((p) => pbtn(p.id)).join('') || '<span class="rp empty note">Žádný hráč bez řady</span>'}</div>
    <div class="rp-sec">Brankář</div>
    <div class="rp-grid">${goalies(team).map((g) => `<button class="rp gkpick ${n.goalie === g.id ? 'ice sel' : ''}" data-ngk="${g.id}"><b>${esc(g.jersey)}</b><span>${esc(g.last_name)}</span></button>`).join('')}
      <button class="rp gkpick ${n.goalie == null ? 'ice sel' : ''}" data-ngk=""><b>–</b><span>Bez brankáře</span></button></div>
  </section>`;
}

function onNewPlayer(id) { // a player in the new substitution
  const n = S.nsub;
  if (n.sel?.side === 'pool') { if (!n.players.includes(n.sel.id)) n.players = n.players.map((x) => (x === id ? n.sel.id : x)); n.sel = null; }
  else n.sel = n.sel?.id === id ? null : { side: 'new', id };
  render();
}

function onPoolPlayer(id) { // a player in the line-ups on the other half
  const n = S.nsub;
  if (n.sel?.side === 'extra') { // the extra place: this player comes on and the goalie goes off
    if (!n.players.includes(id)) Object.assign(n, { players: [...n.players, id], goalie: null });
    n.sel = null; render(); return;
  }
  const size = maxField(n);
  if (n.players.includes(id)) n.sel = { side: 'new', id };
  else if (n.sel?.side === 'new') { n.players = n.players.map((x) => (x === n.sel.id ? id : x)); n.sel = null; }
  else if (n.players.length < size) n.players = [...n.players, id];
  else n.sel = n.sel?.id === id ? null : { side: 'pool', id };
  render();
}

// the floating hide button shows while the long list is open, except at the very bottom of the page
function floatLess() {
  const atBottom = innerHeight + scrollY >= document.documentElement.scrollHeight - 8;
  document.querySelectorAll('.floatless').forEach((b) => {
    const panel = document.querySelector(`.team.${b.dataset.less}`)?.getBoundingClientRect();
    if (panel) b.style.left = `${panel.left + panel.width / 2}px`;
    b.hidden = atBottom;
  });
}
addEventListener('scroll', floatLess, { passive: true });
addEventListener('resize', floatLess);

const lockedSubs = () => { if (isLocked()) toast(`${lockedTxt()} – střídání nejde zapsat. Odemknete zámkem vedle času.`); return isLocked(); };

// Full-screen line editor. Home: lines + goalie on the left, players on the right; away mirrored.
// Tap a player, then a place (or a place, then a player): they swap.
function editorView() {
  const { team, sel, target } = S.edit;
  const lines = S.lines[team];
  const where = new Map();
  lines.forEach((l, i) => SLOTS.forEach((s) => l[s] != null && where.set(l[s], `${i + 1}. ř. ${SLOT_LABEL[s]}`)));
  const person = (id) => (id != null ? S.players.get(id) : null);
  const linesPanel = `<section class="edpanel ${team}">
    <h3>Řady</h3>
    ${lines.map((l, i) => `<div class="lineb edit"><span class="lname">${i + 1}. řada</span>${SLOTS.map((s) => { const p = person(l[s]);
      const on = (l[s] != null && l[s] === sel) || (target?.i === i && target?.slot === s);
      return `<button class="cellb ${on ? 'sel' : ''} ${p ? '' : 'empty'}" data-slot="${team}:${i}:${s}"><small>${SLOT_LABEL[s]}</small><b>${esc(p?.jersey ?? '+')}</b><i>${esc(p?.last_name ?? 'volné')}</i></button>`; }).join('')}</div>`).join('')}
  </section>`;
  const playersPanel = `<section class="edpanel players ${team}">
    <h3>Hráči <span class="muted">– ťukněte na hráče a pak na místo v řadě</span></h3>
    <div class="rp-grid">${field(team).sort((a, b) => a.jersey - b.jersey).map((p) => `<button class="rp ${p.id === sel ? 'sel' : ''} ${where.has(p.id) ? 'inline' : ''}" data-bench="${p.id}"><b>${esc(p.jersey)}</b><span>${esc(p.last_name)}</span><small>${where.get(p.id) ?? `volný · ${p.position}`}</small></button>`).join('')}</div>
  </section>`;
  return `<div class="editorview">
    <div class="row edhead ${team}"><h2>Řady – ${esc(SIDE[team])} · ${esc(S.header[team].short_name ?? S.header[team].name)}</h2>
      ${sel != null && where.has(sel) ? `<button data-clearsel>Uvolnit ${esc(jersey(sel))} z řady</button>` : ''}
      <button data-resetlines>Obnovit z předvoleb</button><button data-editlines="${team}" class="primary">Hotovo</button></div>
    <div class="edgrid">${team === 'home' ? linesPanel + playersPanel : playersPanel + linesPanel}</div>
  </div>`;
}

function onSlot(team, i, slot) {
  const line = S.lines[team][Number(i)];
  const sel = S.edit.sel;
  if (sel != null && sel !== line[slot]) { S.lines[team] = assignSlot(S.lines[team], sel, Number(i), slot); Object.assign(S.edit, { sel: null, target: null }); saveLines(); }
  else if (line[slot] == null) S.edit.target = S.edit.target?.i === Number(i) && S.edit.target?.slot === slot ? null : { i: Number(i), slot }; // empty place first
  else Object.assign(S.edit, { sel: sel === line[slot] ? null : line[slot], target: null });
  render();
}

function onEditPlayer(id) {
  const { team, target } = S.edit;
  if (target) { S.lines[team] = assignSlot(S.lines[team], id, target.i, target.slot); Object.assign(S.edit, { sel: null, target: null }); saveLines(); }
  else S.edit.sel = S.edit.sel === id ? null : id;
  render();
}

function logRow(e) {
  const what = e.type === 'shot'
    ? `<b>${esc(RESULT[e.result])}</b> ${esc(pname(e.shooter_id))}${e.assist_id ? `, asistence ${esc(pname(e.assist_id))}` : ''}${e.strength !== 'even' ? ` · ${esc(STRENGTH[e.strength])}` : ''}`
    : `Střídání ${chips(e.players)}${e.in?.length && e.out?.length ? `<span class="muted">přišli ${e.in.map(jersey).join(', ')} · odešli ${e.out.map(jersey).join(', ')}</span>` : ''}`;
  const st = e.status === 'rejected' ? `Odmítnuto: ${esc(e.error?.message ?? e.error?.code)}` : e.status === 'pending' ? 'čeká na odeslání' : '';
  const warn = (e.warnings ?? []).includes('shot_from_own_half') ? '<div class="note">Střela z vlastní poloviny – sedí strany hřiště?</div>' : '';
  return `<div class="ev ${e.status}">
    <span class="t">${e.period}. ${esc(e.time)}</span><span class="side ${e.team}">${esc(SIDE[e.team])}</span>
    <div>${what}${warn}<div class="st">${st}</div></div>
    <div class="row">${e.status === 'rejected' ? `<button data-retry="${e.client_id}">Znovu</button>` : ''}<button data-edit="${e.client_id}">Opravit</button><button data-del="${e.client_id}" aria-label="Smazat">${icon(I.x)}</button></div>
  </div>`;
}

// ---------- substitutions ----------
function recordSub(team, players, client_id = crypto.randomUUID(), time = currentTime(), period = S.period, strength = teamSituation(S.situation, team).strength) {
  const clash = events().find((e) => e.type === 'substitution' && e.team === team && e.period === period && e.time === time && e.client_id !== client_id);
  if (clash) { toast(`${SIDE[team]} už mají v ${time} střídání. Opravte čas nebo upravte to střídání.`); return false; }
  outbox.put(S.id, client_id, subBody({ team, period, time, players, strength }));
  S.timeOverride = null;
  toast(`${SIDE[team]}: střídání ${time} zapsáno`, () => deleteEvent(client_id, true));
  pump();
  return client_id;
}

function subDialog({ team, ev = null, preset = null }) {
  const evs = events();
  const period = ev?.period ?? S.period;
  let time = ev?.time ?? (readTime('t', S.period) ?? currentTime());
  const { size } = teamSituation(S.situation, team);
  const sel = new Set(ev?.players ?? preset ?? lineupAt(evs, team, period, time) ?? []);
  Object.assign($dlg.dataset, { period, sync: ev ? '0' : '1' });
  const draw = () => {
    $dlg.className = `${team}-dlg`;
    $dlg.innerHTML = `<h2 tabindex="-1" autofocus>${ev ? 'Oprava střídání' : 'Střídání'} – ${esc(SIDE[team])}</h2>
      <div class="row">Čas ${timeBoxes('d', time)}<span class="muted">${period}. část · vybráno <b>${sel.size}</b> z ${ev ? ev.players.length : size}${sel.size === 6 ? ' · bez brankáře' : ' (6 = hra bez brankáře)'}</span></div>
      <div class="sect"><div class="grid">${field(team).map((p) => `<button data-p="${p.id}" class="${sel.has(p.id) ? 'on ice' : ''}"><span class="n">${esc(p.jersey)}</span><span class="nm">${esc(p.last_name)} · ${esc(p.position)}</span></button>`).join('')}</div></div>
      <p class="err" id="derr"></p>
      <div class="actions"><button id="cancel">Zrušit</button><button class="primary" id="ok" ${sel.size < 3 || sel.size > 6 ? 'disabled' : ''}>Zapsat</button></div>`;
    $dlg.querySelectorAll('[data-p]').forEach((b) => (b.onclick = () => { const id = Number(b.dataset.p); time = readTime('d', period) ?? time; sel.has(id) ? sel.delete(id) : sel.add(id); draw(); }));
    $dlg.querySelector('#cancel').onclick = closeDlg;
    $dlg.querySelector('#ok').onclick = () => {
      const t = readTime('d', period);
      if (!t) { $dlg.querySelector('#derr').textContent = 'Neplatný čas'; return; }
      closeDlg();
      recordSub(team, [...sel], ev?.client_id, t, period, ev?.strength ?? teamSituation(S.situation, team).strength);
    };
  };
  draw();
  $dlg.showModal();
}

// ---------- shot dialog (edit, or a player outside the line-up) ----------
function shotDialog(shot, client_id = null) {
  const s = { ...shot };
  const evs = events();
  let showAll = !!shot.showAll;
  Object.assign($dlg.dataset, { period: s.period, sync: client_id ? '0' : '1' });
  const draw = () => {
    const ice = lineupAt(evs, s.team, s.period, s.time) ?? [];
    // only the players on the rink; the full roster is one tap away for a missed substitution
    const players = (showAll || !ice.length ? field(s.team) : ice.map((id) => S.players.get(id)).filter(Boolean)).sort((a, b) => a.jersey - b.jersey);
    const grid = (key, exclude) => `<div class="grid big">${players.filter((p) => p.id !== exclude).map((p) => `<button data-${key}="${p.id}" class="${s[key] === p.id ? 'on' : ''}"><span class="n">${esc(p.jersey)}</span><span class="nm">${esc(p.last_name)}</span></button>`).join('')}</div>`;
    $dlg.className = `${s.team}-dlg`;
    $dlg.innerHTML = `<h2>${client_id ? 'Oprava střely' : 'Střela'} · ${s.period}. část ${timeBoxes('d', s.time)}</h2>
      <div class="sect"><div class="row">${['home', 'away'].map((t) => `<button data-team="${t}" class="${s.team === t ? 'on' : ''}" ${s.team === t ? 'autofocus' : ''}>${esc(SIDE[t])}</button>`).join('')}
        ${(s.team === 'home') !== (s.x >= RINK.center) ? '<span class="note err">Střela z vlastní poloviny?</span>' : ''}</div></div>
      <div class="sect"><b>Výsledek</b><div class="row">${Object.entries(RESULT).map(([k, l]) => `<button data-result="${k}" class="${s.result === k ? 'on' : ''}">${l}</button>`).join('')}</div></div>
      <div class="sect"><b>Střelec – ${ice.length && !showAll ? `na hřišti (${ice.length})` : 'celá soupiska'}</b>${grid('shooter_id')}
        ${ice.length ? `<div class="row"><button data-all>${showAll ? 'Jen hráči na hřišti' : 'Jiný hráč (celá soupiska)…'}</button></div>` : '<span class="muted">Sestava na hřišti zatím není zapsaná</span>'}</div>
      ${s.result === 'goal' ? `<div class="sect"><b>Asistence</b><div class="row"><button data-noassist class="${s.assist_id == null ? 'on' : ''}">Bez asistence</button></div>${grid('assist_id', s.shooter_id)}</div>` : ''}
      <div class="sect"><b>Poměr sil</b><div class="row">${Object.entries(STRENGTH).map(([k, l]) => `<button data-strength="${k}" class="${s.strength === k ? 'on' : ''}">${l}</button>`).join('')}</div></div>
      <p class="err" id="derr"></p>
      <div class="actions"><button id="cancel">Zrušit</button><button class="primary" id="ok" ${s.shooter_id ? '' : 'disabled'}>Uložit</button></div>`;
    const keep = (fn) => () => { s.time = readTime('d', s.period) ?? s.time; fn(); draw(); };
    $dlg.querySelectorAll('[data-team]').forEach((b) => (b.onclick = keep(() => { if (s.team !== b.dataset.team) { s.team = b.dataset.team; s.shooter_id = s.assist_id = undefined; s.strength = teamSituation(S.situation, s.team).strength; } })));
    $dlg.querySelectorAll('[data-result]').forEach((b) => (b.onclick = keep(() => (s.result = b.dataset.result))));
    $dlg.querySelectorAll('[data-strength]').forEach((b) => (b.onclick = keep(() => (s.strength = b.dataset.strength))));
    $dlg.querySelectorAll('[data-shooter_id]').forEach((b) => (b.onclick = keep(() => { s.shooter_id = Number(b.dataset.shooter_id); if (s.assist_id === s.shooter_id) s.assist_id = null; })));
    $dlg.querySelectorAll('[data-assist_id]').forEach((b) => (b.onclick = keep(() => (s.assist_id = Number(b.dataset.assist_id)))));
    $dlg.querySelector('[data-noassist]')?.addEventListener('click', keep(() => (s.assist_id = null)));
    $dlg.querySelector('[data-all]')?.addEventListener('click', keep(() => (showAll = !showAll)));
    $dlg.querySelector('#cancel').onclick = closeDlg;
    $dlg.querySelector('#ok').onclick = () => {
      const t = readTime('d', s.period);
      if (!t) { $dlg.querySelector('#derr').textContent = 'Neplatný čas'; return; }
      closeDlg();
      saveShot({ ...s, time: t }, client_id);
    };
  };
  draw();
  $dlg.showModal();
}

// ---------- edit / delete ----------
function editEvent(client_id) {
  const e = events().find((x) => x.client_id === client_id);
  if (!e) return;
  if (e.type === 'shot') shotDialog({ ...e }, client_id);
  else subDialog({ team: e.team, ev: e });
}

function deleteEvent(client_id, silent = false) {
  if (!silent && !confirm('Smazat tuto událost? Smazání je konečné.')) return;
  const item = outbox.get(client_id);
  // rejected and never stored on the server: just forget it locally
  if (item?.status === 'rejected' && !S.server.some((e) => e.client_id === client_id)) {
    outbox.items = outbox.items.filter((i) => i !== item); outbox.save();
  } else outbox.remove(S.id, client_id);
  toast('Smazáno');
  pump();
}

function closeDlg() { $dlg.close(); render(); }
$dlg.addEventListener('close', () => { $dlg.dataset.sync = '0'; render(); });

let toastTimer;
function toast(text, undo) {
  $toast.innerHTML = `<span>${esc(text)}</span>${undo ? '<button id="undo">Zpět</button>' : ''}`;
  $toast.classList.add('show');
  if (undo) $toast.querySelector('#undo').onclick = () => { $toast.classList.remove('show'); undo(); };
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => $toast.classList.remove('show'), 5000);
}

showList();
