"""SQLite access: one file, WAL mode, one short-lived connection per request."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = Path(__file__).with_name("schema.sql")


def connect(path: str) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    """Create the tables. Raises ValueError for a database written by an older version."""
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(team)")}
    if columns and "role" in columns:
        raise ValueError(
            "Databáze je ze starší verze služby a nejde převést. Smažte ji a spusťte službu znovu "
            "(v Dockeru: docker compose down -v && docker compose up)."
        )
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))


@contextmanager
def transaction(conn: sqlite3.Connection):
    """A write transaction that takes the write lock up front (no deadlock on upgrade)."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
