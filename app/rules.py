"""Rules for shots and substitutions. Pure functions: no database, no HTTP."""
from __future__ import annotations

from dataclasses import dataclass

from app.errors import ApiError
from app.models import RINK_CENTER_X, RINK_HEIGHT, RINK_WIDTH, ShotIn, SubstitutionIn
from app.timeutil import format_mmss, parse_mmss

MAX_ON_FIELD = 6
MIN_LINE = 3
MAX_LINE_WITH_GOALKEEPER = 5


@dataclass(frozen=True)
class Player:
    id: int
    side: str
    jersey: int
    position: str


@dataclass(frozen=True)
class MatchContext:
    period_count: int
    period_length_s: int
    overtime_s: int | None
    players: dict[int, Player]


@dataclass(frozen=True)
class NormalizedEvent:
    type: str
    side: str
    period: int
    time_s: int
    data: dict


def context_from(match_row, player_rows) -> MatchContext:
    return MatchContext(
        period_count=match_row["period_count"],
        period_length_s=match_row["period_length_min"] * 60,
        overtime_s=match_row["overtime_min"] * 60 if match_row["overtime_min"] else None,
        players={
            p["id"]: Player(p["id"], p["side"], p["jersey"], p["position"]) for p in player_rows
        },
    )


def _fail(code: str, message: str, field: str) -> ApiError:
    return ApiError(422, code, message, fields={field: code})


def _other(side: str) -> str:
    return "away" if side == "home" else "home"


def _side_name(side: str) -> str:
    return "domácích" if side == "home" else "hostů"


def _period_length(ctx: MatchContext, period: int) -> int:
    if 1 <= period <= ctx.period_count:
        return ctx.period_length_s
    if period == ctx.period_count + 1 and ctx.overtime_s:
        return ctx.overtime_s
    raise _fail("invalid_period", f"Hrací část {period} v tomto utkání není.", "period")


def _time(ctx: MatchContext, period: int, value: str) -> int:
    length = _period_length(ctx, period)
    seconds = parse_mmss(value)
    if seconds >= length:
        raise _fail(
            "time_out_of_period",
            f"Čas {value} je mimo hrací část; ta trvá {format_mmss(length)}.",
            "time",
        )
    return seconds


def _player(ctx: MatchContext, player_id: int, side: str, field: str) -> Player:
    player = ctx.players.get(player_id)
    if player is None:
        raise _fail("unknown_player", f"Hráč {player_id} není na soupisce tohoto utkání.", field)
    if player.side != side:
        raise _fail(
            "wrong_team",
            f"Hráč {player_id} (číslo {player.jersey}) nepatří na soupisku {_side_name(side)}.",
            field,
        )
    return player


def _unique(ids: list[int], field: str) -> None:
    if len(set(ids)) != len(ids):
        raise _fail("duplicate_player", "Stejný hráč je v seznamu vícekrát.", field)


