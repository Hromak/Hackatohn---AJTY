import { test } from 'node:test';
import assert from 'node:assert/strict';
import { Outbox } from '../js/queue.js';

function memStorage() {
  const m = new Map();
  return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)) };
}

function fakeSend(responses) {
  const calls = [];
  const send = async (method, path, body) => {
    calls.push({ method, path, body });
    const r = responses.shift() ?? { status: 201, body: { event: { warnings: [] } } };
    return typeof r === 'function' ? r() : r;
  };
  return { send, calls };
}

test('an event is stored locally before it is sent', () => {
  const storage = memStorage();
  const box = new Outbox({ storage, send: async () => ({ status: 0 }) });
  box.put(1, 'a', { type: 'shot' });
  const again = new Outbox({ storage, send: async () => ({ status: 0 }) });
  assert.equal(again.pending().length, 1);
  assert.equal(again.pending()[0].client_id, 'a');
});

test('flush sends PUT to the event path and marks it done', async () => {
  const { send, calls } = fakeSend([{ status: 201, body: { event: { warnings: ['shot_from_own_half'] } } }]);
  const box = new Outbox({ storage: memStorage(), send });
  box.put(1, 'a', { type: 'shot' });
  const r = await box.flush();
  assert.equal(r.waitMs, 0);
  assert.deepEqual(calls[0], { method: 'PUT', path: '/matches/1/events/a', body: { type: 'shot' } });
  assert.equal(box.get('a').status, 'done');
  assert.deepEqual(box.get('a').warnings, ['shot_from_own_half']);
});

test('a correction of a pending event replaces it, only the newest is sent', async () => {
  const { send, calls } = fakeSend([]);
  const box = new Outbox({ storage: memStorage(), send });
  box.put(1, 'a', { v: 1 });
  box.put(1, 'a', { v: 2 });
  await box.flush();
  assert.equal(calls.length, 1);
  assert.deepEqual(calls[0].body, { v: 2 });
});

test('network failure keeps the event and stops the flush, order is kept', async () => {
  const { send, calls } = fakeSend([{ status: 0 }]);
  const box = new Outbox({ storage: memStorage(), send });
  box.put(1, 'a', { n: 1 });
  box.put(1, 'b', { n: 2 });
  const r = await box.flush();
  assert.ok(r.waitMs > 0);
  assert.equal(calls.length, 1);
  assert.equal(box.pending().length, 2);
  await box.flush();
  assert.deepEqual(calls.map((c) => c.path), ['/matches/1/events/a', '/matches/1/events/a', '/matches/1/events/b']);
  assert.equal(box.pending().length, 0);
});

test('503 and 500 are retried, never dropped', async () => {
  const { send } = fakeSend([{ status: 503, body: { error: { code: 'forced_unavailable' } } }, { status: 500 }]);
  const box = new Outbox({ storage: memStorage(), send });
  box.put(1, 'a', {});
  assert.ok((await box.flush()).waitMs > 0);
  assert.ok((await box.flush()).waitMs > 0);
  assert.equal(box.get('a').status, 'pending');
  await box.flush();
  assert.equal(box.get('a').status, 'done');
});

test('429 waits as long as Retry-After says', async () => {
  const { send } = fakeSend([{ status: 429, retryAfter: 2, body: { error: { code: 'rate_limited' } } }]);
  const box = new Outbox({ storage: memStorage(), send });
  box.put(1, 'a', {});
  assert.equal((await box.flush()).waitMs, 2000);
  assert.equal(box.get('a').status, 'pending');
});

test('a rejected event is kept with its error and does not block the rest', async () => {
  const { send } = fakeSend([
    { status: 422, body: { error: { code: 'forced_rejection', message: 'Odmítnuto.' } } },
    { status: 201, body: { event: {} } },
  ]);
  const box = new Outbox({ storage: memStorage(), send });
  box.put(1, 'a', { n: 1 });
  box.put(1, 'b', { n: 2 });
  await box.flush();
  assert.equal(box.get('a').status, 'rejected');
  assert.equal(box.get('a').error.code, 'forced_rejection');
  assert.deepEqual(box.get('a').body, { n: 1 });
  assert.equal(box.get('b').status, 'done');
});

test('retry puts a rejected event back to the queue', async () => {
  const { send } = fakeSend([{ status: 409, body: { error: { code: 'duplicate_time' } } }]);
  const box = new Outbox({ storage: memStorage(), send });
  box.put(1, 'a', {});
  await box.flush();
  box.retry('a');
  await box.flush();
  assert.equal(box.get('a').status, 'done');
});

test('delete sends DELETE; 204 and 404 both count as done', async () => {
  const { send, calls } = fakeSend([{ status: 204 }, { status: 404, body: { error: { code: 'unknown_event' } } }]);
  const box = new Outbox({ storage: memStorage(), send });
  box.remove(1, 'a');
  box.remove(1, 'b');
  await box.flush();
  assert.deepEqual(calls.map((c) => c.method), ['DELETE', 'DELETE']);
  assert.equal(box.get('a').status, 'done');
  assert.equal(box.get('b').status, 'done');
  assert.equal(box.get('a').op, 'delete');
});

test('an edit made while the old version is in flight is sent afterwards', async () => {
  let box;
  const calls = [];
  const send = async (method, path, body) => {
    calls.push(body);
    if (calls.length === 1) box.put(1, 'a', { v: 2 });
    return { status: 201, body: { event: {} } };
  };
  box = new Outbox({ storage: memStorage(), send });
  box.put(1, 'a', { v: 1 });
  await box.flush();
  assert.deepEqual(calls, [{ v: 1 }, { v: 2 }]);
  assert.equal(box.get('a').status, 'done');
});

test('only one request is in flight at a time', async () => {
  let inFlight = 0, max = 0;
  const send = async () => {
    inFlight++; max = Math.max(max, inFlight);
    await new Promise((r) => setTimeout(r, 5));
    inFlight--;
    return { status: 201, body: { event: {} } };
  };
  const box = new Outbox({ storage: memStorage(), send });
  for (const id of ['a', 'b', 'c']) box.put(1, id, {});
  await Promise.all([box.flush(), box.flush()]);
  assert.equal(max, 1);
  assert.equal(box.pending().length, 0);
});
