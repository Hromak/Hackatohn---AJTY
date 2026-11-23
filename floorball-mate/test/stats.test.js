import { test } from 'node:test';
import assert from 'node:assert/strict';
import { distanceM, inSlot, filterShots, summarize, filterLog, timeOnIce, shiftPlusMinus, playerPlusMinus } from '../js/stats.js';

const shot = (o) => ({ type: 'shot', team: 'home', period: 1, time: '01:00', x: 700, y: 250, result: 'miss', strength: 'even', shooter_id: 1, status: 'done', ...o });

test('distance is measured to the goal the team attacks (home right, away left)', () => {
  assert.equal(Math.round(distanceM(shot({ x: 813 - 89, y: 250 }))), 4);
  assert.equal(Math.round(distanceM(shot({ team: 'away', x: 76 + 178, y: 250 }))), 8);
});

test('slot = within 8 m and inside the 45° cone in front of the goal', () => {
  assert.equal(inSlot(shot({ x: 740, y: 250 })), true);
  assert.equal(inSlot(shot({ x: 760, y: 320 })), false, 'too wide an angle');
  assert.equal(inSlot(shot({ x: 600, y: 250 })), false, 'too far');
  assert.equal(inSlot(shot({ x: 830, y: 250 })), false, 'behind the goal line');
  assert.equal(inSlot(shot({ team: 'away', x: 120, y: 260 })), true);
});

test('filterShots by period, team, result, strength and player; ignores substitutions and rejected', () => {
  const evs = [
    shot({ period: 1, result: 'goal' }), shot({ period: 2, team: 'away', x: 150 }), shot({ period: 4, strength: 'power_play', shooter_id: 7 }),
    { type: 'substitution', team: 'home', period: 1, time: '00:00', players: [1] }, shot({ status: 'rejected' }),
  ];
  assert.equal(filterShots(evs, {}).length, 3);
  assert.equal(filterShots(evs, { period: 4 }).length, 1);
  assert.equal(filterShots(evs, { team: 'away' }).length, 1);
  assert.equal(filterShots(evs, { results: ['goal'] }).length, 1);
  assert.equal(filterShots(evs, { strength: 'power_play' }).length, 1);
  assert.equal(filterShots(evs, { player: 7 }).length, 1);
});

test('filterLog by period, kind (substitutions, all shots or one result) and team', () => {
  const sub = { type: 'substitution', team: 'away', period: 1, time: '00:00', players: [1] };
  const evs = [shot({ result: 'goal' }), shot({ period: 2, result: 'miss' }), shot({ team: 'away', result: 'goal' }), sub];
  assert.equal(filterLog(evs, {}).length, 4);
  assert.equal(filterLog(evs, { period: 1 }).length, 3);
  assert.equal(filterLog(evs, { kind: 'substitution' }).length, 1);
  assert.equal(filterLog(evs, { kind: 'shot' }).length, 3);
  assert.equal(filterLog(evs, { kind: 'goal', period: 1 }).length, 2);
  assert.equal(filterLog(evs, { kind: 'goal', team: 'home' }).length, 1);
});

test('filterLog with several values per group (e.g. miss + on goal, periods 1 and 2)', () => {
  const evs = [shot({ result: 'miss' }), shot({ result: 'on_goal', period: 2 }), shot({ result: 'goal' }), shot({ result: 'post', period: 3 }),
    { type: 'substitution', team: 'home', period: 1, time: '00:00', players: [1] }];
  assert.equal(filterLog(evs, { kinds: ['miss', 'on_goal'] }).length, 2);
  assert.equal(filterLog(evs, { kinds: ['substitution', 'goal'] }).length, 2);
  assert.equal(filterLog(evs, { periods: [1, 2], kinds: ['miss', 'on_goal', 'post'] }).length, 2);
  assert.equal(filterLog(evs, { teams: ['home', 'away'] }).length, 5);
  assert.equal(filterLog(evs, { kinds: [] }).length, 5, 'empty selection = all');
});

test('filterShots takes several values per group: periods, results, strengths, players', () => {
  const evs = [shot({ period: 1, shooter_id: 1 }), shot({ period: 2, shooter_id: 2, result: 'goal' }), shot({ period: 3, shooter_id: 3, strength: 'power_play' })];
  assert.equal(filterShots(evs, { periods: [1, 2] }).length, 2);
  assert.equal(filterShots(evs, { players: [1, 3] }).length, 2);
  assert.equal(filterShots(evs, { strengths: ['even'] }).length, 2);
  assert.equal(filterShots(evs, { results: ['goal'], periods: [1, 2] }).length, 1);
  assert.equal(filterShots(evs, { players: [], periods: [] }).length, 3, 'empty = all');
});

