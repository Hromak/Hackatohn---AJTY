"""Findings of the code review, pinned by tests."""
import json

import pytest
from fastapi.testclient import TestClient

from app import cli
from app.db import connect
from app.main import create_app
from app.seed import load_match_file
from tests.conftest import FIXTURE_MATCH, make_settings, seed_team
from tests.helpers import Api, cid


@pytest.fixture
def api(client, team_a):
    return Api(client, team_a)


@pytest.mark.parametrize("bad_type", [["shot"], {}, 5, None, True])
def test_type_of_wrong_json_kind_is_422_not_500(api, bad_type):
    r = api.put(cid(), dict(api.shot(), type=bad_type))
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"
    assert "type" in r.json()["error"]["fields"]


def test_match_version_is_never_ahead_of_the_listed_events(api, monkeypatch, settings):
    from app import repo

    api.put(cid(), api.shot())
    original = repo.list_events

    def list_then_someone_writes(conn, match_id, include_deleted=False):
        rows = original(conn, match_id, include_deleted)
        other = connect(settings.db_path)  # a write lands between the two reads
        other.execute("UPDATE match SET version = version + 5 WHERE id = ?", (match_id,))
        other.close()
        return rows

    monkeypatch.setattr(repo, "list_events", list_then_someone_writes)
    assert api.events()["match_version"] == 1


def test_update_of_time_only_and_period_only_is_stored(api):
    c = cid()
    api.put(c, api.shot())
    moved = api.put(c, api.shot(time="08:00")).json()
    assert moved["unchanged"] is False and moved["event"]["time"] == "08:00" and moved["event"]["version"] == 2
    later = api.put(c, api.shot(time="08:00", period=2)).json()["event"]
    assert later["period"] == 2 and later["version"] == 3
    assert later["updated_at"] >= later["created_at"]
    assert api.get(c).json()["event"]["period"] == 2


def test_event_limit_counts_deleted_events(tmp_path):
    settings = make_settings(tmp_path, max_events=2)
    with TestClient(create_app(settings)) as client:
        api = Api(client, seed_team(settings, "Limit"))
        first = cid()
        api.put(first, api.shot())
        api.put(cid(), api.shot(time="01:00"))
        api.delete(first)
        r = api.put(cid(), api.shot(time="02:00"))
    assert r.status_code == 422 and r.json()["error"]["code"] == "event_limit"


def test_in_out_across_periods_and_around_deleted_in_lists(api):
    a, b, c = cid(), cid(), cid()
    api.put(a, api.sub())                                                        # 10 11 12 13 14
    api.put(b, api.sub(jerseys=(20, 21, 22, 23, 24), time="19:00"))
    api.put(c, api.sub(jerseys=(10, 11, 12, 13, 40), period=2, time="00:00"))
    api.delete(b)
    by_id = {e["client_id"]: e for e in api.events(include_deleted=True)["events"]}
    assert by_id[c]["in"] == [api.home[40]] and by_id[c]["out"] == [api.home[14]]  # against a, not deleted b
    assert by_id[b]["in"] == [] and by_id[b]["out"] == [] and by_id[b]["deleted_at"]
    single = api.get(c).json()["event"]
    assert (single["in"], single["out"]) == (by_id[c]["in"], by_id[c]["out"])


def test_delete_bumps_event_and_match_version(api):
    c = cid()
    api.put(c, api.shot())
    api.delete(c)
    assert api.get(c).json()["event"]["version"] == 2
    assert api.client.get(api.base, headers=api.headers).json()["version"] == 2


def test_body_over_limit_without_content_length_is_413(api):
    def chunks():
        for _ in range(20):
            yield b" " * 1000

    r = api.client.put(f"{api.base}/events/{cid()}", content=chunks(), headers=api.headers)
    assert "content-length" not in r.request.headers
    assert r.status_code == 413 and r.json()["error"]["code"] == "payload_too_large"


def test_on_ice_away_is_checked_against_the_away_roster(api):
    r = api.put(cid(), api.shot(result="goal", on_ice={"home": [], "away": [api.home[10]]}))
    assert r.status_code == 422 and r.json()["error"]["fields"] == {"on_ice.away": "wrong_team"}


