CREATE TABLE IF NOT EXISTS team (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    token_hash  TEXT NOT NULL UNIQUE,
    error_mode  TEXT NOT NULL DEFAULT 'off' CHECK (error_mode IN ('off', 'reject', 'unavailable')),
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS match (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id            INTEGER NOT NULL REFERENCES team(id),
    home_name          TEXT NOT NULL,
    home_short         TEXT NOT NULL,
    away_name          TEXT NOT NULL,
    away_short         TEXT NOT NULL,
    date               TEXT NOT NULL,
    venue              TEXT,
    competition        TEXT,
    period_count       INTEGER NOT NULL,
    period_length_min  INTEGER NOT NULL,
    overtime_min       INTEGER,
    version            INTEGER NOT NULL DEFAULT 0,
    next_seq           INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS match_team ON match(team_id);

CREATE TABLE IF NOT EXISTS player (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id    INTEGER NOT NULL REFERENCES match(id),
    side        TEXT NOT NULL CHECK (side IN ('home', 'away')),
    jersey      INTEGER NOT NULL,
    first_name  TEXT NOT NULL,
    last_name   TEXT NOT NULL,
    position    TEXT NOT NULL CHECK (position IN ('G', 'D', 'F')),
    captain     INTEGER NOT NULL DEFAULT 0,
    UNIQUE (match_id, side, jersey)
);

CREATE TABLE IF NOT EXISTS formation (
    match_id  INTEGER NOT NULL REFERENCES match(id),
    side      TEXT NOT NULL CHECK (side IN ('home', 'away')),
    line      INTEGER NOT NULL,
    lw        INTEGER REFERENCES player(id),
    c         INTEGER REFERENCES player(id),
    rw        INTEGER REFERENCES player(id),
    ld        INTEGER REFERENCES player(id),
    rd        INTEGER REFERENCES player(id),
    PRIMARY KEY (match_id, side, line)
);

CREATE TABLE IF NOT EXISTS event (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id    INTEGER NOT NULL REFERENCES match(id),
    client_id   TEXT NOT NULL,
    type        TEXT NOT NULL CHECK (type IN ('shot', 'substitution')),
    side        TEXT NOT NULL CHECK (side IN ('home', 'away')),
    period      INTEGER NOT NULL,
    time_s      INTEGER NOT NULL,
    data        TEXT NOT NULL,
    version     INTEGER NOT NULL,
    seq         INTEGER NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    deleted_at  TEXT,
    UNIQUE (match_id, client_id)
);

CREATE INDEX IF NOT EXISTS event_order ON event(match_id, period, time_s, seq);
