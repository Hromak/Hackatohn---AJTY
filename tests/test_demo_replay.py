import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import auth, make_settings

ROOT = Path(__file__).resolve().parent.parent


def test_demo_match_replays_cleanly(tmp_path):
    settings = make_settings(tmp_path, demo=True, demo_match_path=str(ROOT / "data" / "demo-match.json"))
    events = json.loads((ROOT / "sample-data" / "full-match-events.json").read_text(encoding="utf-8"))
    demo = json.loads((ROOT / "data" / "demo-match.json").read_text(encoding="utf-8"))
    assert len(events) == len(demo["events"]) > 150
    headers = auth("demo")
    with TestClient(create_app(settings)) as client:
        match = client.get("/api/v1/me", headers=headers).json()["matches"][0]["id"]
        base = f"/api/v1/matches/{match}/events"
        first = [client.put(f"{base}/{e['client_id']}", json=e["body"], headers=headers) for e in events]
        assert [r.status_code for r in first] == [201] * len(events), next(
            (r.json() for r in first if r.status_code != 201), None)
        second = [client.put(f"{base}/{e['client_id']}", json=e["body"], headers=headers) for e in events]
        assert all(r.status_code == 200 and r.json()["unchanged"] for r in second)
        stored = client.get(base, headers=headers).json()["events"]
    assert len(stored) == len(events)
    goals = {"home": 0, "away": 0}
    for e in stored:
        if e["type"] == "shot" and e["result"] == "goal":
            goals[e["team"]] += 1
    assert goals == {"home": demo["score"]["home"], "away": demo["score"]["away"]}
    assert not any("shot_from_own_half" in e["warnings"] for e in stored if e["type"] == "shot" and e["result"] == "goal")
