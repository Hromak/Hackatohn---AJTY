// Suggests the next line-up of one team. It only proposes; the scorer always confirms.
// history: the team's line-ups so far (oldest first); current: on the rink now (null at period start);
// formations: the coach's preset lines from the API (may be empty).

const key = (p) => [...p].sort((a, b) => a - b).join(',');
const sim = (a, b) => {
  const s = new Set(a);
  return b.filter((x) => s.has(x)).length / Math.max(a.length, b.length);
};
const SAME = 0.6; // 3 of 5 shared players = "the same line" for learning
const DECAY = 0.85; // chosen with eval/eval-predict.js on one recorded match
const PRIOR = 0.5; // weight of the coach's preset order against one observed transition
const pct = (x) => `${Math.round(x * 100)} %`;

function linesOf(formations) {
  return formations
    .map((f) => ({ line: f.line, players: ['lw', 'c', 'rw', 'ld', 'rd'].map((s) => f[s]).filter((x) => x != null) }))
    .filter((l) => l.players.length >= 3);
}

// size: only suggest line-ups of this many players (4 when short-handed); omitted = any
export function suggest({ history, current, formations = [], size }) {
  const lines = linesOf(formations);
  const cands = [];
  const add = (players, score, why) => {
    if (current && sim(players, current) >= 0.99) return;
    if (size && players.length !== size) return;
    const c = cands.find((x) => sim(x.players, players) >= 0.8);
    if (c) { c.score += score; c.players = players; c.why[why] = (c.why[why] ?? 0) + score; }
    else cands.push({ players, score, why: { [why]: score } });
  };

  if (!current) {
    if (lines.length) add(lines[0].players, 1, 'start_formation');
    else if (history.length) add(history[0], 1, 'start_history');
  } else {
    let from = 0;
    for (let i = 1; i < history.length; i++) {
      // recent substitutions count more: coaches change lines during a match
      const w = sim(history[i - 1], current) * DECAY ** (history.length - i);
      if (sim(history[i - 1], current) >= SAME && key(history[i]) !== key(history[i - 1])) { add(history[i], w, 'history'); from += w; }
    }
    const best = lines.map((l, i) => ({ i, s: sim(l.players, current) })).sort((a, b) => b.s - a.s)[0];
    if (best && best.s >= SAME) add(lines[(best.i + 1) % lines.length].players, PRIOR, 'formation');
    if (!cands.length) {
      // Nothing learned yet: the line-up that has rested longest.
      const seen = new Map();
      history.forEach((p, i) => seen.set(key(p), { p, i }));
      [...seen.values()].sort((a, b) => a.i - b.i).forEach(({ p }, r) => add(p, 0.5 / (r + 1), 'rested'));
    }
    cands.from = from;
  }

  const total = cands.reduce((a, c) => a + c.score, 0);
  return cands
    .sort((a, b) => b.score - a.score)
    .slice(0, 3)
    .map((c) => ({ players: c.players, share: c.score / total, reason: reason(c, lines, cands.from) }));
}

function reason(c, lines, from) {
  const line = lines.find((l) => sim(l.players, c.players) >= 0.8);
  const name = line ? `${line.line}. řada` : 'pětka z historie';
  if (c.why.start_formation) return `Začátek části: ${name} z předvoleb trenéra.`;
  if (c.why.start_history) return 'Začátek části: stejná pětka jako na začátku utkání.';
  if (c.why.history) return `${name}: po této pětce šla v ${pct(c.why.history / from)} střídání.`;
  if (c.why.formation) return `${name}: další v pořadí podle předvoleb (zatím bez historie).`;
  return `${name}: nejdéle nebyla na hřišti.`;
}

// Who usually came on when `playerId` went off: over consecutive substitutions of one team in the same
// period, each player coming on gets 1 / (players coming on), so a single swap counts more than a line change.
// slotOf(players, id) -> 'lw' | 'c' | …: the one who took the same position counts fully even in a line change.
// subs: [{ period, players }] oldest first. Returns [{ id, score }] best first.
export function replacementsFor(subs, playerId, slotOf = null) {
  const score = new Map();
  for (let i = 1; i < subs.length; i++) {
    const prev = subs[i - 1], next = subs[i];
    if (prev.period !== next.period || !prev.players.includes(playerId) || next.players.includes(playerId)) continue;
    const came = next.players.filter((x) => !prev.players.includes(x));
    const pos = slotOf?.(prev.players, playerId);
    for (const id of came) score.set(id, (score.get(id) ?? 0) + (pos && slotOf(next.players, id) === pos ? 1 : 1 / came.length));
  }
  return [...score].map(([id, s]) => ({ id, score: s })).sort((a, b) => b.score - a.score || a.id - b.id);
}