const sub = (team, period, time, players, strength = 'even') => ({ type: 'substitution', team, period, time, players, strength, status: 'done' });

test('timeOnIce: a line-up counts from its substitution until the next one of that team, then stops', () => {
  const evs = [sub('home', 1, '00:00', [1, 2, 3]), sub('away', 1, '00:30', [9, 10, 11]), sub('home', 1, '01:00', [1, 4, 5]), sub('home', 1, '01:30', [6, 7, 8])];
  const t = timeOnIce(evs, {}, () => 120);
  assert.equal(t.get(1), 90, 'on in both line-ups: 0–60 and 60–90');
  assert.equal(t.get(2), 60);
  assert.equal(t.get(4), 30);
  assert.equal(t.get(6), 30, 'last line-up runs until the end of the period');
  assert.equal(t.get(9), 90);
});

test('timeOnIce respects the period and strength filters and ignores rejected events', () => {
  const evs = [sub('home', 1, '00:00', [1]), sub('home', 2, '00:00', [1, 2], 'power_play'), sub('home', 2, '00:40', [3]), { ...sub('home', 2, '00:20', [4]), status: 'rejected' }];
  const end = (p) => (p === 1 ? 100 : 60);
  assert.equal(timeOnIce(evs, { periods: [2] }, end).get(1), 40);
  assert.equal(timeOnIce(evs, { strengths: ['power_play'] }, end).get(2), 40);
  assert.equal(timeOnIce(evs, { strengths: ['power_play'] }, end).get(3), undefined);
  assert.equal(timeOnIce(evs, {}, end).get(1), 140);
  assert.equal(timeOnIce(evs, {}, end).get(4), undefined);
});

test('summarize counts shots, on target (saved + goals), goals and percentages', () => {
  const s = summarize([shot({ result: 'goal', x: 740 }), shot({ result: 'on_goal' }), shot({ result: 'post', x: 600 }), shot({ result: 'miss', x: 500 })]);
  assert.equal(s.shots, 4);
  assert.equal(s.onTarget, 2);
  assert.equal(s.goals, 1);
  assert.equal(s.shootingPct, 25);
  assert.equal(s.slot, 2);
  assert.equal(s.slotPct, 50);
  assert.deepEqual(summarize([]), { shots: 0, onTarget: 0, goals: 0, shootingPct: 0, slot: 0, slotPct: 0, avgDist: 0 });
});

test('shiftPlusMinus: goals for and against while a line-up was on the rink', () => {
  const s = (id, team, period, time, players) => ({ client_id: id, type: 'substitution', team, period, time, players, status: 'done' });
  const goal = (team, period, time) => shot({ team, period, time, result: 'goal' });
  const evs = [
    s('h1', 'home', 1, '00:00', [1]), s('a1', 'away', 1, '00:00', [9]), goal('home', 1, '00:30'), goal('away', 1, '00:50'),
    s('h2', 'home', 1, '01:00', [2]), goal('home', 1, '01:10'), goal('home', 1, '01:20'), shot({ team: 'home', period: 1, time: '01:30', result: 'miss' }),
    s('h3', 'home', 2, '00:00', [3]), { ...goal('away', 2, '00:10'), status: 'rejected' },
  ];
  const pm = shiftPlusMinus(evs);
  assert.equal(pm.get('h1'), 0, '+1 −1');
  assert.equal(pm.get('h2'), 2, 'runs to the end of the period');
  assert.equal(pm.get('a1'), -2, 'away: 1 for, 3 against');
  assert.equal(pm.get('h3'), 0, 'rejected goal does not count');
});

test('playerPlusMinus: goals for and against while the player was on the rink, per period filter', () => {
  const s = (id, team, period, time, players) => ({ client_id: id, type: 'substitution', team, period, time, players, status: 'done' });
  const goal = (team, period, time) => shot({ team, period, time, result: 'goal' });
  const evs = [
    s('h1', 'home', 1, '00:00', [1, 2]), s('a1', 'away', 1, '00:00', [9]), goal('home', 1, '00:30'),
    s('h2', 'home', 1, '01:00', [1, 3]), goal('away', 1, '01:10'), goal('home', 1, '01:20'),
    s('h3', 'home', 2, '00:00', [2]), goal('home', 2, '00:10'),
  ];
  const pm = playerPlusMinus(evs, {});
  assert.equal(pm.get(1), 1, '+1 in the first shift, 0 in the second');
  assert.equal(pm.get(2), 2);
  assert.equal(pm.get(3), 0);
  assert.equal(pm.get(9), -1, '1 for, 2 against');
  assert.equal(playerPlusMinus(evs, { periods: [2] }).get(2), 1);
  assert.equal(playerPlusMinus(evs, { periods: [2] }).get(1), undefined);
});
