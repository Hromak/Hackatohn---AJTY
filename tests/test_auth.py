import pytest
from fastapi.testclient import TestClient

from app.db import connect
from app.main import create_app
from tests.conftest import auth, make_settings


def test_me_requires_token(client):
    r = client.get("/api/v1/me")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized"
    assert r.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "header",
    [
        b"demo",
        b"Bearer ",
        b"Bearer " + b"x" * 5000,
        b"Basic abc",
        "Bearer žluť".encode("utf-8"),
        b"Bearer wrong-token",
        b"Bearer two words",
    ],
)
def test_bad_authorization_is_401(client, team_a, header):
    r = client.get("/api/v1/me", headers={"Authorization": header})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized"


def test_me_lists_own_matches(client, team_a, team_b):
    r = client.get("/api/v1/me", headers=auth(team_a["token"]))
    assert r.status_code == 200
    body = r.json()
    assert body["team"] == {"id": team_a["id"], "name": "Tým A"}
    assert all(set(m) == {"id", "home", "away", "date"} for m in body["matches"])
    assert {m["id"] for m in body["matches"]} == {team_a["training"], team_a["second"]}


def test_token_is_stored_hashed(settings, team_a):
    conn = connect(settings.db_path)
    dump = "\n".join(str(tuple(row)) for row in conn.execute("SELECT * FROM team"))
    assert team_a["token"] not in dump


def test_bootstrap_creates_demo_team_with_one_match(tmp_path):
    app = create_app(make_settings(tmp_path, demo=True))
    with TestClient(app) as c:
        demo = c.get("/api/v1/me", headers=auth("demo"))
    assert demo.status_code == 200 and demo.json()["team"]["name"] == "Demo"
    assert len(demo.json()["matches"]) == 1


def test_bootstrap_is_idempotent(tmp_path):
    s = make_settings(tmp_path, demo=True)
    create_app(s)
    create_app(s)
    conn = connect(s.db_path)
    assert conn.execute("SELECT COUNT(*) FROM team").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM match").fetchone()[0] == 1


def test_no_demo_team_without_demo_mode(tmp_path):
    app = create_app(make_settings(tmp_path, demo=False))
    with TestClient(app) as c:
        assert c.get("/api/v1/me", headers=auth("demo")).status_code == 401
