import threading

import pytest
from fastapi.testclient import TestClient

from tests.helpers import Api, cid


@pytest.fixture
def api(client, team_a):
    return Api(client, team_a)


@pytest.mark.parametrize("raw", [b"", b"null", b"[]", b"42", b'{"type":"shot"', b"type=shot", b'"text"', b"\xff\xfe"])
def test_body_not_an_object_is_400(api, raw):
    r = api.client.put(f"{api.base}/events/{cid()}", content=raw,
                       headers={**api.headers, "Content-Type": "application/json"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "invalid_json"


def test_content_type_does_not_matter_when_body_is_json(api):
    import json

    r = api.client.put(f"{api.base}/events/{cid()}", content=json.dumps(api.shot()).encode(),
                       headers={**api.headers, "Content-Type": "text/plain"})
    assert r.status_code == 201


def test_unknown_field_is_422_with_fields(api):
    r = api.put(cid(), api.shot(colour="red"))
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"
    assert "colour" in r.json()["error"]["fields"]


def test_missing_field_is_named(api):
    body = api.shot()
    del body["shooter_id"]
    r = api.put(cid(), body)
    assert r.status_code == 422 and "shooter_id" in r.json()["error"]["fields"]


def test_unknown_type_is_422(api):
    r = api.put(cid(), {"type": "penalty", "team": "home", "period": 1, "time": "01:00"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"
    assert "type" in r.json()["error"]["fields"]


@pytest.mark.parametrize("bad", ["abc", "123", "{550e8400-e29b-41d4-a716-446655440000}",
                                 "550e8400e29b41d4a716446655440000",
                                 "550e8400-e29b-41d4-a716-44665544000g"])
def test_bad_client_id_is_422(api, bad):
    r = api.put(bad, api.shot())
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_client_id"
    assert api.get(bad).json()["error"]["code"] == "invalid_client_id"
    assert api.delete(bad).json()["error"]["code"] == "invalid_client_id"


def test_client_id_is_case_insensitive(api):
    c = cid()
    assert api.put(c.upper(), api.shot()).status_code == 201
    assert api.get(c).status_code == 200
    assert api.put(c, api.shot()).json()["unchanged"] is True
    events = api.events()["events"]
    assert len(events) == 1 and events[0]["client_id"] == c


def test_concurrent_identical_puts_store_one_event(app, team_a):
    with TestClient(app) as setup:
        api = Api(setup, team_a)
        body, c = api.shot(), cid()
    statuses, lock = [], threading.Lock()

    def worker():
        with TestClient(app) as client:
            r = client.put(f"{api.base}/events/{c}", json=body, headers=api.headers)
        with lock:
            statuses.append(r.status_code)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(set(statuses)) in ([200, 201], [201])
    assert statuses.count(201) == 1
    with TestClient(app) as check:
        assert len(Api(check, team_a).events()["events"]) == 1


def test_concurrent_distinct_puts_all_stored_with_unique_seq(app, team_a):
    with TestClient(app) as setup:
        api = Api(setup, team_a)
        bodies = [(cid(), api.shot(time=f"{i:02d}:00")) for i in range(12)]
    statuses, lock = [], threading.Lock()

    def worker(c, body):
        with TestClient(app) as client:
            r = client.put(f"{api.base}/events/{c}", json=body, headers=api.headers)
        with lock:
            statuses.append(r.status_code)

    threads = [threading.Thread(target=worker, args=item) for item in bodies]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert statuses == [201] * 12
    with TestClient(app) as check:
        events = Api(check, team_a).events()["events"]
    assert sorted(e["seq"] for e in events) == list(range(1, 13))
