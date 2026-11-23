"""All SQL lives here. Every statement uses bound parameters."""
from __future__ import annotations

import sqlite3

from app.db import now_iso

# --- teams -----------------------------------------------------------------


def create_team(conn: sqlite3.Connection, name: str, token_hash: str) -> int:
    cur = conn.execute(
        "INSERT INTO team(name, token_hash, created_at) VALUES (?, ?, ?)",
        (name, token_hash, now_iso()),
    )
    return int(cur.lastrowid)


def team_by_token_hash(conn: sqlite3.Connection, token_hash: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM team WHERE token_hash = ?", (token_hash,)).fetchone()


def count_teams(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM team").fetchone()[0]


# --- matches ---------------------------------------------------------------


def matches_of_team(conn: sqlite3.Connection, team_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM match WHERE team_id = ? ORDER BY id", (team_id,)
    ).fetchall()


def match_for_team(conn: sqlite3.Connection, match_id: int, team_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM match WHERE id = ? AND team_id = ?", (match_id, team_id)
    ).fetchone()


def match_by_id(conn: sqlite3.Connection, match_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM match WHERE id = ?", (match_id,)).fetchone()


def players_of_match(conn: sqlite3.Connection, match_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM player WHERE match_id = ? ORDER BY side DESC, jersey", (match_id,)
    ).fetchall()


def formations_of_match(conn: sqlite3.Connection, match_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM formation WHERE match_id = ? ORDER BY side DESC, line", (match_id,)
    ).fetchall()


# --- events ----------------------------------------------------------------

import json  # noqa: E402
from dataclasses import dataclass  # noqa: E402

from app.errors import ApiError  # noqa: E402
from app.rules import NormalizedEvent, in_out, warnings_for  # noqa: E402
from app.timeutil import format_mmss  # noqa: E402


@dataclass(frozen=True)
class UpsertResult:
    row: sqlite3.Row
    created: bool
    unchanged: bool


def get_event(conn: sqlite3.Connection, match_id: int, client_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM event WHERE match_id = ? AND client_id = ?", (match_id, client_id)
    ).fetchone()


def list_events(
    conn: sqlite3.Connection, match_id: int, include_deleted: bool = False
) -> list[sqlite3.Row]:
    sql = "SELECT * FROM event WHERE match_id = ?"
    if not include_deleted:
        sql += " AND deleted_at IS NULL"
    return conn.execute(sql + " ORDER BY period, time_s, seq", (match_id,)).fetchall()


def _dump(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _same_content(row: sqlite3.Row, event: NormalizedEvent) -> bool:
    return (
        row["side"] == event.side
        and row["period"] == event.period
        and row["time_s"] == event.time_s
        and row["data"] == _dump(event.data)
    )


def upsert_event(
    conn: sqlite3.Connection,
    match_id: int,
    client_id: str,
    event: NormalizedEvent,
    expected_version: int | None,
    max_events: int,
) -> UpsertResult:
    """Create or update one event. Must run inside a write transaction.

    The order of the checks is the public contract; see docs/design.md.
    """
    stored = get_event(conn, match_id, client_id)
    if stored is not None:
        if stored["deleted_at"] is not None:
            raise ApiError(
                410,
                "deleted",
                "Tato událost byla smazána. Pro novou událost použijte nové client_id.",
            )
        if stored["type"] != event.type:
            raise ApiError(
                422,
                "type_change",
                "Typ existující události nejde změnit. Smažte ji a založte novou.",
                fields={"type": "type_change"},
            )
        if _same_content(stored, event):
            return UpsertResult(stored, created=False, unchanged=True)
        if expected_version is not None and expected_version != stored["version"]:
            raise ApiError(
                409,
                "version_conflict",
                f"Událost mezitím změnil někdo jiný (uložená verze {stored['version']}, "
                f"poslaná {expected_version}).",
                extra={"event": event_out(conn, stored)},
            )
    if event.type == "substitution":
        clash = conn.execute(
            """SELECT 1 FROM event
               WHERE match_id = ? AND type = 'substitution' AND side = ? AND period = ?
                 AND time_s = ? AND deleted_at IS NULL AND client_id <> ?""",
            (match_id, event.side, event.period, event.time_s, client_id),
        ).fetchone()
        if clash is not None:
            raise ApiError(
                409,
                "duplicate_time",
                f"Tým už má v této části střídání v čase {format_mmss(event.time_s)}. "
                "Dvě střídání téhož týmu ve stejném čase nejdou zapsat.",
                fields={"time": "duplicate_time"},
            )
    now = now_iso()
    if stored is None:
        count = conn.execute(
            "SELECT COUNT(*) FROM event WHERE match_id = ?", (match_id,)
        ).fetchone()[0]
        if count >= max_events:
            raise ApiError(
                422,
                "event_limit",
                f"Utkání už má {max_events} uložených událostí, víc jich nepřijme.",
            )
        seq = conn.execute("SELECT next_seq FROM match WHERE id = ?", (match_id,)).fetchone()[0]
        conn.execute(
            """INSERT INTO event(match_id, client_id, type, side, period, time_s, data, version,
                                 seq, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)""",
            (match_id, client_id, event.type, event.side, event.period, event.time_s,
             _dump(event.data), seq, now, now),
        )
        conn.execute(
            "UPDATE match SET next_seq = next_seq + 1, version = version + 1 WHERE id = ?",
            (match_id,),
        )
        return UpsertResult(get_event(conn, match_id, client_id), created=True, unchanged=False)
    conn.execute(
        """UPDATE event SET side = ?, period = ?, time_s = ?, data = ?, version = version + 1,
                            updated_at = ?
           WHERE id = ?""",
        (event.side, event.period, event.time_s, _dump(event.data), now, stored["id"]),
    )
    conn.execute("UPDATE match SET version = version + 1 WHERE id = ?", (match_id,))
    return UpsertResult(get_event(conn, match_id, client_id), created=False, unchanged=False)


def delete_event(conn: sqlite3.Connection, match_id: int, client_id: str) -> bool:
    """Soft delete. Returns False when the event never existed. Repeating is a no-op."""
    stored = get_event(conn, match_id, client_id)
    if stored is None:
        return False
    if stored["deleted_at"] is None:
        now = now_iso()
        conn.execute(
            "UPDATE event SET deleted_at = ?, updated_at = ?, version = version + 1 WHERE id = ?",
            (now, now, stored["id"]),
        )
        conn.execute("UPDATE match SET version = version + 1 WHERE id = ?", (match_id,))
    return True


def reset_match(conn: sqlite3.Connection, match_id: int) -> int:
    """Remove every event of the match for real; client ids become free again."""
    cur = conn.execute("DELETE FROM event WHERE match_id = ?", (match_id,))
    conn.execute(
        "UPDATE match SET next_seq = 1, version = version + 1 WHERE id = ?", (match_id,)
    )
    return cur.rowcount


def _row_out(row: sqlite3.Row) -> dict:
    data = json.loads(row["data"])
    out = {
        "client_id": row["client_id"],
        "type": row["type"],
        "team": row["side"],
        "period": row["period"],
        "time": format_mmss(row["time_s"]),
        **data,
        "version": row["version"],
        "seq": row["seq"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "warnings": warnings_for(
            NormalizedEvent(row["type"], row["side"], row["period"], row["time_s"], data)
        ),
    }
    if row["deleted_at"] is not None:
        out["deleted_at"] = row["deleted_at"]
    return out


def events_out(rows: list[sqlite3.Row]) -> list[dict]:
    """Rows (already ordered by period, time, seq) as API objects, with in/out for substitutions.

    in/out compare each substitution with the previous non-deleted one of the same team.
    """
    lineup: dict[str, list[int] | None] = {"home": None, "away": None}
    result = []
    for row in rows:
        out = _row_out(row)
        if row["type"] == "substitution":
            if row["deleted_at"] is None:
                came, left = in_out(lineup[row["side"]], out["players"])
                lineup[row["side"]] = out["players"]
            else:
                came, left = [], []
            out["in"], out["out"] = came, left
        result.append(out)
    return result


def event_out(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    """One event as an API object. in/out need only the previous substitution of the same team."""
    out = _row_out(row)
    if row["type"] != "substitution":
        return out
    if row["deleted_at"] is not None:
        out["in"], out["out"] = [], []
        return out
    previous = conn.execute(
        """SELECT data FROM event
           WHERE match_id = ? AND type = 'substitution' AND side = ? AND deleted_at IS NULL
             AND (period, time_s, seq) < (?, ?, ?)
           ORDER BY period DESC, time_s DESC, seq DESC LIMIT 1""",
        (row["match_id"], row["side"], row["period"], row["time_s"], row["seq"]),
    ).fetchone()
    lineup = json.loads(previous["data"])["players"] if previous is not None else None
    out["in"], out["out"] = in_out(lineup, out["players"])
    return out


# --- error mode and overview --------------------------------------------------


def set_error_mode(conn: sqlite3.Connection, team_id: int, mode: str) -> bool:
    cur = conn.execute(
        "UPDATE team SET error_mode = ? WHERE id = ?", (mode, team_id)
    )
    return cur.rowcount == 1


def teams_overview(conn: sqlite3.Connection) -> list[dict]:
    teams = conn.execute("SELECT * FROM team ORDER BY id").fetchall()
    result = []
    for team in teams:
        matches = conn.execute(
            """SELECT m.*,
                      (SELECT COUNT(*) FROM event e WHERE e.match_id = m.id AND e.deleted_at IS NULL) AS events,
                      (SELECT COUNT(*) FROM event e WHERE e.match_id = m.id AND e.deleted_at IS NOT NULL) AS deleted
               FROM match m WHERE m.team_id = ? ORDER BY m.id""",
            (team["id"],),
        ).fetchall()
        result.append(
            {
                "id": team["id"],
                "name": team["name"],
                "error_mode": team["error_mode"],
                "matches": [
                    {
                        "id": m["id"],
                        "home": m["home_name"],
                        "away": m["away_name"],
                        "events": m["events"],
                        "deleted": m["deleted"],
                        "version": m["version"],
                    }
                    for m in matches
                ],
            }
        )
    return result