def test_formations_fixture_has_real_ids(api):
    forms = api.client.get(f"{api.base}/formations", headers=api.headers).json()
    assert forms["home"][0] == {"line": 1, **{slot: api.home[j] for slot, j in
                                              zip(("lw", "c", "rw", "ld", "rd"), (10, 11, 12, 13, 14))}}


def test_player_ids_differ_between_a_teams_two_matches(client, team_a):
    training, second = Api(client, team_a), Api(client, team_a, "second")
    assert set(training.home.values()).isdisjoint(second.home.values())
    r = second.put(cid(), training.shot())
    assert r.status_code == 422 and r.json()["error"]["code"] == "unknown_player"


def test_lowercase_bearer_scheme_is_accepted(client, team_a):
    r = client.get("/api/v1/me", headers={"Authorization": f"bearer {team_a['token']}"})
    assert r.status_code == 200


def test_retry_after_is_readable_from_a_browser(tmp_path):
    settings = make_settings(tmp_path, rate_per_sec=0.001, rate_burst=1)
    with TestClient(create_app(settings)) as client:
        last = [client.get("/api/v1/me", headers={"Origin": "https://x.example"}) for _ in range(3)][-1]
    assert last.status_code == 429
    assert "retry-after" in last.headers["access-control-expose-headers"].lower()


def test_events_survive_a_new_connection(client, team_a, settings):
    api = Api(client, team_a)
    c = cid()
    api.put(c, api.shot())
    row = connect(settings.db_path).execute("SELECT client_id FROM event").fetchone()
    assert row["client_id"] == c


# --- OpenAPI ---------------------------------------------------------------------------------


def test_openapi_describes_codes_conflict_body_and_limits(client):
    spec = client.get("/api/openapi.json").json()
    schemas = spec["components"]["schemas"]
    codes = schemas["ErrorDetail"]["properties"]["code"]["examples"]
    for code in ("unknown_player", "duplicate_time", "version_conflict", "deleted", "rate_limited",
                 "too_many_concurrent_requests", "invalid_client_id", "goalkeeper_in_line", "event_limit"):
        assert code in codes, code
    put = spec["paths"]["/api/v1/matches/{match_id}/events/{client_id}"]["put"]
    assert put["responses"]["409"]["content"]["application/json"]["schema"]["$ref"].endswith("/ConflictOut")
    assert "event" in schemas["ConflictOut"]["properties"]
    assert put["operationId"] == "putEvent"
    shot = schemas["ShotIn"]["properties"]
    assert (shot["x"]["minimum"], shot["x"]["maximum"], shot["y"]["maximum"]) == (0, 890, 501)
    assert schemas["SubstitutionIn"]["properties"]["players"]["minItems"] == 3
    assert schemas["SubstitutionIn"]["properties"]["players"]["maxItems"] == 6
    assert shot["time"]["pattern"] == "^[0-9]{2}:[0-5][0-9]$"
    ids = [op["operationId"] for ops in spec["paths"].values() for op in ops.values()]
    assert len(ids) == len(set(ids)) and all("_" not in i for i in ids)


def test_samples_conform_to_the_documented_shapes(client):
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "sample-data"
    shot = json.loads((root / "event-shot-put-response.json").read_text(encoding="utf-8"))["event"]
    spec = client.get("/api/openapi.json").json()["components"]["schemas"]
    assert set(shot) <= set(spec["ShotOut"]["properties"])
    assert set(spec["ShotOut"]["required"]) <= set(shot)


# --- match file and CLI ------------------------------------------------------------------------


def broken(change):
    match = json.loads(FIXTURE_MATCH.read_text(encoding="utf-8"))
    change(match)
    return match


@pytest.mark.parametrize(
    "change,word",
    [
        (lambda m: m.pop("roster"), "roster"),
        (lambda m: m.__setitem__("home", "Domácí"), "home"),
        (lambda m: m["home"].__setitem__("name", None), "home.name"),
        (lambda m: m["roster"]["home"][0].pop("position"), "position"),
        (lambda m: m["roster"]["home"][0].__setitem__("position", "B"), "position"),
        (lambda m: m["roster"]["away"].append(dict(m["roster"]["away"][0])), "repeats"),
        (lambda m: m["roster"].__setitem__("home", [p for p in m["roster"]["home"] if p["position"] != "G"]), "goalkeeper"),
        (lambda m: m["formations"]["home"][0].pop("line"), "line"),
        (lambda m: m["formations"]["home"].append(dict(m["formations"]["home"][0])), "line"),
        (lambda m: m["formations"]["home"][0].__setitem__("lw", 77), "not on roster"),
        (lambda m: m["formations"].pop("away"), "formations.away"),
        (lambda m: m["periods"].__setitem__("overtime_min", -5), "overtime_min"),
        (lambda m: m["periods"].__setitem__("count", 0), "count"),
        (lambda m: m.__setitem__("date", 20261121), "date"),
    ],
)
def test_match_file_errors_name_the_problem(tmp_path, change, word):
    path = tmp_path / "match.json"
    path.write_text(json.dumps(broken(change)), encoding="utf-8")
    with pytest.raises(ValueError, match=word):
        load_match_file(str(path))


