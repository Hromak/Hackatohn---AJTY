"""Findings of the security review, pinned by tests."""
import threading

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import connect
from app.main import create_app
from tests.conftest import auth, make_settings, seed_team
from tests.helpers import Api, cid


# --- rate limiting: nobody can spend someone else's budget -----------------------------------


def test_anonymous_flood_does_not_block_teams(tmp_path):
    settings = make_settings(tmp_path, rate_per_sec=0.001, rate_burst=5,
                             global_rate_per_sec=0.001, global_rate_burst=50)
    with TestClient(create_app(settings)) as client:
        team = seed_team(settings, "Poctivý")
        assert client.get("/api/v1/me", headers=auth(team["token"])).status_code == 200
        flood = [client.get("/neexistuje").status_code for _ in range(60)]
        flood += [client.get("/api/openapi.json").status_code for _ in range(60)]
        flood += [client.get("/api/v1/me").status_code for _ in range(60)]
        flood += [client.get("/api/v1/me", headers=auth(f"random-{n}")).status_code for n in range(60)]
        after = client.get("/api/v1/me", headers=auth(team["token"]))
    assert flood.count(429) > 200
    assert after.status_code == 200


def test_one_team_flood_does_not_block_another(tmp_path):
    settings = make_settings(tmp_path, rate_per_sec=0.001, rate_burst=5,
                             global_rate_per_sec=0.001, global_rate_burst=50)
    with TestClient(create_app(settings)) as client:
        noisy, calm = seed_team(settings, "Hlučný"), seed_team(settings, "Klidný")
        for token in (noisy["token"], calm["token"]):
            assert client.get("/api/v1/me", headers=auth(token)).status_code == 200
        statuses = [client.get("/api/v1/me", headers=auth(noisy["token"])).status_code for _ in range(100)]
        after = client.get("/api/v1/me", headers=auth(calm["token"]))
    assert statuses.count(429) >= 90
    assert after.status_code == 200


def test_in_flight_requests_per_token_are_capped(tmp_path, monkeypatch):
    from app import repo

    settings = make_settings(tmp_path, max_in_flight=2)
    app = create_app(settings)
    team = seed_team(settings, "Souběžný")
    gate, entered = threading.Event(), threading.Semaphore(0)
    original = repo.matches_of_team

    def slow(conn, team_id):
        entered.release()
        gate.wait(5)
        return original(conn, team_id)

    with TestClient(app) as warm:  # a token gets its own budget once it has authenticated
        assert warm.get("/api/v1/codebooks", headers=auth(team["token"])).status_code == 200
    monkeypatch.setattr(repo, "matches_of_team", slow)
    statuses = []

    def worker():
        with TestClient(app) as client:
            statuses.append(client.get("/api/v1/me", headers=auth(team["token"])).status_code)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    entered.acquire(timeout=5)
    entered.acquire(timeout=5)
    with TestClient(app) as client:
        third = client.get("/api/v1/me", headers=auth(team["token"]))
    gate.set()
    for t in threads:
        t.join()
    assert third.status_code == 429 and third.json()["error"]["code"] == "too_many_concurrent_requests"
    assert statuses == [200, 200]
    with TestClient(app) as client:
        assert client.get("/api/v1/me", headers=auth(team["token"])).status_code == 200


# --- cost of reads and writes does not grow with the match ------------------------------------


def test_single_event_in_out_uses_previous_substitution_only(client, team_a, monkeypatch):
    from app import repo

    api = Api(client, team_a)
    first, second, third = cid(), cid(), cid()
    api.put(first, api.sub())
    api.put(second, api.sub(jerseys=(20, 21, 22, 23, 24), time="01:00"))
    api.put(cid(), api.sub(team="away", time="01:30"))
    monkeypatch.setattr(repo, "list_events", lambda *a, **k: pytest.fail("whole match was read"))
    stored = api.get(second).json()["event"]
    assert sorted(stored["in"]) == sorted(api.home[j] for j in (20, 21, 22, 23, 24))
    written = api.put(third, api.sub(jerseys=(10, 21, 22, 23, 24), time="02:00", period=2)).json()["event"]
    assert written["in"] == [api.home[10]] and written["out"] == [api.home[20]]


def test_default_event_limit_is_500():
    assert Settings().max_events == 500


# --- safe defaults ---------------------------------------------------------------------------


def test_demo_is_off_by_default(monkeypatch):
    monkeypatch.delenv("ZAPI_DEMO", raising=False)
    assert Settings().demo is False and Settings.from_env().demo is False


def test_database_with_demo_team_refuses_to_start_without_demo(tmp_path):
    create_app(make_settings(tmp_path, demo=True))
    with pytest.raises(SystemExit) as info:
        create_app(make_settings(tmp_path, demo=False))
    assert "ZAPI_DEMO" in str(info.value)


def test_docs_page_only_in_demo_mode(tmp_path):
    with TestClient(create_app(make_settings(tmp_path / "a", demo=True))) as demo:
        assert demo.get("/api/docs").status_code == 200
        assert demo.get("/docs/oauth2-redirect").status_code == 404
    with TestClient(create_app(make_settings(tmp_path / "b", demo=False))) as shared:
        assert shared.get("/api/docs").status_code == 404
        assert shared.get("/api/openapi.json").status_code == 200


# --- small things ----------------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["99999999999999999999999999", "0", "-1", "2147483648"])
def test_out_of_range_ids_are_422_not_500(client, team_a, bad):
    r = client.get(f"/api/v1/matches/{bad}", headers=auth(team_a["token"]))
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"


def test_trailing_slash_is_not_redirected(client, team_a):
    r = client.get("/api/v1/me/", headers={**auth(team_a["token"]), "Host": "evil.example"},
                   follow_redirects=False)
    assert r.status_code == 404 and "location" not in r.headers


def test_match_file_with_wrong_types_is_a_clear_error(tmp_path, fixture_match):
    import json

    from app.seed import load_match_file

    fixture_match["roster"]["home"][0]["jersey"] = "7"
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(fixture_match), encoding="utf-8")
    with pytest.raises(ValueError, match="jersey"):
        load_match_file(str(path))


# --- nothing organiser-only ships in this repository -------------------------------------------


@pytest.mark.parametrize("path", ["/jury", "/api/v1/jury/teams", "/api/v1/jury/matches/1/events"])
def test_no_jury_page_or_routes(client, team_a, path):
    r = client.get(path, headers=auth(team_a["token"]))
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


def test_api_description_has_no_jury_or_match_kinds(client):
    text = client.get("/api/openapi.json").text
    for word in ("jury", "porot", "measurement", "měřic", "sdílen"):
        assert word not in text.lower(), word


def test_requests_are_not_stored(client, team_a, settings):
    api = Api(client, team_a)
    api.put(cid(), api.shot())
    tables = {row[0] for row in connect(settings.db_path).execute("SELECT name FROM sqlite_master")}
    assert "request_log" not in tables


def test_database_of_an_older_version_is_refused_with_advice(tmp_path):
    settings = make_settings(tmp_path)
    conn = connect(settings.db_path)
    conn.execute("CREATE TABLE team (id INTEGER PRIMARY KEY, name TEXT, token_hash TEXT, role TEXT)")
    conn.commit()
    conn.close()
    with pytest.raises(SystemExit) as info:
        create_app(settings)
    assert "docker compose down -v" in str(info.value)
