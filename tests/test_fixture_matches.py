"""Real matches shipped with the repository: rosters only, loaded for the local demo team."""
import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import connect
from app.main import create_app
from app.seed import load_match_file
from tests.conftest import FIXTURE_MATCH, auth, make_settings

ROOT = Path(__file__).resolve().parent.parent
MATCHES = ROOT / "data" / "matches"


def shipped():
    return sorted(MATCHES.glob("*.json"))


def test_repository_ships_several_real_matches():
    assert len(shipped()) >= 5


@pytest.mark.parametrize("path", shipped(), ids=lambda p: p.name)
def test_shipped_match_is_valid_and_has_rosters_only(path):
    match = load_match_file(str(path))
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert set(raw) == {"competition", "date", "venue", "home", "away", "periods", "roster", "formations"}
    assert match["formations"] == {"home": [], "away": []}
    for side in ("home", "away"):
        assert len(match["roster"][side]) >= 12
        for player in match["roster"][side]:
            assert set(player) == {"jersey", "first_name", "last_name", "position", "captain"}
            assert player["first_name"] and player["last_name"]


def test_demo_team_gets_every_match_from_the_directory(tmp_path):
    directory = tmp_path / "matches"
    directory.mkdir()
    for name in ("b.json", "a.json"):
        match = json.loads(FIXTURE_MATCH.read_text(encoding="utf-8"))
        match["home"]["name"] = f"Domácí {name}"
        (directory / name).write_text(json.dumps(match), encoding="utf-8")
    (directory / "poznamka.txt").write_text("není utkání", encoding="utf-8")
    settings = make_settings(tmp_path, demo=True, demo_matches_dir=str(directory))
    with TestClient(create_app(settings)) as client:
        matches = client.get("/api/v1/me", headers=auth("demo")).json()["matches"]
        assert len(matches) == 3
        extra = matches[1:]
        names = [client.get(f"/api/v1/matches/{m['id']}", headers=auth("demo")).json()["home"]["name"]
                 for m in extra]
        assert names == ["Domácí a.json", "Domácí b.json"]
        roster = client.get(f"/api/v1/matches/{extra[0]['id']}/roster", headers=auth("demo"))
        assert roster.status_code == 200
    # a restart must not load them a second time
    with TestClient(create_app(settings)) as client:
        assert len(client.get("/api/v1/me", headers=auth("demo")).json()["matches"]) == 3


def test_missing_directory_is_not_an_error(tmp_path):
    settings = make_settings(tmp_path, demo=True, demo_matches_dir=str(tmp_path / "nothing"))
    with TestClient(create_app(settings)) as client:
        assert len(client.get("/api/v1/me", headers=auth("demo")).json()["matches"]) == 1


def test_broken_file_in_the_directory_stops_the_start(tmp_path):
    directory = tmp_path / "matches"
    directory.mkdir()
    (directory / "rozbite.json").write_text("{", encoding="utf-8")
    with pytest.raises((ValueError, SystemExit)) as info:
        create_app(make_settings(tmp_path, demo=True, demo_matches_dir=str(directory)))
    assert "rozbite.json" in str(info.value)


def test_shared_instance_ignores_the_directory(tmp_path):
    directory = tmp_path / "matches"
    directory.mkdir()
    shutil.copy(FIXTURE_MATCH, directory / "a.json")
    settings = make_settings(tmp_path, demo=False, demo_matches_dir=str(directory))
    create_app(settings)
    assert connect(settings.db_path).execute("SELECT COUNT(*) FROM match").fetchone()[0] == 0


def test_directory_comes_from_the_environment(monkeypatch):
    assert Settings().demo_matches_dir == "data/matches"
    monkeypatch.setenv("ZAPI_DEMO_MATCHES_DIR", "/somewhere")
    assert Settings.from_env().demo_matches_dir == "/somewhere"


def test_image_contains_the_matches():
    assert "COPY data/matches ./data/matches" in (ROOT / "Dockerfile").read_text(encoding="utf-8")
