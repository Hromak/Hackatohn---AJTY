import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import auth, make_settings, seed_team
from tests.helpers import Api, cid


@pytest.fixture
def api(client, team_a):
    return Api(client, team_a)


def test_put_creates_then_same_put_is_unchanged(api):
    c = cid()
    first = api.put(c, api.shot())
    assert first.status_code == 201
    assert first.json()["created"] is True and first.json()["unchanged"] is False
    assert first.json()["event"]["version"] == 1
    second = api.put(c, api.shot())
    assert second.status_code == 200
    assert second.json()["created"] is False and second.json()["unchanged"] is True
    assert second.json()["event"]["version"] == 1
    assert len(api.events()["events"]) == 1


def test_event_out_shape(api):
    c = cid()
    event = api.put(c, api.shot()).json()["event"]
    assert event["client_id"] == c and event["type"] == "shot" and event["team"] == "home"
    assert event["period"] == 1 and event["time"] == "07:42" and event["seq"] == 1
    assert event["x"] == 600 and event["result"] == "on_goal" and event["strength"] == "even"
    assert event["goalkeeper_id"] is None and event["assist_id"] is None and event["on_ice"] is None
    assert event["warnings"] == [] and event["created_at"] == event["updated_at"]
    assert "deleted_at" not in event and "in" not in event


def test_put_with_changed_body_updates_same_event(api):
    c = cid()
    api.put(c, api.shot())
    r = api.put(c, api.shot(team="away", shooter_id=api.away[10], x=200))
    assert r.status_code == 200
    assert r.json()["unchanged"] is False and r.json()["event"]["version"] == 2
    events = api.events()["events"]
    assert len(events) == 1 and events[0]["team"] == "away"


def test_unchanged_replay_wins_over_stale_version(api):
    c = cid()
    api.put(c, api.shot())
    changed = api.shot(x=610, version=1)
    assert api.put(c, changed).json()["event"]["version"] == 2
    replay = api.put(c, changed)
    assert replay.status_code == 200 and replay.json()["unchanged"] is True
    assert replay.json()["event"]["version"] == 2


def test_stale_version_with_different_content_is_409(api):
    c = cid()
    api.put(c, api.shot())
    api.put(c, api.shot(x=610))
    r = api.put(c, api.shot(x=620, version=1))
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "version_conflict"
    assert r.json()["event"]["version"] == 2 and r.json()["event"]["x"] == 610


def test_current_version_updates(api):
    c = cid()
    api.put(c, api.shot())
    assert api.put(c, api.shot(x=610, version=1)).status_code == 200


def test_type_change_is_422(api):
    c = cid()
    api.put(c, api.shot())
    r = api.put(c, api.sub())
    assert r.status_code == 422 and r.json()["error"]["code"] == "type_change"


def test_delete_is_idempotent_and_final(api):
    c = cid()
    api.put(c, api.shot())
    assert api.delete(c).status_code == 204
    assert api.delete(c).status_code == 204
    assert api.events()["events"] == []
    deleted = api.events(include_deleted=True)["events"]
    assert len(deleted) == 1 and deleted[0]["deleted_at"]
    assert api.get(c).json()["event"]["deleted_at"]
    r = api.put(c, api.shot())
    assert r.status_code == 410 and r.json()["error"]["code"] == "deleted"


def test_delete_unknown_is_404(api):
    r = api.delete(cid())
    assert r.status_code == 404 and r.json()["error"]["code"] == "unknown_event"


def test_get_unknown_event_is_404(api):
    assert api.get(cid()).json()["error"]["code"] == "unknown_event"


def test_two_substitutions_same_time_same_team_conflict(api):
    first, second, away = cid(), cid(), cid()
    assert api.put(first, api.sub()).status_code == 201
    r = api.put(second, api.sub(jerseys=(20, 21, 22, 23, 24)))
    assert r.status_code == 409 and r.json()["error"]["code"] == "duplicate_time"
    assert api.put(away, api.sub(team="away")).status_code == 201
    api.delete(first)
    assert api.put(second, api.sub(jerseys=(20, 21, 22, 23, 24))).status_code == 201


def test_substitution_keeps_its_own_time_on_update(api):
    c = cid()
    api.put(c, api.sub())
    assert api.put(c, api.sub(strength="power_play")).status_code == 200


def test_in_out_follow_previous_lineup(api):
    first, second = cid(), cid()
    one = api.put(first, api.sub()).json()["event"]
    assert one["out"] == [] and sorted(one["in"]) == sorted(one["players"])
    two = api.put(second, api.sub(jerseys=(10, 11, 20, 21, 22), time="01:05")).json()["event"]
    assert sorted(two["in"]) == sorted(api.home[j] for j in (20, 21, 22))
    assert sorted(two["out"]) == sorted(api.home[j] for j in (12, 13, 14))
    api.put(first, api.sub(jerseys=(20, 21, 22, 23, 24)))
    two_again = next(e for e in api.events()["events"] if e["client_id"] == second)
    assert sorted(two_again["in"]) == sorted(api.home[j] for j in (10, 11))
    assert sorted(two_again["out"]) == sorted(api.home[j] for j in (23, 24))


