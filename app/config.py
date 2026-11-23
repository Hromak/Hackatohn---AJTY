"""Service settings. Everything comes from environment variables; nothing secret lives in the repo."""
from __future__ import annotations

import os
from dataclasses import dataclass


def _bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    db_path: str = "data/zapisovatel.sqlite"
    demo: bool = False
    demo_token: str = "demo"
    demo_match_path: str = "data/demo-match.json"
    demo_matches_dir: str = "data/matches"
    rate_per_sec: float = 20
    rate_burst: int = 40
    global_rate_per_sec: float = 300
    global_rate_burst: int = 600
    max_events: int = 500
    max_in_flight: int = 4
    max_body: int = 16384

    @classmethod
    def from_env(cls) -> "Settings":
        env = os.environ
        default = cls()

        def number(name: str, fallback, kind):
            raw = env.get(name)
            if raw is None or raw == "":
                return fallback
            try:
                value = kind(raw)
            except ValueError:
                raise SystemExit(f"{name} musí být číslo, ne {raw!r}.") from None
            if value <= 0:
                raise SystemExit(f"{name} musí být kladné číslo, ne {raw!r}.")
            return value

        return cls(
            db_path=env.get("ZAPI_DB_PATH", default.db_path),
            demo=_bool(env.get("ZAPI_DEMO", "0")),
            demo_token=env.get("ZAPI_DEMO_TOKEN", default.demo_token),
            demo_match_path=env.get("ZAPI_DEMO_MATCH", default.demo_match_path),
            demo_matches_dir=env.get("ZAPI_DEMO_MATCHES_DIR", default.demo_matches_dir),
            rate_per_sec=number("ZAPI_RATE_PER_SEC", default.rate_per_sec, float),
            rate_burst=number("ZAPI_RATE_BURST", default.rate_burst, int),
            global_rate_per_sec=number("ZAPI_GLOBAL_RATE_PER_SEC", default.global_rate_per_sec, float),
            global_rate_burst=number("ZAPI_GLOBAL_RATE_BURST", default.global_rate_burst, int),
            max_events=number("ZAPI_MAX_EVENTS", default.max_events, int),
            max_body=number("ZAPI_MAX_BODY", default.max_body, int),
            max_in_flight=number("ZAPI_MAX_IN_FLIGHT", default.max_in_flight, int),
        )
