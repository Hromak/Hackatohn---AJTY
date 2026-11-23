import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.middleware import TokenBucket
from tests.conftest import auth, make_settings, seed_team
from tests.helpers import Api, cid

ORIGIN = {"Origin": "https://tablet.example.org"}


def test_cors_preflight_needs_no_token(client, team_a):
    r = client.options(
        f"/api/v1/matches/{team_a['training']}/events/{cid()}",
        headers={**ORIGIN, "Access-Control-Request-Method": "PUT",
                 "Access-Control-Request-Headers": "authorization,content-type"},
    )
    assert r.status_code in (200, 204)
    assert r.headers["access-control-allow-origin"] == "*"
    assert "PUT" in r.headers["access-control-allow-methods"]
    assert "authorization" in r.headers["access-control-allow-headers"].lower()
    assert "access-control-allow-credentials" not in r.headers


def test_success_and_error_responses_carry_cors_headers(client, team_a):
    ok = client.get("/api/v1/me", headers={**auth(team_a["token"]), **ORIGIN})
    denied = client.get("/api/v1/me", headers=ORIGIN)
    assert ok.headers["access-control-allow-origin"] == "*"
    assert denied.status_code == 401 and denied.headers["access-control-allow-origin"] == "*"


def test_body_over_limit_is_413(client, team_a):
    api = Api(client, team_a)
    r = client.put(f"{api.base}/events/{cid()}", content=b"x" * 17_000,
                   headers={**api.headers, **ORIGIN, "Content-Type": "application/json"})
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "payload_too_large"
    assert r.headers["access-control-allow-origin"] == "*"


def test_body_at_limit_is_not_rejected_for_size(client, team_a):
    api = Api(client, team_a)
    r = client.put(f"{api.base}/events/{cid()}", content=b" " * 16_384,
                   headers={**api.headers, "Content-Type": "application/json"})
    assert r.status_code == 400  # not JSON, but not too large either


def test_token_bucket_refills():
    bucket = TokenBucket(rate=1, burst=3)
    assert [bucket.allow("k", now=100.0) for _ in range(4)] == [True, True, True, False]
    assert bucket.allow("other", now=100.0) is True
    assert bucket.allow("k", now=102.0) is True


def test_token_bucket_forgets_idle_keys():
    bucket = TokenBucket(rate=10, burst=5)
    for i in range(5000):
        bucket.allow(f"key-{i}", now=100.0)
    bucket.allow("later", now=10_000.0)
    assert len(bucket) < 100


def test_rate_limit_returns_429_json_with_cors(tmp_path):
    settings = make_settings(tmp_path, rate_per_sec=0.001, rate_burst=3)
    with TestClient(create_app(settings)) as client:
        team = seed_team(settings, "Rychlík")
        headers = {**auth(team["token"]), **ORIGIN}
        # the first request of a token is counted with the unverified traffic, then it has its own budget
        statuses = [client.get("/api/v1/me", headers=headers).status_code for _ in range(5)]
        last = client.get("/api/v1/me", headers=headers)
        other = seed_team(settings, "Klidný")
        calm = client.get("/api/v1/me", headers=auth(other["token"]))
    assert statuses == [200, 200, 200, 200, 429]
    assert last.status_code == 429 and last.json()["error"]["code"] == "rate_limited"
    assert last.headers["retry-after"] == "1"
    assert last.headers["access-control-allow-origin"] == "*"
    assert calm.status_code == 200


def test_unverified_traffic_shares_one_small_budget(tmp_path):
    settings = make_settings(tmp_path, rate_per_sec=0.001, rate_burst=5)
    with TestClient(create_app(settings)) as client:
        statuses = [client.get("/api/v1/me").status_code for _ in range(7)]
    assert statuses[:5] == [401] * 5 and statuses[5:] == [429, 429]


def test_global_budget_caps_verified_traffic(tmp_path):
    settings = make_settings(tmp_path, global_rate_per_sec=0.001, global_rate_burst=4)
    with TestClient(create_app(settings)) as client:
        team = seed_team(settings, "Jediný")
        statuses = [client.get("/api/v1/me", headers=auth(team["token"])).status_code for _ in range(6)]
    assert statuses == [200, 200, 200, 200, 429, 429]


def test_health_survives_rate_limit(tmp_path):
    settings = make_settings(tmp_path, rate_per_sec=0.001, rate_burst=2)
    with TestClient(create_app(settings)) as client:
        for _ in range(5):
            client.get("/api/v1/me")
        assert client.get("/api/health").status_code == 200


def switch(client, team, mode):
    return client.put("/api/v1/me/error-mode", json={"mode": mode}, headers=auth(team["token"]))


@pytest.fixture
def demo(tmp_path):
    settings = make_settings(tmp_path, demo=True)
    with TestClient(create_app(settings)) as client:
        me = client.get("/api/v1/me", headers=auth("demo")).json()
        team = {"token": "demo", "training": me["matches"][0]["id"]}
        yield client, team


def test_reject_mode_blocks_writes_not_reads(demo):
    client, team = demo
    api = Api(client, team)
    c = cid()
    assert api.put(c, api.shot()).status_code == 201
    assert switch(client, team, "reject").json() == {"mode": "reject"}
    for response in (api.put(cid(), api.shot()), api.put(c, api.shot(x=610)), api.delete(c), api.reset()):
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "forced_rejection"
    assert len(api.events()["events"]) == 1
    assert client.get("/api/v1/me", headers=api.headers).status_code == 200
    assert switch(client, team, "off").status_code == 200
    assert api.put(cid(), api.shot(time="09:00")).status_code == 201


def test_unavailable_mode_blocks_everything_but_switch(demo):
    client, team = demo
    api = Api(client, team)
    switch(client, team, "unavailable")
    for response in (client.get("/api/v1/me", headers=api.headers),
                     client.get(f"{api.base}/roster", headers=api.headers),
                     api.put(cid(), api.shot())):
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "forced_unavailable"
    assert switch(client, team, "off").status_code == 200
    assert client.get("/api/v1/me", headers=api.headers).status_code == 200


def test_error_mode_rejects_unknown_value(demo):
    client, team = demo
    r = switch(client, team, "slow")
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"


def test_team_switches_its_own_error_mode_without_demo_mode(client, team_a):
    assert switch(client, team_a, "reject").status_code == 200
    api = Api(client, team_a)
    assert api.put(cid(), api.shot()).json()["error"]["code"] == "forced_rejection"
    assert switch(client, team_a, "off").status_code == 200
    assert api.put(cid(), api.shot()).status_code == 201


def test_unexpected_error_is_500_json_with_cors_and_no_details(client, team_a, monkeypatch, settings):
    from app import repo

    def boom(*args, **kwargs):
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr(repo, "matches_of_team", boom)
    r = client.get("/api/v1/me", headers={**auth(team_a["token"]), **ORIGIN})
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "internal_error"
    assert "secret" not in r.text
    assert r.headers["access-control-allow-origin"] == "*"
