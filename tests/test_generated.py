import json
import re
from pathlib import Path

from app import cli

ROOT = Path(__file__).resolve().parent.parent


def refs(node):
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "$ref":
                yield value
            else:
                yield from refs(value)
    elif isinstance(node, list):
        for item in node:
            yield from refs(item)


def spec(client):
    return client.get("/api/openapi.json").json()


def test_every_ref_resolves(client):
    s = spec(client)
    for ref in set(refs(s)):
        assert ref.startswith("#/components/schemas/"), ref
        assert ref.rsplit("/", 1)[1] in s["components"]["schemas"], ref


def test_event_request_schemas_are_described(client):
    schemas = spec(client)["components"]["schemas"]
    assert schemas["ShotIn"]["additionalProperties"] is False
    assert set(schemas["ShotIn"]["required"]) == {"type", "team", "period", "time", "x", "y", "result", "shooter_id"}
    assert set(schemas["SubstitutionIn"]["required"]) == {"type", "team", "period", "time", "players"}
    assert "in" in schemas["SubstitutionOut"]["properties"]


def test_no_framework_validation_schema(client):
    s = spec(client)
    assert "HTTPValidationError" not in s["components"]["schemas"]
    assert "HTTPValidationError" not in json.dumps(s)


def test_bearer_security_is_declared(client):
    s = spec(client)
    assert s["components"]["securitySchemes"]["bearer"] == {"type": "http", "scheme": "bearer"}
    assert s["paths"]["/api/v1/me"]["get"]["security"] == [{"bearer": []}]
    assert "security" not in s["paths"]["/api/health"]["get"]


def test_openapi_file_is_current(tmp_path):
    out = tmp_path / "openapi.json"
    assert cli.main(["export-openapi", "--out", str(out)]) == 0
    assert out.read_text(encoding="utf-8") == (ROOT / "docs" / "openapi.json").read_text(encoding="utf-8"), \
        "run: uv run python -m app.cli export-openapi"


def test_samples_are_current(tmp_path):
    assert cli.main(["export-samples", "--out", str(tmp_path)]) == 0
    committed = sorted(p.name for p in (ROOT / "sample-data").glob("*.json"))
    assert sorted(p.name for p in tmp_path.glob("*.json")) == committed
    for name in committed:
        assert (tmp_path / name).read_text(encoding="utf-8") == (ROOT / "sample-data" / name).read_text(encoding="utf-8"), \
            f"{name} is stale; run: uv run python -m app.cli export-samples"


def test_samples_cover_the_guide(tmp_path):
    names = {p.name for p in (ROOT / "sample-data").glob("*.json")}
    assert {"me.json", "codebooks.json", "matches.json", "match.json", "roster.json", "formations.json",
            "events-empty.json", "event-shot-put-request.json", "event-shot-put-response.json",
            "event-substitution-put-request.json", "event-substitution-put-response.json",
            "error-unknown-player.json", "full-match-events.json"} <= names


def test_demo_match_has_no_real_source():
    demo = json.loads((ROOT / "data" / "demo-match.json").read_text(encoding="utf-8"))
    assert "source" not in demo
    # Public code and documents may say that private/ exists, but must not point into it.
    public = (list((ROOT / "app").rglob("*.py")) + list((ROOT / "scripts").glob("*.py"))
              + list((ROOT / "podklady").glob("*.md")) + list((ROOT / "docs").glob("*.md"))
              + [ROOT / "README.md", ROOT / "AGENTS.md", ROOT / "Dockerfile", ROOT / "compose.yaml"])
    for path in public:
        if path.exists():
            assert re.search(r"private/\w", path.read_text(encoding="utf-8")) is None, path
