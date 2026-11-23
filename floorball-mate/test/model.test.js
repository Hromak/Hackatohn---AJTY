import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseTime, seconds, lineupAt, shotBody, subBody, sortEvents, mergeEvents, nextTime, teamSituation, stepTime, orderLineup, initLines, assignSlot, clearSlot, linePlayers } from '../js/model.js';

test('parseTime accepts what a scorer types', () => {
  assert.equal(parseTime('742'), '07:42');
  assert.equal(parseTime('7:42'), '07:42');
  assert.equal(parseTime('07:42'), '07:42');
  assert.equal(parseTime('0'), '00:00');
  assert.equal(parseTime('1959'), '19:59');
});

test('parseTime rejects nonsense', () => {
  assert.equal(parseTime('7:60'), null);
  assert.equal(parseTime('abc'), null);
  assert.equal(parseTime(''), null);
  assert.equal(parseTime('12345'), null);
});

test('seconds converts mm:ss', () => {
  assert.equal(seconds('07:42'), 462);
});

const sub = (team, period, time, players, seq) => ({ type: 'substitution', team, period, time, players, seq });

test('lineupAt returns the last substitution of the team up to that moment', () => {
  const evs = [
    sub('home', 1, '00:00', [1, 2, 3, 4, 5], 1),
    sub('away', 1, '00:30', [20, 21, 22, 23, 24], 2),
    sub('home', 1, '01:10', [6, 7, 3, 4, 5], 3),
    sub('home', 2, '00:00', [9, 10, 11, 12, 13], 4),
  ];
  assert.deepEqual(lineupAt(evs, 'home', 1, '01:00'), [1, 2, 3, 4, 5]);
  assert.deepEqual(lineupAt(evs, 'home', 1, '01:10'), [6, 7, 3, 4, 5]);
  assert.deepEqual(lineupAt(evs, 'home', 2, '05:00'), [9, 10, 11, 12, 13]);
  assert.equal(lineupAt(evs, 'away', 1, '00:10'), null);
});

test('lineupAt does not carry a line-up over into the next period', () => {
  const evs = [sub('home', 1, '00:00', [1, 2, 3, 4, 5], 1)];
  assert.equal(lineupAt(evs, 'home', 2, '03:00'), null);
});

test('sortEvents orders by period, time, then delivery order', () => {
  const evs = [sub('home', 2, '00:00', [1], 1), sub('home', 1, '05:00', [2], 3), sub('away', 1, '05:00', [3], 2)];
  assert.deepEqual(sortEvents(evs).map((e) => e.players[0]), [3, 2, 1]);
});

test('shotBody sends assist and on_ice only with a goal', () => {
  const base = { team: 'home', period: 1, time: '07:42', x: 612, y: 233, shooter_id: 6, goalkeeper_id: 36, strength: 'even' };
  const miss = shotBody({ ...base, result: 'miss', assist_id: 9, on_ice: { home: [1], away: [2] } });
  assert.equal(miss.assist_id, null);
  assert.equal('on_ice' in miss, false);
  const goal = shotBody({ ...base, result: 'goal', assist_id: 9, on_ice: { home: [1], away: [2] } });
  assert.equal(goal.assist_id, 9);
  assert.deepEqual(goal.on_ice, { home: [1], away: [2] });
  assert.equal(goal.type, 'shot');
});

test('shotBody rounds coordinates and keeps them inside the rink', () => {
  const b = shotBody({ team: 'home', period: 1, time: '00:10', x: 890.6, y: -3.2, result: 'miss', shooter_id: 1 });
  assert.equal(b.x, 890);
  assert.equal(b.y, 0);
});

test('mergeEvents shows local changes on top of what the server has', () => {
  const server = [
    { client_id: 'a', type: 'shot', team: 'home', period: 1, time: '01:00', result: 'miss', seq: 1 },
    { client_id: 'b', type: 'shot', team: 'home', period: 1, time: '02:00', result: 'miss', seq: 2 },
    { client_id: 'c', type: 'shot', team: 'away', period: 1, time: '03:00', result: 'miss', seq: 3 },
  ];
  const outbox = [
    { client_id: 'a', op: 'put', status: 'pending', body: { type: 'shot', team: 'home', period: 1, time: '01:00', result: 'goal' } },
    { client_id: 'b', op: 'delete', status: 'pending', body: null },
    { client_id: 'd', op: 'put', status: 'rejected', error: { code: 'forced_rejection' }, body: { type: 'shot', team: 'away', period: 1, time: '00:30', result: 'miss' } },
  ];
  const v = mergeEvents(server, outbox);
  assert.deepEqual(v.map((e) => e.client_id), ['d', 'a', 'c']);
  assert.equal(v[1].result, 'goal');
  assert.equal(v[1].status, 'pending');
  assert.equal(v[0].status, 'rejected');
  assert.equal(v[0].error.code, 'forced_rejection');
  assert.equal(v[2].status, 'done');
});

test('nextTime offers the last recorded time of the period plus 5 s', () => {
  const evs = [sub('home', 1, '00:00', [1], 1), sub('away', 1, '07:40', [2], 2), sub('home', 1, '03:00', [3], 3), sub('home', 2, '01:00', [4], 4)];
  assert.equal(nextTime(evs, 1, 1200), '07:45');
  assert.equal(nextTime(evs, 2, 1200), '01:05');
  assert.equal(nextTime(evs, 3, 1200), '00:00');
});

