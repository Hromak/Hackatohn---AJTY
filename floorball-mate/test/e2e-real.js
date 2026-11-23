// End-to-end walk through against the REAL OLC service, through serve.py, using the app's own modules.
// It RESETS the match it uses (default 1). Needs: docker compose up (OLC) and python3 serve.py.
// usage: node test/e2e-real.js [--base http://localhost:5173] [--match 1] [--token demo]
import assert from 'node:assert/strict';
import { createApi } from '../js/api.js';
import { Outbox } from '../js/queue.js';
import { shotBody, subBody } from '../js/model.js';

const arg = (n, d) => { const i = process.argv.indexOf(`--${n}`); return i > 0 ? process.argv[i + 1] : d; };
const BASE = arg('base', 'http://localhost:5173');
const M = Number(arg('match', '1'));
const TOKEN = arg('token', 'demo');

const api = createApi({ base: `${BASE}/api/v1`, token: () => TOKEN });
const mem = () => { const m = new Map(); return { getItem: (k) => m.get(k) ?? null, setItem: (k, v) => m.set(k, v) }; };
let sent = 0, limited = 0;
const send = async (...a) => { sent++; const r = await api.send(...a); if (r.status === 429) limited++; return r; };
const box = new Outbox({ storage: mem(), send });
const step = (s) => console.log(`\n▶ ${s}`);
const ok = (s) => console.log(`  ✓ ${s}`);

async function drain(max = 60) {
  for (let i = 0; i < max; i++) {
    const { waitMs } = await box.flush();
    if (!waitMs) return;
    await new Promise((r) => setTimeout(r, Math.min(waitMs, 1500)));
  }
  throw new Error('queue did not drain');
}
const serverEvents = async () => (await api.get(`/matches/${M}/events`)).events;
const errorMode = async (mode) => assert.equal((await api.send('PUT', '/me/error-mode', { mode })).status, 200);

