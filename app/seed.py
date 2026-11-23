"""Turning a match description file into teams and matches in the database."""
from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path

from app import repo
from app.auth import hash_token, new_token
from app.config import Settings

SLOTS = ("lw", "c", "rw", "ld", "rd")
POSITIONS = {"G", "D", "F"}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(f"match file: {message}")


def load_match_file(path: str) -> dict:
    """Read and check a match description. Raises ValueError saying what is wrong."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"match file: cannot read {path} ({exc.strerror or exc})") from None
    try:
        match = json.loads(text)
    except ValueError as exc:
        raise ValueError(f"match file: {path} is not valid JSON ({exc})") from None
    _require(isinstance(match, dict), "the top level must be an object")
    for key in ("competition", "date", "home", "away", "periods", "roster", "formations"):
        _require(key in match, f"missing key '{key}'")
    for key in ("competition", "date"):
        _require(isinstance(match[key], str) and match[key], f"'{key}' must be text")
    _require(match.get("venue") is None or isinstance(match["venue"], str), "'venue' must be text")
    _require(isinstance(match["roster"], dict), "'roster' must be an object with home and away")
    _require(isinstance(match["formations"], dict), "'formations' must be an object with home and away")
    for side in ("home", "away"):
        _require(isinstance(match[side], dict), f"'{side}' must be an object with name and short_name")
        for key in ("name", "short_name"):
            _require(isinstance(match[side].get(key), str) and match[side][key], f"missing {side}.{key}")
        players = match["roster"].get(side)
        _require(isinstance(players, list) and players, f"empty roster.{side}")
        jerseys = set()
        for index, player in enumerate(players):
            where = f"roster.{side}[{index}]"
            _require(isinstance(player, dict), f"{where} must be an object")
            for key in ("jersey", "first_name", "last_name", "position"):
                _require(key in player, f"{where} missing '{key}'")
            _require(
                type(player["jersey"]) is int and 0 <= player["jersey"] <= 999,
                f"{where} jersey must be a whole number",
            )
            for key in ("first_name", "last_name"):
                _require(isinstance(player[key], str), f"{where} {key} must be text")
            _require(player["position"] in POSITIONS, f"{where} position must be G, D or F")
            _require(player["jersey"] not in jerseys, f"{where} jersey {player['jersey']} repeats")
            jerseys.add(player["jersey"])
        _require(
            any(p["position"] == "G" for p in players), f"roster.{side} has no goalkeeper (position G)"
        )
        lines = match["formations"].get(side)
        _require(isinstance(lines, list), f"missing formations.{side} (use [] for none)")
        seen_lines = set()
        for index, line in enumerate(lines):
            where = f"formations.{side}[{index}]"
            _require(isinstance(line, dict), f"{where} must be an object")
            _require(type(line.get("line")) is int and line["line"] >= 1, f"{where} needs a 'line' number")
            _require(line["line"] not in seen_lines, f"{where} line {line['line']} repeats")
            seen_lines.add(line["line"])
            for slot in SLOTS:
                jersey = line.get(slot)
                _require(
                    jersey is None or jersey in jerseys,
                    f"{where}.{slot} jersey {jersey} not on roster",
                )
    periods = match["periods"]
    _require(isinstance(periods, dict), "'periods' must be an object")
    for key in ("count", "length_min"):
        _require(
            type(periods.get(key)) is int and 1 <= periods[key] <= 99,
            f"periods.{key} must be a whole number from 1 to 99",
        )
    overtime = periods.get("overtime_min")
    _require(
        overtime is None or (type(overtime) is int and 1 <= overtime <= 99),
        "periods.overtime_min must be null or a whole number from 1 to 99",
    )
    return match


def create_match(conn: sqlite3.Connection, team_id: int, match: dict) -> int:
    periods = match["periods"]
    cur = conn.execute(
        """INSERT INTO match(team_id, home_name, home_short, away_name, away_short, date,
                             venue, competition, period_count, period_length_min, overtime_min)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            team_id,
            match["home"]["name"],
            match["home"]["short_name"],
            match["away"]["name"],
            match["away"]["short_name"],
            match["date"],
            match.get("venue"),
            match["competition"],
            periods["count"],
            periods["length_min"],
            periods.get("overtime_min"),
        ),
    )
    match_id = int(cur.lastrowid)
    for side in ("home", "away"):
        ids: dict[int, int] = {}
        for player in sorted(match["roster"][side], key=lambda p: p["jersey"]):
            cur = conn.execute(
                """INSERT INTO player(match_id, side, jersey, first_name, last_name, position, captain)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    match_id,
                    side,
                    player["jersey"],
                    player["first_name"],
                    player["last_name"],
                    player["position"],
                    1 if player.get("captain") else 0,
                ),
            )
            ids[player["jersey"]] = int(cur.lastrowid)
        for line in match["formations"].get(side, []):
            conn.execute(
                "INSERT INTO formation(match_id, side, line, lw, c, rw, ld, rd) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (match_id, side, line["line"], *[ids.get(line.get(slot)) for slot in SLOTS]),
            )
    return match_id


def add_team(
    conn: sqlite3.Connection, name: str, match: dict, token: str | None = None
) -> tuple[int, str]:
    """Create a team with one match. Returns (team id, plain token)."""
    token = token or new_token()
    team_id = repo.create_team(conn, name, hash_token(token))
    create_match(conn, team_id, match)
    return team_id, token


def ensure_bootstrap(conn: sqlite3.Connection, settings: Settings) -> None:
    """Idempotent start-up data: the demo team with the matches shipped in the repository.

    Raises ValueError when the settings would leave the service in an unsafe state.
    """
    demo_team = repo.team_by_token_hash(conn, hash_token(settings.demo_token))
    if not settings.demo and demo_team is not None:
        raise ValueError(
            "Databáze obsahuje ukázkový tým s veřejně známým tokenem, ale ZAPI_DEMO je vypnuté. "
            "Použijte čistou databázi, nebo zapněte ZAPI_DEMO=1."
        )
    if settings.demo and repo.count_teams(conn) == 0:
        extra = [load_match_file(str(path)) for path in _match_files(settings.demo_matches_dir)]
        team_id, _ = add_team(
            conn, "Demo", load_match_file(settings.demo_match_path), token=settings.demo_token
        )
        for match in extra:
            create_match(conn, team_id, match)


def _match_files(directory: str) -> list[Path]:
    """Match description files of a directory, in name order. A missing directory means none."""
    folder = Path(directory)
    return sorted(folder.glob("*.json")) if folder.is_dir() else []


def events_to_api(match: dict, home_ids: dict[int, int], away_ids: dict[int, int]) -> list[dict]:
    """The match file's jersey-based events as API requests: [{"client_id", "body"}].

    `home_ids` / `away_ids` map jersey number -> player id of the target match. The client ids
    are stable (derived from the position in the file), so the list can be replayed.
    """
    ids = {"home": home_ids, "away": away_ids}
    other = {"home": "away", "away": "home"}
    result = []
    for index, event in enumerate(match.get("events", [])):
        team = event["team"]
        body = {"type": event["type"], "team": team, "period": event["period"], "time": event["time"]}
        if event["type"] == "substitution":
            body["players"] = [ids[team][j] for j in event["players"]]
            body["strength"] = event.get("strength", "even")
            body["empty_net"] = bool(event.get("empty_net", False))
        else:
            body.update(
                x=event["x"],
                y=event["y"],
                result=event["result"],
                strength=event.get("strength", "even"),
                shooter_id=ids[team][event["shooter"]],
                goalkeeper_id=(
                    ids[other[team]][event["goalkeeper"]]
                    if event.get("goalkeeper") is not None
                    else None
                ),
                assist_id=ids[team][event["assist"]] if event.get("assist") is not None else None,
            )
        client_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"zapisovatel-api/demo-match/{index}"))
        result.append({"client_id": client_id, "body": body})
    return result
