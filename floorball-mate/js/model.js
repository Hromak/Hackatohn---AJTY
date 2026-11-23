// Pure helpers for event bodies and match state. No DOM, no network.

export const RINK = { w: 890, h: 501, center: 445 };

// "742" / "7:42" / "07:42" -> "07:42"; anything else -> null.
export function parseTime(input) {
  const s = String(input ?? '').trim();
  let m = s.match(/^(\d{1,2}):(\d{2})$/);
  if (!m) {
    const d = s.match(/^\d{1,4}$/) ? s.padStart(4, '0') : null;
    m = d && [null, d.slice(0, 2), d.slice(2)];
  }
  if (!m || Number(m[2]) > 59) return null;
  return `${m[1].padStart(2, '0')}:${m[2]}`;
}

export const seconds = (t) => Number(t.slice(0, 2)) * 60 + Number(t.slice(3));
export const mmss = (s) => `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;

export function sortEvents(events) {
  return [...events].sort(
    (a, b) => a.period - b.period || seconds(a.time) - seconds(b.time) || (a.seq ?? Infinity) - (b.seq ?? Infinity),
  );
}

// Field players of `team` on the rink at (period, time); null before the first substitution of that period.
export function lineupAt(events, team, period, time) {
  let found = null;
  for (const e of sortEvents(events)) {
    if (e.type !== 'substitution' || e.team !== team || e.period !== period) continue;
    if (seconds(e.time) > seconds(time)) break;
    found = e.players;
  }
  return found;
}

// The match clock stops often, so the app never runs its own: it offers the last recorded time + 5 s.
export function nextTime(events, period, lengthSec) {
  const times = events.filter((e) => e.period === period).map((e) => seconds(e.time));
  return times.length ? mmss(Math.min(Math.max(...times) + 5, lengthSec - 1)) : '00:00';
}

// ▲▼ buttons: move by deltaSec (seconds carry into minutes), clamped to the period.
export function stepTime(t, deltaSec, lengthSec) {
  return mmss(Math.min(Math.max(seconds(t) + deltaSec, 0), lengthSec - 1));
}

export const SLOTS = ['lw', 'c', 'rw', 'ld', 'rd'];
export const SLOT_LABEL = { lw: 'LK', c: 'C', rw: 'PK', ld: 'LO', rd: 'PO', x: '+' };

// Line-up in a fixed order LK C PK LO PO: slot from the formations, else forwards/defenders by jersey.
export function orderLineup(lineup, formations, players) {
  const slotOf = new Map();
  for (const f of formations) for (const s of SLOTS) if (f[s] != null && !slotOf.has(f[s])) slotOf.set(f[s], s);
  const taken = new Map();
  const rest = [];
  for (const id of lineup) {
    const s = slotOf.get(id);
    if (s && !taken.has(s)) taken.set(s, id); else rest.push(id);
  }
  const byJersey = (a, b) => (players.get(a)?.jersey ?? 0) - (players.get(b)?.jersey ?? 0);
  const free = (list) => list.find((s) => !taken.has(s));
  const overflow = [];
  for (const id of rest.sort(byJersey)) {
    const s = free(players.get(id)?.position === 'D' ? ['ld', 'rd'] : ['lw', 'c', 'rw']);
    if (s) taken.set(s, id); else overflow.push(id);
  }
  for (const id of overflow) taken.set(free(SLOTS) ?? `x${id}`, id);
  return [...taken].map(([slot, id]) => ({ slot: slot.startsWith('x') ? 'x' : slot, id }))
    .sort((a, b) => (SLOTS.indexOf(a.slot) + 1 || 9) - (SLOTS.indexOf(b.slot) + 1 || 9));
}

// Prepared lines in the API's formation shape { line, lw, c, rw, ld, rd }. The API has no write for
// formations, so edited lines live only on this tablet.
export function initLines(formations) {
  const lines = formations.map((f) => ({ line: f.line, ...Object.fromEntries(SLOTS.map((s) => [s, f[s] ?? null])) }));
  while (lines.length < 3) lines.push({ line: lines.length + 1, ...Object.fromEntries(SLOTS.map((s) => [s, null])) });
  return lines;
}
export const linePlayers = (l) => SLOTS.map((s) => l[s]).filter((x) => x != null);

// Tap-to-swap: put player `id` into lines[li][slot]. If the player was in another slot, the two swap;
// a player displaced by someone from the bench goes to the bench.
export function assignSlot(lines, id, li, slot) {
  const next = lines.map((l) => ({ ...l }));
  const from = next.flatMap((l, i) => SLOTS.filter((s) => l[s] === id).map((s) => [i, s]))[0];
  const occupant = next[li][slot];
  if (from) next[from[0]][from[1]] = occupant;
  next[li][slot] = id;
  return next;
}
export function clearSlot(lines, li, slot) {
  const next = lines.map((l) => ({ ...l }));
  next[li][slot] = null;
  return next;
}

// situation: 'even' | 'pp_home' | 'pp_away' (power play of that team; the other one plays with 4)
export function teamSituation(situation, team) {
  if (situation === 'even') return { strength: 'even', size: 5 };
  return situation === `pp_${team}` ? { strength: 'power_play', size: 5 } : { strength: 'short_handed', size: 4 };
}

// What the scorer sees: server events with queued local changes applied, sorted.
export function mergeEvents(serverEvents, outboxItems) {
  const view = new Map(serverEvents.map((e) => [e.client_id, { ...e, status: 'done', error: null }]));
  for (const i of outboxItems) {
    if (i.status === 'done' && i.op === 'put' && i.event) view.set(i.client_id, { ...i.event, status: 'done', error: null });
    else if (i.op === 'delete' && i.status !== 'rejected') view.delete(i.client_id);
    else if (i.op === 'put' && i.status !== 'done')
      view.set(i.client_id, { ...view.get(i.client_id), ...i.body, client_id: i.client_id, status: i.status, error: i.error });
  }
  return sortEvents([...view.values()]);
}

const clamp =(v, max) => Math.min(max, Math.max(0, Math.round(v)));

export function shotBody(s) {
  const goal = s.result === 'goal';
  const body = {
    type: 'shot', team: s.team, period: s.period, time: s.time,
    x: clamp(s.x, RINK.w), y: clamp(s.y, RINK.h),
    result: s.result, strength: s.strength ?? 'even',
    shooter_id: s.shooter_id, goalkeeper_id: s.goalkeeper_id ?? null,
    assist_id: goal ? (s.assist_id ?? null) : null,
  };
  if (goal && s.on_ice) body.on_ice = s.on_ice;
  return body;
}

export function subBody(s) {
  return {
    type: 'substitution', team: s.team, period: s.period, time: s.time,
    players: s.players, strength: s.strength ?? 'even', empty_net: s.players.length === 6,
  };
}
