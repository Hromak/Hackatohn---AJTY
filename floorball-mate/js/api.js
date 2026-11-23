// Thin fetch wrapper. Never throws: a network failure is { status: 0 }.

export function createApi({ base = '/api/v1', token, fetchImpl = globalThis.fetch }) {
  async function send(method, path, body) {
    try {
      const r = await fetchImpl(base + path, {
        method,
        headers: { Authorization: `Bearer ${token()}`, ...(body ? { 'Content-Type': 'application/json' } : {}) },
        body: body ? JSON.stringify(body) : undefined,
      });
      const text = await r.text();
      let json = null;
      try { json = text ? JSON.parse(text) : null; } catch { /* non-JSON error page */ }
      return { status: r.status, body: json, retryAfter: Number(r.headers.get('Retry-After')) || 0 };
    } catch {
      return { status: 0, body: null, retryAfter: 0 };
    }
  }
  const get = async (path) => {
    const r = await send('GET', path);
    if (r.status !== 200) throw Object.assign(new Error(r.body?.error?.message ?? `Chyba ${r.status || 'spojení'}.`), r);
    return r.body;
  };
  return { send, get };
}
