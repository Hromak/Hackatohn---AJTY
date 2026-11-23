"""Bearer tokens. Only the SHA-256 of a token is stored."""
from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass

from fastapi import Depends, Request

from app import repo
from app.errors import ApiError

_BEARER = re.compile(r"^[Bb][Ee][Aa][Rr][Ee][Rr] ([\x21-\x7e]{1,256})$")  # the scheme is case-insensitive


@dataclass(frozen=True)
class Team:
    id: int
    name: str
    error_mode: str


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _unauthorized() -> ApiError:
    return ApiError(
        401,
        "unauthorized",
        "Chybí nebo neplatí token. Pošlete hlavičku Authorization: Bearer <token>.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _conn(request: Request):
    from app.main import get_conn

    yield from get_conn(request)


def authenticate(request: Request, conn=Depends(_conn)) -> Team:
    """Resolve the token to a team. No error-mode handling here (the switch needs it raw)."""
    header = request.headers.get("authorization", "")
    match = _BEARER.match(header)
    if match is None:
        raise _unauthorized()
    row = repo.team_by_token_hash(conn, hash_token(match.group(1)))
    if row is None:
        raise _unauthorized()
    team = Team(id=row["id"], name=row["name"], error_mode=row["error_mode"])
    request.state.team_id = team.id
    return team


_WRITE_METHODS = {"PUT", "POST", "DELETE", "PATCH"}


def current_team(request: Request, team: Team = Depends(authenticate)) -> Team:
    """The authenticated team, with its forced error mode applied.

    The switch itself (`/me/error-mode`) depends on `authenticate` directly, so it keeps
    working while a mode is on.
    """
    path = request.url.path
    if team.error_mode == "unavailable":
        raise ApiError(
            503,
            "forced_unavailable",
            "Služba je pro tento tým dočasně nedostupná (režim vynucené chyby).",
            headers={"Retry-After": "5"},
        )
    if (
        team.error_mode == "reject"
        and request.method in _WRITE_METHODS
        and path.startswith("/api/v1/matches/")
    ):
        raise ApiError(
            422,
            "forced_rejection",
            "Zápis byl odmítnut (režim vynucené chyby). Čtení funguje dál.",
        )
    return team
