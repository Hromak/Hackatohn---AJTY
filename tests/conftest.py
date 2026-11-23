import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import connect, transaction
from app.main import create_app
from app.seed import add_team, create_match, load_match_file

FIXTURE_MATCH = Path(__file__).parent / "fixtures" / "match-small.json"


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def make_settings(tmp_path, **overrides) -> Settings:
    values = dict(
        db_path=str(tmp_path / "test.sqlite"),
        demo=False,
        demo_match_path=str(FIXTURE_MATCH),
        demo_matches_dir=str(tmp_path / "no-extra-matches"),
        rate_per_sec=10_000,
        rate_burst=10_000,
        global_rate_per_sec=10_000,
        global_rate_burst=10_000,
        max_in_flight=100,
    )
    values.update(overrides)
    return Settings(**values)


@pytest.fixture
def settings(tmp_path):
    return make_settings(tmp_path)


@pytest.fixture
def app(settings):
    return create_app(settings)


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


def seed_team(settings: Settings, name: str) -> dict:
    conn = connect(settings.db_path)
    try:
        with transaction(conn):
            match = load_match_file(str(FIXTURE_MATCH))
            team_id, token = add_team(conn, name, match)
            second = create_match(conn, team_id, match)
        first = conn.execute(
            "SELECT MIN(id) FROM match WHERE team_id = ?", (team_id,)
        ).fetchone()[0]
    finally:
        conn.close()
    # "training" is the team's match from add_team; "second" is one more with the same roster
    return {"id": team_id, "token": token, "training": first, "second": second}


@pytest.fixture
def team_a(app, settings):
    return seed_team(settings, "Tým A")


@pytest.fixture
def team_b(app, settings):
    return seed_team(settings, "Tým B")


@pytest.fixture
def fixture_match():
    return json.loads(FIXTURE_MATCH.read_text(encoding="utf-8"))