def test_in_out_ignores_other_team_and_deleted(api):
    first, away, mid, last = cid(), cid(), cid(), cid()
    api.put(first, api.sub())
    api.put(away, api.sub(team="away", time="00:30"))
    api.put(mid, api.sub(jerseys=(20, 21, 22, 23, 24), time="01:00"))
    api.delete(mid)
    event = api.put(last, api.sub(jerseys=(10, 11, 12, 13, 40), time="02:00")).json()["event"]
    assert event["in"] == [api.home[40]] and event["out"] == [api.home[14]]


def test_events_are_ordered_by_period_time_seq(api):
    ids = [cid() for _ in range(4)]
    api.put(ids[0], api.shot(period=2, time="03:00"))
    api.put(ids[1], api.shot(period=1, time="10:00"))
    api.put(ids[2], api.shot(period=1, time="02:00"))
    api.put(ids[3], api.shot(period=1, time="10:00", x=700))
    assert [e["client_id"] for e in api.events()["events"]] == [ids[2], ids[1], ids[3], ids[0]]


def test_shot_from_own_half_has_warning(api):
    event = api.put(cid(), api.shot(x=200)).json()["event"]
    assert event["warnings"] == ["shot_from_own_half"]


def test_goal_with_assist_and_on_ice_roundtrip(api):
    c = cid()
    on_ice = {"home": [api.home[j] for j in (1, 10, 11, 12, 13, 14)],
              "away": [api.away[j] for j in (1, 10, 11, 12, 13, 14)]}
    body = api.shot(result="goal", goalkeeper_id=api.away[1], assist_id=api.home[11], on_ice=on_ice,
                    strength="power_play")
    assert api.put(c, body).status_code == 201
    stored = api.get(c).json()["event"]
    assert stored["assist_id"] == api.home[11] and stored["on_ice"] == on_ice
    assert stored["goalkeeper_id"] == api.away[1] and stored["strength"] == "power_play"


def test_rule_error_reaches_client_with_fields(api):
    r = api.put(cid(), api.shot(shooter_id=999999))
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "unknown_player"
    assert r.json()["error"]["fields"] == {"shooter_id": "unknown_player"}
    assert api.events()["events"] == []


def test_reset_training_clears_and_frees_client_ids(api):
    c = cid()
    api.put(c, api.shot())
    api.put(cid(), api.sub())
    r = api.reset()
    assert r.status_code == 200 and r.json() == {"deleted": 2}
    assert api.events()["events"] == []
    again = api.put(c, api.shot())
    assert again.status_code == 201 and again.json()["event"]["seq"] == 1


def test_reset_frees_deleted_client_id(api):
    c = cid()
    api.put(c, api.shot())
    api.delete(c)
    api.reset()
    assert api.put(c, api.shot()).status_code == 201


def test_every_match_of_the_team_can_be_reset(client, team_a):
    api = Api(client, team_a, "second")
    api.put(cid(), api.shot())
    r = api.reset()
    assert r.status_code == 200 and r.json() == {"deleted": 1}
    assert api.events()["events"] == []


def test_event_limit(tmp_path):
    settings = make_settings(tmp_path, max_events=3)
    with TestClient(create_app(settings)) as client:
        api = Api(client, seed_team(settings, "Limit"))
        ids = [cid() for _ in range(4)]
        for index, c in enumerate(ids[:3]):
            assert api.put(c, api.shot(time=f"0{index}:00")).status_code == 201
        r = api.put(ids[3], api.shot(time="05:00"))
        assert r.status_code == 422 and r.json()["error"]["code"] == "event_limit"
        assert api.put(ids[0], api.shot(time="06:00")).status_code == 200


def test_other_team_cannot_read_or_write_events(client, team_a, team_b):
    mine = Api(client, team_a)
    c = cid()
    mine.put(c, mine.shot())
    base = f"/api/v1/matches/{team_a['training']}"
    other = auth(team_b["token"])
    assert client.get(f"{base}/events", headers=other).status_code == 404
    assert client.get(f"{base}/events/{c}", headers=other).status_code == 404
    assert client.put(f"{base}/events/{c}", json=mine.shot(), headers=other).status_code == 404
    assert client.delete(f"{base}/events/{c}", headers=other).status_code == 404
    assert client.post(f"{base}/reset", headers=other).status_code == 404
    assert len(mine.events()["events"]) == 1


def test_match_version_grows_on_every_change(api):
    def version():
        return api.events()["match_version"]

    c = cid()
    assert version() == 0
    api.put(c, api.shot())
    assert version() == 1
    api.put(c, api.shot())
    assert version() == 1
    api.put(c, api.shot(x=610))
    assert version() == 2
    api.delete(c)
    assert version() == 3
    api.reset()
    assert version() == 4


def test_same_client_id_in_two_matches_is_independent(client, team_a):
    training, second = Api(client, team_a), Api(client, team_a, "second")
    c = cid()
    assert training.put(c, training.shot()).status_code == 201
    assert second.put(c, second.shot()).status_code == 201
