"""Management commands: python -m app.cli <command>.

  add-teams <match.json> --names "A,B" | --count N | --tokens-file FILE
  status
  export-openapi [--out docs/openapi.json]
  export-samples [--out sample-data]

The database is the one from ZAPI_DB_PATH (see app/config.py).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

from app import repo
from app.auth import hash_token
from app.config import Settings
from app.db import connect, init_schema, transaction
from app.seed import add_team, events_to_api, load_match_file

ROOT = Path(__file__).resolve().parent.parent
DEMO_MATCH = ROOT / "data" / "demo-match.json"
FIXED_TIME = "2026-11-21T09:00:00Z"
_TEAM_TOKEN = re.compile(r"^[\x21-\x7e]{8,256}$")
_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")


def _open():
    conn = connect(Settings.from_env().db_path)
    init_schema(conn)
    return conn


class CliError(Exception):
    """A problem with the input; shown as one line, nothing is changed."""


def _teams_from_tokens_file(path: str) -> list[tuple[str, str]]:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise CliError(f"cannot read the tokens file {path} ({exc.strerror or exc})") from None
    wanted = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            raise CliError(f"tokens file line {number}: expected name<tab>token")
        name, token = parts[0].strip(), parts[1]
        if not name:
            raise CliError(f"tokens file line {number}: the team name is empty")
        if _TEAM_TOKEN.fullmatch(token) is None:
            raise CliError(
                f"tokens file line {number}: the token must be 8-256 characters without spaces "
                "or accented letters (check for stray spaces)"
            )
        wanted.append((name, token))
    tokens = [token for _, token in wanted]
    if len(set(tokens)) != len(tokens):
        raise CliError("tokens file: the same token appears twice")
    return wanted


def cmd_add_teams(args) -> int:
    chosen = [option for option in (args.names, args.count, args.tokens_file) if option]
    if len(chosen) != 1:
        raise CliError("give exactly one of --names, --count or --tokens-file")
    try:
        match = load_match_file(args.match)
    except ValueError as exc:
        raise CliError(str(exc)) from None
    if args.tokens_file:
        wanted = _teams_from_tokens_file(args.tokens_file)
    elif args.names:
        wanted = [(name.strip(), None) for name in args.names.split(",") if name.strip()]
    else:
        if not 1 <= args.count <= 200:
            raise CliError("--count must be between 1 and 200")
        wanted = [(f"Tým {n}", None) for n in range(1, args.count + 1)]
    if not wanted:
        raise CliError("no team to create")
    names = [name for name, _ in wanted]
    if len(set(names)) != len(names):
        raise CliError("the same team name appears twice")
    conn = _open()
    try:
        with transaction(conn):
            existing = {team["name"] for team in repo.teams_overview(conn)}
            for name, token in wanted:
                if name in existing:
                    raise CliError(f"a team named '{name}' already exists; nothing created")
                if token and repo.team_by_token_hash(conn, hash_token(token)) is not None:
                    raise CliError("a team with one of these tokens already exists; nothing created")
            created = []
            for name, token in wanted:
                team_id, plain = add_team(conn, name, match, token=token)
                created.append((name, plain, repo.matches_of_team(conn, team_id)[0]["id"]))
    finally:
        conn.close()
    print("# name\ttoken\tmatch_id   (tokens are shown only now; keep this output)")
    for name, plain, match_id in created:
        print(f"{name}\t{plain}\t{match_id}")
    return 0


def cmd_status(args) -> int:
    conn = _open()
    try:
        for team in repo.teams_overview(conn):
            print(f"{team['name']} (id {team['id']}, režim chyby: {team['error_mode']})")
            for match in team["matches"]:
                print(f"  utkání {match['id']} {match['home']} – {match['away']}: "
                      f"{match['events']} událostí, {match['deleted']} smazaných, verze {match['version']}")
    finally:
        conn.close()
    return 0


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _demo_client(directory: str):
    from fastapi.testclient import TestClient

    from app.main import create_app

    settings = Settings(
        db_path=str(Path(directory) / "samples.sqlite"),
        demo=True,
        demo_token="demo",
        demo_match_path=str(DEMO_MATCH),
        rate_per_sec=100_000,
        rate_burst=100_000,
        global_rate_per_sec=100_000,
        global_rate_burst=100_000,
    )
    return TestClient(create_app(settings))


def cmd_export_openapi(args) -> int:
    with tempfile.TemporaryDirectory() as directory, _demo_client(directory) as client:
        _write(Path(args.out), client.get("/api/openapi.json").json())
    return 0


def _fixed(data):
    """Replace timestamps so that the generated files do not change from run to run."""
    return json.loads(_TIMESTAMP.sub(FIXED_TIME, json.dumps(data, ensure_ascii=False)))


def cmd_export_samples(args) -> int:
    out = Path(args.out)
    headers = {"Authorization": "Bearer demo"}
    demo = load_match_file(str(DEMO_MATCH))
    with tempfile.TemporaryDirectory() as directory, _demo_client(directory) as client:
        def get(path):
            response = client.get(f"/api/v1{path}", headers=headers)
            assert response.status_code == 200, (path, response.text)
            return response.json()

        me = get("/me")
        match_id = me["matches"][0]["id"]
        base = f"/matches/{match_id}"
        roster = get(f"{base}/roster")
        _write(out / "me.json", me)
        _write(out / "codebooks.json", get("/codebooks"))
        _write(out / "matches.json", get("/matches"))
        _write(out / "match.json", get(base))
        _write(out / "roster.json", roster)
        _write(out / "formations.json", get(f"{base}/formations"))
        _write(out / "events-empty.json", get(f"{base}/events"))

        home = {p["jersey"]: p["id"] for p in roster["home"]}
        away = {p["jersey"]: p["id"] for p in roster["away"]}
        full = events_to_api(demo, home, away)
        _write(out / "full-match-events.json", full)

        def put(item):
            response = client.put(
                f"/api/v1{base}/events/{item['client_id']}", json=item["body"], headers=headers
            )
            return response

        first_sub = next(e for e in full if e["body"]["type"] == "substitution")
        second_sub = next(
            e for e in full
            if e["body"]["type"] == "substitution" and e["body"]["team"] == first_sub["body"]["team"]
            and e is not first_sub
        )
        goal = next(e for e in full if e["body"]["type"] == "shot" and e["body"]["result"] == "goal")
        put(first_sub)
        _write(out / "event-substitution-put-request.json", second_sub["body"])
        _write(out / "event-substitution-put-response.json", _fixed(put(second_sub).json()))
        _write(out / "event-shot-put-request.json", goal["body"])
        _write(out / "event-shot-put-response.json", _fixed(put(goal).json()))
        _write(out / "events.json", _fixed(get(f"{base}/events")))
        bad = dict(goal["body"], shooter_id=999999)
        error = client.put(
            f"/api/v1{base}/events/00000000-0000-4000-8000-000000000001", json=bad, headers=headers
        )
        assert error.status_code == 422, error.text
        _write(out / "error-unknown-player.json", error.json())
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("add-teams", help="create teams, each with its own token and one match")
    p.add_argument("match", help="match description file (JSON)")
    p.add_argument("--names", help='comma separated team names, e.g. "Alfa,Beta"')
    p.add_argument("--count", type=int, help="create N teams named Tým 1..N")
    p.add_argument("--tokens-file", help="output of an earlier add-teams run; re-creates the same tokens")
    p.set_defaults(func=cmd_add_teams)

    p = sub.add_parser("status", help="teams, matches and event counts")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("export-openapi", help="write the API description")
    p.add_argument("--out", default=str(ROOT / "docs" / "openapi.json"))
    p.set_defaults(func=cmd_export_openapi)

    p = sub.add_parser("export-samples", help="write the sample data")
    p.add_argument("--out", default=str(ROOT / "sample-data"))
    p.set_defaults(func=cmd_export_samples)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except CliError as problem:
        print(f"{args.command}: {problem}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
