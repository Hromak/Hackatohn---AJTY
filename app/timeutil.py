"""Match time as the scoreboard shows it: "mm:ss" elapsed in the current period."""
from __future__ import annotations

import re

from app.errors import ApiError

_MMSS = re.compile(r"^[0-9]{2}:[0-5][0-9]$", re.ASCII)


def parse_mmss(value: str) -> int:
    if not isinstance(value, str) or _MMSS.fullmatch(value) is None:
        raise ApiError(
            422,
            "invalid_time",
            'Čas musí být ve tvaru "mm:ss", například "07:42".',
            fields={"time": "invalid_time"},
        )
    return int(value[:2]) * 60 + int(value[3:])


def format_mmss(seconds: int) -> str:
    return f"{seconds // 60:02d}:{seconds % 60:02d}"