try {
  step('proxy and token');
  assert.equal((await api.send('GET', '/me')).status, 200);
  assert.equal((await createApi({ base: `${BASE}/api/v1`, token: () => 'wrong' }).send('GET', '/me')).status, 401);
  ok('GET /me 200 via proxy, wrong token 401');

  step(`reset match ${M}, load header, roster, formations`);
  assert.equal((await api.send('POST', `/matches/${M}/reset`)).status < 300, true);
  const header = await api.get(`/matches/${M}`);
  const roster = await api.get(`/matches/${M}/roster`);
  const formations = await api.get(`/matches/${M}/formations`);
  const fieldOf = (t) => roster[t].filter((p) => p.position !== 'G').map((p) => p.id);
  const gk = (t) => roster[t].find((p) => p.position === 'G').id;
  const line = (t, n) => (formations[t][n] ? ['lw', 'c', 'rw', 'ld', 'rd'].map((k) => formations[t][n][k]) : fieldOf(t).slice(n * 5, n * 5 + 5));
  ok(`${header.home.name} – ${header.away.name}, ${roster.home.length}+${roster.away.length} players, ${formations.home.length} preset lines`);

  step('period start, shot, goal with assist');
  const id = { h0: crypto.randomUUID(), a0: crypto.randomUUID(), shot: crypto.randomUUID(), goal: crypto.randomUUID(), h1: crypto.randomUUID() };
  box.put(M, id.h0, subBody({ team: 'home', period: 1, time: '00:00', players: line('home', 0) }));
  box.put(M, id.a0, subBody({ team: 'away', period: 1, time: '00:00', players: line('away', 0) }));
  box.put(M, id.shot, shotBody({ team: 'home', period: 1, time: '01:10', x: 700, y: 250, result: 'on_goal', shooter_id: line('home', 0)[0], goalkeeper_id: gk('away') }));
  box.put(M, id.h1, subBody({ team: 'home', period: 1, time: '01:30', players: line('home', 1) }));
  box.put(M, id.goal, shotBody({
    team: 'home', period: 1, time: '02:05', x: 760, y: 240, result: 'goal', shooter_id: line('home', 1)[0], assist_id: line('home', 1)[1], goalkeeper_id: gk('away'),
    on_ice: { home: [...line('home', 1), gk('home')], away: [...line('away', 0), gk('away')] },
  }));
  await drain();
  let evs = await serverEvents();
  assert.equal(evs.length, 5);
  assert.ok(box.items.every((i) => i.status === 'done'));
  const h1 = evs.find((e) => e.client_id === id.h1);
  assert.deepEqual([...h1.in].sort(), [...line('home', 1)].sort());
  assert.deepEqual([...h1.out].sort(), [...line('home', 0)].sort());
  ok('5 events on the server; in/out of the 2nd home substitution computed by the API');

  step('identical repeat is a no-op');
  const again = await api.send('PUT', `/matches/${M}/events/${id.goal}`, box.get(id.goal).body);
  assert.equal(again.status, 200);
  assert.equal(again.body.unchanged, true);
  ok('200 unchanged: true');

  step('correction of the goal (other shooter)');
  box.put(M, id.goal, { ...box.get(id.goal).body, shooter_id: line('home', 1)[2] });
  await drain();
  const g = (await serverEvents()).find((e) => e.client_id === id.goal);
  assert.equal(g.shooter_id, line('home', 1)[2]);
  assert.equal(g.version, 2);
  ok('same client_id, version 2');

  step('delete the shot');
  box.remove(M, id.shot);
  await drain();
  evs = await serverEvents();
  assert.equal(evs.some((e) => e.client_id === id.shot), false);
  assert.equal((await api.send('PUT', `/matches/${M}/events/${id.shot}`, box.get(id.shot).body)).body.error.code, 'deleted');
  ok('gone from the server; a later PUT gets 410 deleted');

  step('duplicate_time is rejected and kept');
  const dup = crypto.randomUUID();
  box.put(M, dup, subBody({ team: 'home', period: 1, time: '01:30', players: line('home', 2) }));
  await drain();
  assert.equal(box.get(dup).status, 'rejected');
  assert.equal(box.get(dup).error.code, 'duplicate_time');
  assert.ok(box.get(dup).body.players);
  ok(`409 duplicate_time, event kept locally with message: "${box.get(dup).error.message}"`);
  box.put(M, dup, { ...box.get(dup).body, time: '01:31' });
  await drain();
  assert.equal(box.get(dup).status, 'done');
  ok('after fixing the time it goes through');

  step('error mode "unavailable": nothing is lost');
  await errorMode('unavailable');
  const off1 = [crypto.randomUUID(), crypto.randomUUID(), crypto.randomUUID()];
  off1.forEach((cid, i) => box.put(M, cid, shotBody({ team: 'away', period: 1, time: `03:0${i}`, x: 150, y: 250, result: 'miss', shooter_id: line('away', 0)[i] })));
  const r1 = await box.flush();
  assert.ok(r1.waitMs > 0);
  assert.equal(box.pending().length, 3);
  assert.equal((await api.send('GET', `/matches/${M}/events`)).status, 503);
  ok('PUT got 503, all 3 events still pending locally, reads 503 too');
  // the PUT from the error mode switch itself is a write: switching back must still work
  const back = await api.send('PUT', '/me/error-mode', { mode: 'off' });
  assert.equal(back.status, 200, 'error-mode off must be accepted while unavailable');
  await drain();
  evs = await serverEvents();
  assert.ok(off1.every((cid) => evs.some((e) => e.client_id === cid)));
  ok('after "off" all 3 arrived');

  step('error mode "reject": event kept with its error, retry works');
  await errorMode('reject');
  const rej = crypto.randomUUID();
  box.put(M, rej, shotBody({ team: 'away', period: 1, time: '04:00', x: 120, y: 200, result: 'post', shooter_id: line('away', 0)[1] }));
  await drain();
  assert.equal(box.get(rej).status, 'rejected');
  assert.equal(box.get(rej).error.code, 'forced_rejection');
  assert.equal((await api.send('GET', `/matches/${M}/events`)).status, 200);
  ok(`422 forced_rejection, kept locally ("${box.get(rej).error.message}"), reads still work`);
  await errorMode('off');
  box.retry(rej);
  await drain();
  assert.equal(box.get(rej).status, 'done');
  ok('retry after "off" stored it');

  step('burst: 60 queued events after reconnect, rate limit 20/s');
  sent = 0; limited = 0;
  const burst = Array.from({ length: 60 }, () => crypto.randomUUID());
  burst.forEach((cid, i) => box.put(M, cid, shotBody({ team: 'home', period: 2, time: `${String(Math.floor(i / 6)).padStart(2, '0')}:${String((i % 6) * 9).padStart(2, '0')}`, x: 600 + i, y: 250, result: 'miss', shooter_id: line('home', 0)[i % 5] })));
  const t0 = Date.now();
  await drain(200);
  evs = await serverEvents();
  assert.ok(burst.every((cid) => evs.some((e) => e.client_id === cid)));
  ok(`all 60 stored in ${((Date.now() - t0) / 1000).toFixed(1)} s, ${sent} requests, ${limited}× 429 handled by waiting`);

  step('Retry-After passes through the proxy');
  const hits = await Promise.all(Array.from({ length: 12 }, () => api.send('GET', '/me')));
  const busy = hits.find((h) => h.status === 429);
  if (busy) { assert.ok(busy.retryAfter > 0); ok(`429 ${busy.body.error.code}, Retry-After ${busy.retryAfter}`); }
  else ok('no 429 in 12 parallel GETs (limit not reached)');

  console.log('\nE2E OK');
} finally {
  await api.send('PUT', '/me/error-mode', { mode: 'off' });
}
