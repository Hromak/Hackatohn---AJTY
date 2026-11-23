from tests.conftest import auth


def get(client, team, path):
    return client.get(f"/api/v1{path}", headers=auth(team["token"]))


def test_matches_list_equals_me(client, team_a):
    assert get(client, team_a, "/matches").json()["matches"] == get(client, team_a, "/me").json()["matches"]


def test_match_header_has_periods_with_overtime(client, team_a):
    r = get(client, team_a, f"/matches/{team_a['training']}")
    assert r.status_code == 200
    body = r.json()
    assert body["home"] == {"name": "FBC Domácí Test", "short_name": "Domácí"}
    assert [p["period"] for p in body["periods"]] == [1, 2, 3, 4]
    assert body["periods"][0] == {"period": 1, "label": "1. třetina", "length": "20:00", "overtime": False}
    assert body["periods"][3] == {"period": 4, "label": "Prodloužení", "length": "05:00", "overtime": True}
    assert body["version"] == 0
    assert "kind" not in body


def test_roster_split_by_side_and_sorted(client, team_a):
    body = get(client, team_a, f"/matches/{team_a['training']}/roster").json()
    assert [p["jersey"] for p in body["home"]] == sorted(p["jersey"] for p in body["home"])
    assert len(body["home"]) == 14 and len(body["away"]) == 14
    first = body["home"][0]
    assert set(first) == {"id", "jersey", "first_name", "last_name", "position", "captain"}
    assert first["position"] == "G" and first["captain"] is False
    assert {p["id"] for p in body["home"]}.isdisjoint({p["id"] for p in body["away"]})


def test_formations_reference_roster_ids(client, team_a):
    roster = get(client, team_a, f"/matches/{team_a['training']}/roster").json()
    forms = get(client, team_a, f"/matches/{team_a['training']}/formations").json()
    for side in ("home", "away"):
        ids = {p["id"] for p in roster[side]}
        assert [f["line"] for f in forms[side]] == [1, 2]
        for line in forms[side]:
            for slot in ("lw", "c", "rw", "ld", "rd"):
                assert line[slot] is None or line[slot] in ids
        assert forms[side][1]["rd"] is None


def test_foreign_match_is_404_like_unknown(client, team_a, team_b):
    foreign = get(client, team_b, f"/matches/{team_a['training']}")
    unknown = get(client, team_b, "/matches/999999")
    assert foreign.status_code == unknown.status_code == 404
    assert foreign.json() == unknown.json()
    assert foreign.json()["error"]["code"] == "not_found"
    for suffix in ("/roster", "/formations"):
        assert get(client, team_b, f"/matches/{team_a['training']}{suffix}").status_code == 404


def test_codebooks_rink(client, team_a):
    body = get(client, team_a, "/codebooks").json()
    assert body["rink"]["width"] == 890 and body["rink"]["height"] == 501
    assert body["rink"]["home_attacks"] == "right" and body["rink"]["center_x"] == 445
    assert [r["code"] for r in body["shot_results"]] == ["miss", "on_goal", "post", "goal"]
    assert [s["code"] for s in body["formation_slots"]] == ["lw", "c", "rw", "ld", "rd"]


def test_non_integer_match_id_is_422_error_shape(client, team_a):
    r = get(client, team_a, "/matches/abc")
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"


def test_read_endpoints_need_token(client, team_a):
    for path in ("/codebooks", "/matches", f"/matches/{team_a['training']}/roster"):
        assert client.get(f"/api/v1{path}").status_code == 401