def test_match_file_missing_or_not_json_is_a_value_error(tmp_path):
    with pytest.raises(ValueError, match="cannot read"):
        load_match_file(str(tmp_path / "nope.json"))
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="not valid JSON"):
        load_match_file(str(bad))


def run_cli(monkeypatch, capsys, settings, *argv):
    monkeypatch.setenv("ZAPI_DB_PATH", settings.db_path)
    code = cli.main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def team_count(settings):
    from app.db import init_schema

    conn = connect(settings.db_path)
    init_schema(conn)  # a refused command may not have touched the database at all
    return conn.execute("SELECT COUNT(*) FROM team").fetchone()[0]


@pytest.mark.parametrize(
    "lines,word",
    [
        ("Alfa\tgood-token-0123456789\nBeta\tgood-token-0123456789\n", "twice"),
        ("Alfa\thas space 0123456789\n", "token"),
        ("Alfa\t\n", "token"),
        ("just a line without a tab\n", "tab"),
        ("Alfa\tgood-token-0123456789\nAlfa\tother-token-0123456789\n", "name"),
    ],
)
def test_bad_tokens_file_creates_nothing_and_says_why(tmp_path, monkeypatch, capsys, lines, word):
    settings = make_settings(tmp_path)
    tokens = tmp_path / "tokens.tsv"
    tokens.write_text(lines, encoding="utf-8")
    code, _, err = run_cli(monkeypatch, capsys, settings, "add-teams", str(FIXTURE_MATCH), "--tokens-file", str(tokens))
    assert code != 0 and word in err and "Traceback" not in err
    assert team_count(settings) == 0


def test_duplicate_names_and_conflicting_options_are_refused(tmp_path, monkeypatch, capsys):
    settings = make_settings(tmp_path)
    code, _, err = run_cli(monkeypatch, capsys, settings, "add-teams", str(FIXTURE_MATCH), "--names", "Alfa,Alfa")
    assert code != 0 and "name" in err and team_count(settings) == 0
    run_cli(monkeypatch, capsys, settings, "add-teams", str(FIXTURE_MATCH), "--names", "Alfa")
    code, _, err = run_cli(monkeypatch, capsys, settings, "add-teams", str(FIXTURE_MATCH), "--names", "Alfa")
    assert code != 0 and "already exists" in err and team_count(settings) == 1


def test_bad_match_file_on_the_command_line_is_one_clear_line(tmp_path, monkeypatch, capsys):
    settings = make_settings(tmp_path)
    code, _, err = run_cli(monkeypatch, capsys, settings, "add-teams", str(tmp_path / "nope.json"), "--count", "1")
    assert code != 0 and "cannot read" in err and "Traceback" not in err


def test_startup_messages_name_the_real_cause(tmp_path, monkeypatch):
    with pytest.raises(SystemExit) as info:
        create_app(make_settings(tmp_path / "a", demo=True, demo_match_path=str(tmp_path / "missing.json")))
    assert "cannot read" in str(info.value) and "Databázi nejde" not in str(info.value)
    monkeypatch.setenv("ZAPI_RATE_BURST", "many")
    from app.config import Settings

    with pytest.raises(SystemExit) as info:
        Settings.from_env()
    assert "ZAPI_RATE_BURST" in str(info.value)


def test_private_network_preflight_is_allowed(client, team_a):
    r = client.options(
        f"/api/v1/matches/{team_a['training']}/events",
        headers={"Origin": "https://tablet.example.org", "Access-Control-Request-Method": "GET",
                 "Access-Control-Request-Private-Network": "true"},
    )
    assert r.status_code in (200, 204)
    assert r.headers["access-control-allow-private-network"] == "true"
