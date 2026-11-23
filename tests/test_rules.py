import pytest
from pydantic import TypeAdapter, ValidationError

from app.errors import ApiError
from app.models import EventIn
from app.rules import MatchContext, Player, in_out, normalize, warnings_for
from app.timeutil import format_mmss, parse_mmss

# home: goalkeeper 1, skaters 2-9; away: goalkeeper 11, skaters 12-19
PLAYERS = {1: Player(1, "home", 1, "G"), 11: Player(11, "away", 1, "G")}
PLAYERS.update({i: Player(i, "home", i, "F") for i in range(2, 10)})
PLAYERS.update({i: Player(i, "away", i, "D") for i in range(12, 20)})
CTX = MatchContext(period_count=3, period_length_s=1200, overtime_s=300, players=PLAYERS)
CTX_NO_OT = MatchContext(period_count=3, period_length_s=1200, overtime_s=None, players=PLAYERS)

ADAPTER = TypeAdapter(EventIn)


def shot(**over):
    body = {"type": "shot", "team": "home", "period": 1, "time": "07:42", "x": 600, "y": 250,
            "result": "on_goal", "shooter_id": 2}
    body.update(over)
    return body


def sub(**over):
    body = {"type": "substitution", "team": "home", "period": 1, "time": "08:10",
            "players": [2, 3, 4, 5, 6]}
    body.update(over)
    return body


def run(body, ctx=CTX):
    return normalize(ctx, ADAPTER.validate_python(body))


def code_of(body, ctx=CTX):
    with pytest.raises(ApiError) as info:
        run(body, ctx)
    assert info.value.status == 422
    assert info.value.fields, "rule errors name the field"
    return info.value.code


@pytest.mark.parametrize("value,seconds", [("00:00", 0), ("19:59", 1199), ("07:42", 462)])
def test_parse_mmss_accepts(value, seconds):
    assert parse_mmss(value) == seconds
    assert format_mmss(seconds) == value


@pytest.mark.parametrize("value", ["7:42", "07:60", "07:42:00", " 07:42", "०७:४२", "", "ab:cd", "0742", "07.42"])
def test_parse_mmss_rejects(value):
    with pytest.raises(ApiError) as info:
        parse_mmss(value)
    assert info.value.code == "invalid_time"


def test_time_at_period_length_is_out_of_period():
    assert code_of(shot(time="20:00")) == "time_out_of_period"


def test_overtime_is_shorter():
    assert run(shot(period=4, time="04:59")).time_s == 299
    assert code_of(shot(period=4, time="05:00")) == "time_out_of_period"


@pytest.mark.parametrize("period", [0, 5, -1])
def test_period_outside_match(period):
    assert code_of(shot(period=period)) == "invalid_period"


def test_overtime_period_without_overtime():
    assert code_of(shot(period=4), CTX_NO_OT) == "invalid_period"


def test_valid_shot_is_normalized_with_defaults():
    event = run(shot())
    assert (event.type, event.side, event.period, event.time_s) == ("shot", "home", 1, 462)
    assert event.data == {"x": 600, "y": 250, "result": "on_goal", "strength": "even",
                          "shooter_id": 2, "goalkeeper_id": None, "assist_id": None, "on_ice": None}


