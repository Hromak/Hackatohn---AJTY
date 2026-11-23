import { test } from 'node:test';
import assert from 'node:assert/strict';
import { suggest, replacementsFor } from '../js/predict.js';

const L1 = [1, 2, 3, 4, 5], L2 = [6, 7, 8, 9, 10], L3 = [11, 12, 13, 14, 15];
const formations = [
  { line: 1, lw: 1, c: 2, rw: 3, ld: 4, rd: 5 },
  { line: 2, lw: 6, c: 7, rw: 8, ld: 9, rd: 10 },
  { line: 3, lw: 11, c: 12, rw: 13, ld: 14, rd: 15 },
];
const key = (p) => [...p].sort((a, b) => a - b).join(',');

test('period start without history suggests line 1 of the formations', () => {
  const s = suggest({ history: [], current: null, formations });
  assert.equal(key(s[0].players), key(L1));
});

test('with formations and no history the next line follows the current one', () => {
  const s = suggest({ history: [L1], current: L1, formations });
  assert.equal(key(s[0].players), key(L2));
  const s3 = suggest({ history: [L1, L2, L3], current: L3, formations });
  assert.equal(key(s3[0].players), key(L1));
});

test('without formations and without history there is nothing to suggest', () => {
  assert.deepEqual(suggest({ history: [], current: null, formations: [] }), []);
});

test('without formations it learns the rotation from the history', () => {
  const history = [L1, L2, L3, L1, L2, L3, L1];
  const s = suggest({ history, current: L1, formations: [] });
  assert.equal(key(s[0].players), key(L2));
});

test('history beats the formations when the coach plays differently', () => {
  const history = [L1, L3, L1, L3, L1];
  const s = suggest({ history, current: L1, formations });
  assert.equal(key(s[0].players), key(L3));
});

test('suggestions are distinct, never the current line, at most three, with reasons', () => {
  const history = [L1, L2, L3, L1, L2, L3, L1];
  const s = suggest({ history, current: L1, formations });
  assert.ok(s.length <= 3);
  assert.equal(new Set(s.map((x) => key(x.players))).size, s.length);
  assert.ok(s.every((x) => key(x.players) !== key(L1)));
  assert.ok(s.every((x) => typeof x.reason === 'string' && x.reason.length > 0));
  const total = s.reduce((a, x) => a + x.share, 0);
  assert.ok(total <= 1.0001);
});

test('a new pattern late in the match wins over old history', () => {
  // the coach rotated three lines, then switches to two new ones that alternate
  // B is line 2 with one player changed, as in the real match
  const A = [1, 2, 13, 11, 16], B = [6, 7, 8, 9, 12];
  const old = [L1, L2, L3, L1, L2, L3, L1, L2, L3, L1, L2, L3];
  const s = suggest({ history: [...old, A, B, A, B, A, B], current: B, formations });
  assert.equal(key(s[0].players), key(A));
});

test('short-handed: only line-ups of four are suggested, learned from earlier penalties', () => {
  const PK = [1, 4, 5, 9];
  const history = [L1, L2, PK, L3, L1];
  const s = suggest({ history, current: L1, formations, size: 4 });
  assert.ok(s.length > 0);
  assert.ok(s.every((x) => x.players.length === 4));
  assert.equal(key(s[0].players), key(PK));
  assert.deepEqual(suggest({ history: [L1], current: L1, formations, size: 4 }), []);
});

test('a slightly changed line still counts as the same line for learning', () => {
  const L1b = [1, 2, 3, 4, 16];
  const history = [L1, L2, L1, L2, L1b];
  const s = suggest({ history, current: L1b, formations: [] });
  assert.equal(key(s[0].players), key(L2));
});

test('replacementsFor: who most often came on when this player went off', () => {
  const sub = (period, players) => ({ period, players });
  const subs = [sub(1, [1, 2, 3, 4, 5]), sub(1, [6, 2, 3, 4, 5]), sub(1, [1, 2, 3, 4, 5]), sub(1, [6, 2, 3, 4, 5]), sub(1, [1, 2, 3, 4, 5]), sub(1, [7, 2, 3, 4, 5])];
  const r = replacementsFor(subs, 1);
  assert.deepEqual(r.map((x) => x.id), [6, 7]);
  assert.equal(r[0].score, 2);
});

test('replacementsFor: a whole-line change counts less than a single swap; periods are not joined', () => {
  const subs = [{ period: 1, players: [1, 2, 3, 4, 5] }, { period: 1, players: [6, 7, 8, 9, 10] }, { period: 2, players: [11, 2, 3, 4, 5] }];
  const r = replacementsFor(subs, 1);
  assert.equal(r.length, 5);
  assert.ok(r.every((x) => Math.abs(x.score - 0.2) < 1e-9));
  assert.deepEqual(replacementsFor(subs, 99), []);
});

test('replacementsFor: in a whole-line change the player who took the same position counts fully', () => {
  const subs = [{ period: 1, players: [1, 2, 3, 4, 5] }, { period: 1, players: [6, 7, 8, 9, 10] }];
  const slot = { 1: 'lw', 2: 'c', 3: 'rw', 4: 'ld', 5: 'rd', 6: 'lw', 7: 'c', 8: 'rw', 9: 'ld', 10: 'rd' };
  const r = replacementsFor(subs, 2, (players, id) => slot[id]);
  assert.equal(r[0].id, 7);
  assert.equal(r[0].score, 1);
  assert.ok(r.slice(1).every((x) => Math.abs(x.score - 0.2) < 1e-9));
});
