import pytest
from fastapi.testclient import TestClient

from app import cli
from app.main import create_app
from tests.conftest import FIXTURE_MATCH, auth, make_settings


def run(monkeypatch, capsys, settings, *argv):
    monkeypatch.setenv("ZAPI_DB_PATH", settings.db_path)
    code = cli.main(list(argv))
    return code, capsys.readouterr().out


def test_add_teams_prints_tokens_that_work(tmp_path, monkeypatch, capsys):
    settings = make_settings(tmp_path)
    code, out = run(monkeypatch, capsys, settings, "add-teams", str(FIXTURE_MATCH), "--names", "Alfa,Beta")
    assert code == 0
    lines = [line.split("\t") for line in out.strip().splitlines() if "\t" in line and not line.startswith("#")]
    assert [l[0] for l in lines] == ["Alfa", "Beta"] and all(len(l) == 3 for l in lines)
    with TestClient(create_app(settings)) as client:
        me = client.get("/api/v1/me", headers=auth(lines[0][1])).json()
    assert me["team"]["name"] == "Alfa"
    assert {str(m["id"]) for m in me["matches"]} == {lines[0][2]}


def test_add_teams_count(tmp_path, monkeypatch, capsys):
    settings = make_settings(tmp_path)
    _, out = run(monkeypatch, capsys, settings, "add-teams", str(FIXTURE_MATCH), "--count", "3")
    names = [line.split("\t")[0] for line in out.strip().splitlines() if "\t" in line and not line.startswith("#")]
    assert names == ["Tým 1", "Tým 2", "Tým 3"]


def test_tokens_file_recreates_same_tokens(tmp_path, monkeypatch, capsys):
    first = make_settings(tmp_path / "one")
    _, out = run(monkeypatch, capsys, first, "add-teams", str(FIXTURE_MATCH), "--names", "Alfa,Beta")
    tokens_file = tmp_path / "tokens.tsv"
    tokens_file.write_text(out, encoding="utf-8")
    second = make_settings(tmp_path / "two")
    code, _ = run(monkeypatch, capsys, second, "add-teams", str(FIXTURE_MATCH), "--tokens-file", str(tokens_file))
    assert code == 0
    token = [l.split("\t") for l in out.splitlines() if l.startswith("Beta\t")][0][1]
    with TestClient(create_app(second)) as client:
        assert client.get("/api/v1/me", headers=auth(token)).json()["team"]["name"] == "Beta"


def test_add_teams_refuses_duplicate_token(tmp_path, monkeypatch, capsys):
    settings = make_settings(tmp_path)
    _, out = run(monkeypatch, capsys, settings, "add-teams", str(FIXTURE_MATCH), "--names", "Alfa")
    tokens_file = tmp_path / "tokens.tsv"
    tokens_file.write_text(out, encoding="utf-8")
    code, _ = run(monkeypatch, capsys, settings, "add-teams", str(FIXTURE_MATCH), "--tokens-file", str(tokens_file))
    assert code != 0


def test_status_lists_teams_without_tokens(tmp_path, monkeypatch, capsys):
    settings = make_settings(tmp_path)
    _, out = run(monkeypatch, capsys, settings, "add-teams", str(FIXTURE_MATCH), "--names", "Alfa")
    token = [l.split("\t") for l in out.splitlines() if l.startswith("Alfa\t")][0][1]
    code, status = run(monkeypatch, capsys, settings, "status")
    assert code == 0 and "Alfa" in status and "0 událostí" in status and token not in status


@pytest.mark.parametrize("command", ["add-jury", "reset-jury"])
def test_jury_commands_are_gone(command):
    with pytest.raises(SystemExit):
        cli.main([command])
