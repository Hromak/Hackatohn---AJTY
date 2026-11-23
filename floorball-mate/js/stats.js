// Shot analysis for the map: filters and a summary. Pure functions, no DOM.
// Measured on podklady/hriste-890x501.png: goal lines at x = 76 and 813, goal centre y = 250, 22.25 px = 1 m (40 m rink).

const PX_PER_M = 890 / 40;
const GOAL = { home: { x: 813, y: 250 }, away: { x: 76, y: 250 } }; // the goal each team attacks
export const SLOT_M = 8;

const vec = (s) => {
  const g = GOAL[s.team];
  return { dx: s.team === 'home' ? g.x - s.x : s.x - g.x, dy: s.y - g.y };
};

export const distanceM = (s) => { const { dx, dy } = vec(s); return Math.hypot(dx, dy) / PX_PER_M; };

// "Slot" (dangerous zone): in front of the goal line, within 8 m and at most 45° off the goal's axis.
// A transparent rule instead of xG: one recorded match is too little data to calibrate xG honestly.
export function inSlot(s) {
  const { dx, dy } = vec(s);
  return dx > 0 && Math.abs(dy) <= dx && Math.hypot(dx, dy) <= SLOT_M * PX_PER_M;
}

// Each group takes one value or a list (any of them matches); missing or empty list = all.
const list = (one, many) => (many?.length ? many : one != null ? [one] : null);

// f: { periods|period, team|teams, results, strengths|strength, players|player }
export function filterShots(events, f) {
  const periods = list(f.period, f.periods), teams = list(f.team, f.teams), results = list(null, f.results);
  const strengths = list(f.strength, f.strengths), players = list(f.player, f.players);
  return events.filter((e) => e.type === 'shot' && e.status !== 'rejected'
    && (!periods || periods.includes(e.period))
    && (!teams || teams.includes(e.team))
    && (!results || results.includes(e.result))
    && (!strengths || strengths.includes(e.strength))
    && (!players || players.includes(e.shooter_id)));
}

// Zápis filter. kinds: 'substitution' | 'shot' (all shots) | a shot result ('goal', 'on_goal', 'post', 'miss')
export function filterLog(events, f) {
  const periods = list(f.period, f.periods), teams = list(f.team, f.teams), kinds = list(f.kind, f.kinds);
  const kindOf = (e, k) => (k === 'substitution' || k === 'shot' ? e.type === k : e.type === 'shot' && e.result === k);
  return events.filter((e) => (!periods || periods.includes(e.period))
    && (!teams || teams.includes(e.team))
    && (!kinds || kinds.some((k) => kindOf(e, k))));
}

const sec = (t) => Number(t.slice(0, 2)) * 60 + Number(t.slice(3));

// Time on the rink in seconds per player, from substitutions only (they never contain goalies).
// A line-up plays from its substitution until the team's next one in that period; the last one until
// endOf(period). f: { periods, strengths } as in filterShots (a segment's strength is its substitution's).
export function timeOnIce(events, f, endOf) {
  const periods = list(f.period, f.periods), strengths = list(f.strength, f.strengths);
  const subs = events.filter((e) => e.type === 'substitution' && e.status !== 'rejected')
    .sort((a, b) => a.period - b.period || sec(a.time) - sec(b.time) || (a.seq ?? 0) - (b.seq ?? 0));
  const toi = new Map();
  subs.forEach((s, i) => {
    if ((periods && !periods.includes(s.period)) || (strengths && !strengths.includes(s.strength))) return;
    const next = subs.slice(i + 1).find((n) => n.team === s.team && n.period === s.period);
    const length = Math.max(0, (next ? sec(next.time) : endOf(s.period)) - sec(s.time));
    for (const id of s.players) toi.set(id, (toi.get(id) ?? 0) + length);
  });
  return toi;
}

// Plus/minus of every substitution (shift): goals for minus goals against while that line-up was on,
// i.e. from its time until the team's next substitution in the same period (or the end of the period).
export function shiftPlusMinus(events) {
  const ok = events.filter((e) => e.status !== 'rejected');
  const subs = ok.filter((e) => e.type === 'substitution').sort((a, b) => a.period - b.period || sec(a.time) - sec(b.time) || (a.seq ?? 0) - (b.seq ?? 0));
  const goals = ok.filter((e) => e.type === 'shot' && e.result === 'goal');
  const pm = new Map();
  subs.forEach((s, i) => {
    const next = subs.slice(i + 1).find((n) => n.team === s.team && n.period === s.period);
    const from = sec(s.time), to = next ? sec(next.time) : Infinity;
    pm.set(s.client_id, goals.filter((g) => g.period === s.period && sec(g.time) >= from && sec(g.time) < to)
      .reduce((a, g) => a + (g.team === s.team ? 1 : -1), 0));
  });
  return pm;
}

const pct = (a, b) => (b ? Math.round((100 * a) / b) : 0);

export function summarize(shots) {
  const goals = shots.filter((s) => s.result === 'goal').length;
  const onTarget = shots.filter((s) => s.result === 'goal' || s.result === 'on_goal').length;
  const slot = shots.filter(inSlot).length;
  const avgDist = shots.length ? Math.round((10 * shots.reduce((a, s) => a + distanceM(s), 0)) / shots.length) / 10 : 0;
  return { shots: shots.length, onTarget, goals, shootingPct: pct(goals, shots.length), slot, slotPct: pct(slot, shots.length), avgDist };
}

// +/− per player: the shift plus/minus added to everyone in that line-up. f: { periods } as in filterShots.
export function playerPlusMinus(events, f) {
  const periods = list(f.period, f.periods);
  const shift = shiftPlusMinus(events);
  const pm = new Map();
  for (const s of events) {
    if (s.type !== 'substitution' || s.status === 'rejected' || (periods && !periods.includes(s.period))) continue;
    for (const id of s.players) pm.set(id, (pm.get(id) ?? 0) + (shift.get(s.client_id) ?? 0));
  }
  return pm;
}