@pytest.mark.parametrize(
    "over,code",
    [
        ({"shooter_id": 12}, "wrong_team"),
        ({"shooter_id": 999}, "unknown_player"),
        ({"goalkeeper_id": 12}, "not_goalkeeper"),
        ({"goalkeeper_id": 1}, "not_goalkeeper"),
        ({"goalkeeper_id": 999}, "unknown_player"),
        ({"result": "goal", "assist_id": 2}, "assist_is_shooter"),
        ({"result": "goal", "assist_id": 12}, "wrong_team"),
        ({"result": "miss", "assist_id": 3}, "goal_fields_on_non_goal"),
        ({"result": "post", "on_ice": {"home": [2], "away": []}}, "goal_fields_on_non_goal"),
        ({"result": "goal", "on_ice": {"home": [1, 2, 3, 4, 5, 6, 7], "away": []}}, "too_many_players"),
        ({"result": "goal", "on_ice": {"home": [2, 12], "away": []}}, "wrong_team"),
        ({"result": "goal", "on_ice": {"home": [2, 2], "away": []}}, "duplicate_player"),
        ({"x": 891}, "out_of_rink"),
        ({"y": 502}, "out_of_rink"),
        ({"x": -1}, "out_of_rink"),
    ],
)
def test_shot_rule_violations(over, code):
    assert code_of(shot(**over)) == code


def test_goal_with_everything():
    event = run(shot(result="goal", goalkeeper_id=11, assist_id=3,
                     on_ice={"home": [1, 2, 3, 4, 5, 6], "away": [11, 12, 13, 14, 15]}))
    assert event.data["assist_id"] == 3
    assert event.data["on_ice"] == {"home": [1, 2, 3, 4, 5, 6], "away": [11, 12, 13, 14, 15]}


def test_rink_corners_are_inside():
    assert run(shot(x=0, y=0)).data["x"] == 0
    assert run(shot(x=890, y=501)).data["y"] == 501


@pytest.mark.parametrize(
    "over,code",
    [
        ({"players": [2, 3]}, "too_few_players"),
        ({"players": [2, 3, 4, 5, 6, 7]}, "empty_net_required"),
        ({"players": [2, 3, 4, 5, 6, 7, 8], "empty_net": True}, "too_many_players"),
        ({"players": [2, 3, 4, 5, 5]}, "duplicate_player"),
        ({"players": [1, 2, 3, 4, 5]}, "goalkeeper_in_line"),
        ({"players": [2, 3, 4, 5, 12]}, "wrong_team"),
        ({"players": [2, 3, 4, 5, 999]}, "unknown_player"),
    ],
)
def test_substitution_rule_violations(over, code):
    assert code_of(sub(**over)) == code


@pytest.mark.parametrize("players,empty_net", [([2, 3, 4, 5, 6], False), ([2, 3, 4], False),
                                               ([2, 3, 4, 5, 6, 7], True), ([2, 3, 4, 5], True)])
def test_substitution_sizes_accepted(players, empty_net):
    event = run(sub(players=players, empty_net=empty_net))
    assert event.data == {"players": players, "strength": "even", "empty_net": empty_net}


@pytest.mark.parametrize(
    "team,x,expected",
    [("home", 300, ["shot_from_own_half"]), ("home", 445, []), ("home", 444, ["shot_from_own_half"]),
     ("away", 444, []), ("away", 445, ["shot_from_own_half"])],
)
def test_own_half_warning(team, x, expected):
    shooter = 2 if team == "home" else 12
    assert warnings_for(run(shot(team=team, x=x, shooter_id=shooter))) == expected


def test_substitution_has_no_warnings():
    assert warnings_for(run(sub())) == []


def test_in_out():
    assert in_out([1, 2, 3, 4, 5], [1, 2, 6, 7, 8]) == ([6, 7, 8], [3, 4, 5])
    assert in_out(None, [1, 2, 3]) == ([1, 2, 3], [])
    assert in_out([1, 2, 3], [1, 2, 3]) == ([], [])


@pytest.mark.parametrize(
    "body",
    [
        shot(colour="red"),
        sub(players="2,3,4"),
        shot(result="blocked"),
        shot(x="600"),
        shot(x=600.5),
        shot(time=742),
        {"type": "penalty", "team": "home"},
        {k: v for k, v in shot().items() if k != "shooter_id"},
        sub(empty_net="yes"),
    ],
)
def test_model_rejects_wrong_shapes(body):
    with pytest.raises(ValidationError):
        ADAPTER.validate_python(body)
