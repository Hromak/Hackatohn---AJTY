from app.db import connect, init_schema


def test_health_ok(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_unknown_route_has_error_shape(client):
    r = client.get("/api/v1/nope")
    assert r.status_code == 404
    body = r.json()
    assert body["error"]["code"] == "not_found"
    assert body["error"]["message"]


def test_wrong_method_has_error_shape(client):
    r = client.post("/api/health")
    assert r.status_code == 405
    assert r.json()["error"]["code"] == "method_not_allowed"


def test_events_survive_new_connection(tmp_path):
    path = str(tmp_path / "x.sqlite")
    c1 = connect(path)
    init_schema(c1)
    c1.execute(
        "INSERT INTO team(name, token_hash, created_at) VALUES ('A', 'h', 'now')"
    )
    c1.commit()
    c1.close()
    c2 = connect(path)
    assert c2.execute("SELECT name FROM team").fetchone()["name"] == "A"


def test_missing_data_directory_is_created(tmp_path):
    path = tmp_path / "a" / "b" / "x.sqlite"
    conn = connect(str(path))
    init_schema(conn)
    assert path.exists()


def test_unwritable_db_path_fails_at_startup_with_clear_message(tmp_path):
    import pytest

    from app.main import create_app
    from tests.conftest import make_settings

    blocker = tmp_path / "file"
    blocker.write_text("not a directory")
    with pytest.raises(SystemExit) as info:
        create_app(make_settings(tmp_path, db_path=str(blocker / "x.sqlite")))
    assert "ZAPI_DB_PATH" in str(info.value) and str(blocker) in str(info.value)


def test_demo_start_announces_the_demo_token(tmp_path, caplog):
    import logging

    from app.main import create_app
    from tests.conftest import make_settings

    with caplog.at_level(logging.INFO, logger="zapi"):
        create_app(make_settings(tmp_path, demo=True, demo_token="demo"))
    assert any("Bearer demo" in record.getMessage() for record in caplog.records)