test('nextTime rolls seconds over into the next minute and stays inside the period', () => {
  assert.equal(nextTime([sub('home', 1, '07:58', [1], 1)], 1, 1200), '08:03');
  assert.equal(nextTime([sub('home', 1, '19:57', [1], 1)], 1, 1200), '19:59');
});

test('stepTime moves by seconds with carry over minutes and stays inside the period', () => {
  assert.equal(stepTime('07:58', 5, 1200), '08:03');
  assert.equal(stepTime('08:03', -5, 1200), '07:58');
  assert.equal(stepTime('07:58', 60, 1200), '08:58');
  assert.equal(stepTime('00:03', -5, 1200), '00:00');
  assert.equal(stepTime('19:58', 5, 1200), '19:59');
  assert.equal(stepTime('04:30', 60, 300), '04:59');
});

test('seconds arrows by 10 s and +5 s after a shot carry over minutes correctly', () => {
  assert.equal(stepTime('11:50', 10, 1200), '12:00');
  assert.equal(stepTime('12:00', -10, 1200), '11:50');
  assert.equal(stepTime('00:05', -10, 1200), '00:00');
  assert.equal(stepTime('11:58', 5, 1200), '12:03');
  assert.equal(stepTime('19:57', 5, 1200), '19:59');
});

const P = (id, jersey, position) => ({ id, jersey, position });
const players = new Map([P(1, 10, 'F'), P(2, 11, 'F'), P(3, 12, 'F'), P(4, 2, 'D'), P(5, 3, 'D'), P(6, 4, 'D'), P(7, 5, 'F')].map((p) => [p.id, p]));

test('orderLineup puts players in fixed slots LK C PK LO PO from the formations', () => {
  const formations = [{ line: 1, lw: 3, c: 1, rw: 2, ld: 5, rd: 4 }];
  assert.deepEqual(orderLineup([1, 2, 3, 4, 5], formations, players).map((x) => `${x.slot}:${x.id}`), ['lw:3', 'c:1', 'rw:2', 'ld:5', 'rd:4']);
});

test('orderLineup without formations: forwards by jersey to LK C PK, defenders to LO PO', () => {
  assert.deepEqual(orderLineup([5, 3, 4, 1, 2], [], players).map((x) => `${x.slot}:${x.id}`), ['lw:1', 'c:2', 'rw:3', 'ld:4', 'rd:5']);
});

test('orderLineup handles four players, three defenders and six players', () => {
  assert.deepEqual(orderLineup([1, 2, 4, 5], [], players).map((x) => x.slot), ['lw', 'c', 'ld', 'rd']);
  assert.deepEqual(orderLineup([1, 2, 4, 5, 6], [], players).map((x) => `${x.slot}:${x.id}`), ['lw:1', 'c:2', 'rw:6', 'ld:4', 'rd:5']);
  assert.equal(orderLineup([1, 2, 3, 4, 5, 7], [], players).length, 6);
});

test('initLines copies the coach presets and pads to three lines', () => {
  const f = [{ line: 1, lw: 1, c: 2, rw: 3, ld: 4, rd: 5 }];
  const l = initLines(f);
  assert.equal(l.length, 3);
  assert.deepEqual(l[0], f[0]);
  assert.notEqual(l[0], f[0]);
  assert.deepEqual(l[2], { line: 3, lw: null, c: null, rw: null, ld: null, rd: null });
  assert.equal(initLines([]).length, 3);
});

test('assignSlot puts a bench player into a slot; the one sitting there goes to the bench', () => {
  const l = initLines([{ line: 1, lw: 1, c: 2, rw: 3, ld: 4, rd: 5 }]);
  const n = assignSlot(l, 9, 0, 'c');
  assert.equal(n[0].c, 9);
  assert.equal(l[0].c, 2, 'original not mutated');
  assert.ok(!linePlayers(n[0]).includes(2));
});

test('assignSlot swaps two players already in lines', () => {
  const l = initLines([{ line: 1, lw: 1, c: 2, rw: 3, ld: 4, rd: 5 }, { line: 2, lw: 6, c: 7, rw: 8, ld: 9, rd: 10 }]);
  const n = assignSlot(l, 7, 0, 'lw');
  assert.equal(n[0].lw, 7);
  assert.equal(n[1].c, 1);
  const m = assignSlot(l, 1, 2, 'rd');
  assert.equal(m[0].lw, null);
  assert.equal(m[2].rd, 1);
  assert.deepEqual(linePlayers(clearSlot(l, 0, 'c')[0]), [1, 3, 4, 5]);
});

test('situation gives each team its strength and line-up size', () => {
  assert.deepEqual(teamSituation('even', 'home'), { strength: 'even', size: 5 });
  assert.deepEqual(teamSituation('pp_home', 'home'), { strength: 'power_play', size: 5 });
  assert.deepEqual(teamSituation('pp_home', 'away'), { strength: 'short_handed', size: 4 });
  assert.deepEqual(teamSituation('pp_away', 'home'), { strength: 'short_handed', size: 4 });
});

test('subBody sets empty_net only for six players', () => {
  assert.equal(subBody({ team: 'home', period: 1, time: '00:00', players: [1, 2, 3, 4, 5] }).empty_net, false);
  assert.equal(subBody({ team: 'home', period: 1, time: '00:00', players: [1, 2, 3, 4, 5, 6] }).empty_net, true);
});
