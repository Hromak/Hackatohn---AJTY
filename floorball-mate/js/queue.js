// Offline outbox. Every event is written to storage before it is sent; PUT with the client UUID
// makes resending safe. One request at a time, in order; corrections replace the pending version.

const RETRY_MS = [1000, 2000, 5000, 10000];

export class Outbox {
  constructor({ storage = globalThis.localStorage, send, key = 'fm.outbox' }) {
    this.storage = storage;
    this.send = send;
    this.key = key;
    this.items = JSON.parse(storage.getItem(key) || '[]');
    this.failures = 0;
    this.running = null;
    this.onchange = () => {};
  }

  save() {
    this.storage.setItem(this.key, JSON.stringify(this.items));
    this.onchange();
  }

  get(client_id) {
    return this.items.find((i) => i.client_id === client_id);
  }

  pending() {
    return this.items.filter((i) => i.status === 'pending');
  }

  forMatch(match_id) {
    return this.items.filter((i) => i.match_id === match_id);
  }

  enqueue(match_id, client_id, op, body) {
    const item = this.get(client_id);
    const fields = { op, body, status: 'pending', error: null, rev: (item?.rev ?? 0) + 1 };
    if (item) Object.assign(item, fields);
    else this.items.push({ match_id, client_id, warnings: [], ...fields });
    this.save();
  }

  put(match_id, client_id, body) {
    this.enqueue(match_id, client_id, 'put', body);
  }

  remove(match_id, client_id) {
    this.enqueue(match_id, client_id, 'delete', this.get(client_id)?.body ?? null);
  }

  retry(client_id) {
    const item = this.get(client_id);
    if (item?.status === 'rejected') Object.assign(item, { status: 'pending', error: null });
    this.save();
  }

  // Sends until the queue is empty or a retryable failure; returns how long to wait before the next try.
  flush() {
    this.running ??= this.#run().finally(() => (this.running = null));
    return this.running;
  }

  async #run() {
    for (let item; (item = this.pending()[0]); ) {
      const rev = item.rev;
      const path = `/matches/${item.match_id}/events/${item.client_id}`;
      const r = item.op === 'put' ? await this.send('PUT', path, item.body) : await this.send('DELETE', path);
      if (r.status === 0 || r.status === 429 || r.status >= 500) {
        this.failures++;
        return { waitMs: r.status === 429 && r.retryAfter ? r.retryAfter * 1000 : RETRY_MS[Math.min(this.failures, RETRY_MS.length) - 1] };
      }
      this.failures = 0;
      if (item.rev !== rev) continue; // edited while in flight: send the newer version next
      const ok = (r.status >= 200 && r.status < 300) || (item.op === 'delete' && r.status === 404);
      if (ok) Object.assign(item, { status: 'done', event: r.body?.event ?? null, warnings: r.body?.event?.warnings ?? [] });
      else Object.assign(item, { status: 'rejected', error: r.body?.error ?? { code: `http_${r.status}`, message: `Chyba ${r.status}.` } });
      this.save();
    }
    return { waitMs: 0 };
  }
}
