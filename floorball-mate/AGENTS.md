# AGENTS.md

Plain HTML + ES modules, no build, no dependencies. `serve.py` (stdlib) serves the app and proxies
`/api/` to the OLC service. The OLC backend and its contract are frozen: never change it.

| Path | Responsibility |
|---|---|
| `js/model.js` | pure: time parsing, event bodies, line-up at a moment, merge of server + local events |
| `js/queue.js` | offline outbox: store first, PUT with client UUID, one request at a time, retry 0/429/5xx, keep 4xx as rejected |
| `js/predict.js` | next line-up suggestion (formations + recent history) |
| `js/api.js` | fetch wrapper, never throws (network error = status 0) |
| `js/stats.js` | shot filters, summary, slot zone (goal positions measured on the rink image) |
| `js/voice.js` | voice/typed command -> shot fields, rule-based parser (Czech number words) |
| `js/app.js` | UI only |
| `test/*.test.js` | unit tests, no network |
| `test/e2e-real.js` | walk through against the real service (resets match 1) |
| `eval/eval-predict.js` | prediction accuracy on `../sample-data/full-match-events.json` |

## Rules

- Test first: `node --test test/*.test.js` must pass; logic goes in `model/queue/predict`, not `app.js`.
- Before claiming the API works, run `node test/e2e-real.js` against `docker compose up` + `serve.py`.
- Coordinates are never mirrored in data: home attacks right (x ≥ 445). "Prohodit strany" is display only.
- Never drop an event: a rejected one stays in the outbox with its error until the scorer fixes or deletes it.
- Accuracy numbers in docs/presentation come from `node eval/eval-predict.js`, not from memory.
- User-facing text Czech, code English.