def _shot(ctx: MatchContext, p: ShotIn) -> NormalizedEvent:
    time_s = _time(ctx, p.period, p.time)
    if not 0 <= p.x <= RINK_WIDTH:
        raise _fail("out_of_rink", f"Souřadnice x musí být 0 až {RINK_WIDTH}.", "x")
    if not 0 <= p.y <= RINK_HEIGHT:
        raise _fail("out_of_rink", f"Souřadnice y musí být 0 až {RINK_HEIGHT}.", "y")
    _player(ctx, p.shooter_id, p.team, "shooter_id")
    if p.goalkeeper_id is not None:
        keeper = ctx.players.get(p.goalkeeper_id)
        if keeper is None:
            raise _fail(
                "unknown_player",
                f"Hráč {p.goalkeeper_id} není na soupisce tohoto utkání.",
                "goalkeeper_id",
            )
        if keeper.side != _other(p.team) or keeper.position != "G":
            raise _fail(
                "not_goalkeeper",
                f"Hráč {p.goalkeeper_id} není brankář soupeře.",
                "goalkeeper_id",
            )
    on_ice = None
    if p.result != "goal":
        if p.assist_id is not None:
            raise _fail("goal_fields_on_non_goal", "Asistence patří jen ke gólu.", "assist_id")
        if p.on_ice is not None:
            raise _fail("goal_fields_on_non_goal", "Hráči na hřišti patří jen ke gólu.", "on_ice")
    else:
        if p.assist_id is not None:
            if p.assist_id == p.shooter_id:
                raise _fail("assist_is_shooter", "Asistent nemůže být střelec.", "assist_id")
            _player(ctx, p.assist_id, p.team, "assist_id")
        if p.on_ice is not None:
            on_ice = {}
            for side in ("home", "away"):
                ids = list(getattr(p.on_ice, side))
                field = f"on_ice.{side}"
                if len(ids) > MAX_ON_FIELD:
                    raise _fail(
                        "too_many_players",
                        f"Na hřišti může být nejvýš {MAX_ON_FIELD} hráčů jedné strany.",
                        field,
                    )
                _unique(ids, field)
                for player_id in ids:
                    _player(ctx, player_id, side, field)
                on_ice[side] = ids
    return NormalizedEvent(
        type="shot",
        side=p.team,
        period=p.period,
        time_s=time_s,
        data={
            "x": p.x,
            "y": p.y,
            "result": p.result,
            "strength": p.strength,
            "shooter_id": p.shooter_id,
            "goalkeeper_id": p.goalkeeper_id,
            "assist_id": p.assist_id,
            "on_ice": on_ice,
        },
    )


def _substitution(ctx: MatchContext, p: SubstitutionIn) -> NormalizedEvent:
    time_s = _time(ctx, p.period, p.time)
    players = list(p.players)
    if len(players) < MIN_LINE:
        raise _fail("too_few_players", f"Ve střídání musí být aspoň {MIN_LINE} hráči.", "players")
    if len(players) > MAX_ON_FIELD:
        raise _fail(
            "too_many_players", f"Ve střídání může být nejvýš {MAX_ON_FIELD} hráčů.", "players"
        )
    if len(players) > MAX_LINE_WITH_GOALKEEPER and not p.empty_net:
        raise _fail(
            "empty_net_required",
            "Šest hráčů v poli jde zapsat jen při hře bez brankáře (empty_net: true).",
            "players",
        )
    _unique(players, "players")
    for player_id in players:
        player = _player(ctx, player_id, p.team, "players")
        if player.position == "G":
            raise _fail(
                "goalkeeper_in_line",
                f"Hráč {player_id} (číslo {player.jersey}) je brankář; do střídání patří jen hráči v poli.",
                "players",
            )
    return NormalizedEvent(
        type="substitution",
        side=p.team,
        period=p.period,
        time_s=time_s,
        data={"players": players, "strength": p.strength, "empty_net": p.empty_net},
    )


def normalize(ctx: MatchContext, payload: ShotIn | SubstitutionIn) -> NormalizedEvent:
    """Check an event against the match and return it in canonical form. Raises ApiError(422)."""
    if isinstance(payload, ShotIn):
        return _shot(ctx, payload)
    return _substitution(ctx, payload)


def warnings_for(event: NormalizedEvent) -> list[str]:
    """Soft findings that do not reject the event."""
    if event.type != "shot":
        return []
    x = event.data["x"]
    own_half = x < RINK_CENTER_X if event.side == "home" else x >= RINK_CENTER_X
    return ["shot_from_own_half"] if own_half else []


def in_out(previous: list[int] | None, current: list[int]) -> tuple[list[int], list[int]]:
    """Who came on and who went off against the previous line-up of the same team."""
    if previous is None:
        return list(current), []
    return (
        [p for p in current if p not in previous],
        [p for p in previous if p not in current],
    )
