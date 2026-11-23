# AGENTS.md

Instructions for AI coding agents (and people) working in this repository.

## What this is

A small standalone HTTP service for a hackathon. Teams build a tablet app for a floorball
scorer; this service gives the app its data (matches, rosters, line presets) and collects the
shots and substitutions the app records. The contract and the
reasons behind it are in `docs/design.md` (Czech). Read it before changing behaviour.

## Layout

| Path | Responsibility |
|---|---|
| `app/main.py` | application factory, wiring |
| `app/config.py` | settings from `ZAPI_*` environment variables |
| `app/models.py` | request and response shapes (the API description is generated from them) |
| `app/rules.py` | validation of shots and substitutions – pure functions, no database |
| `app/repo.py` | all SQL (bound parameters only) |
| `app/routes_public.py` | endpoints for teams |
| `app/middleware.py` | body limit, rate limit, CORS |
| `app/auth.py` | bearer tokens, forced error modes |
| `app/seed.py`, `app/cli.py` | creating teams and matches, management commands |
| `data/demo-match.json` | the fictional demo match (seed format) |
| `data/matches/*.json` | real league matches, rosters only; loaded as extra matches of the demo team |
| `docs/openapi.json`, `sample-data/` | **generated** – never edit by hand |
| `tests/` | pytest suite; `tests/helpers.py` has the `Api` helper for event tests |
| `scripts/smoke.py` | end-to-end walk through against a running instance |

## Commands

```bash
uv sync                                   # install
uv run pytest                             # all tests (about 20 s)
uv run pytest tests/test_rules.py -k sub  # a subset
ZAPI_DEMO=1 uv run uvicorn app.main:app_from_env --factory --port 8000   # run locally, token "demo"
uv run python -m app.cli export-openapi   # regenerate docs/openapi.json
uv run python -m app.cli export-samples   # regenerate sample-data/
python3 scripts/smoke.py --base-url http://localhost:8000 --token demo
docker compose up --build                 # the same in a container
```

## Rules

- **Test first.** Write the failing test, watch it fail, then write the code. Rules belong in
  `tests/test_rules.py`, HTTP behaviour in `tests/test_events*.py`.
- **After any change to `app/models.py`, routes or the demo match, regenerate** the API
  description and the samples (two `export-*` commands above). `tests/test_generated.py` fails
  when they are stale.
- **The contract is frozen during the hackathon.** Do not rename fields, codes or paths.
- Every error goes through `ApiError` so that it has the common shape
  `{"error": {"code", "message", "fields"}}`. Messages are Czech, codes are English.
- SQL lives only in `app/repo.py` and always uses bound parameters.
- New error codes must be added to `ERROR_CODES` in `app/errors.py` and to the README table.
- Coordinates are never mirrored: home attacks right (x ≥ 445) for the whole match.
- Nothing secret goes into the repository. The directory `private/` is git-ignored; public
  code and documents must not refer to it (a test checks this).
- User-facing text is Czech; code, identifiers and commit messages are English.

## Decisions worth knowing

- One `PUT` with a client-generated UUID creates and updates an event; an identical repeat is
  a no-op. This is what makes an offline queue safe.
- A substitution is the line-up that came on, as in FIS; who came on and went off is computed
  on read.
- Deleting is final (410 on a later `PUT`); a reset really removes the rows.
- SQLite in WAL mode, one process. Write transactions use `BEGIN IMMEDIATE`.
