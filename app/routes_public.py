"""Endpoints for teams."""
from __future__ import annotations

import json
import re
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request, Response
from pydantic import TypeAdapter, ValidationError

from app import repo
from app.auth import Team, _conn, authenticate, current_team
from app.db import transaction
from app.errors import ApiError, validation_fields
from app.models import (
    RINK_CENTER_X,
    RINK_HEIGHT,
    RINK_WIDTH,
    CodebooksOut,
    ConflictOut,
    ErrorModeIn,
    ErrorModeOut,
    ErrorOut,
    EventIn,
    EventOneOut,
    EventsOut,
    FormationsOut,
    PutEventOut,
    ResetOut,
    MatchesOut,
    MatchOut,
    MeOut,
    RosterOut,
)
from app.rules import context_from, normalize
from app.timeutil import format_mmss

COMMON_ERRORS = {
    401: {"model": ErrorOut, "description": "Chybí nebo neplatí token."},
    429: {
        "model": ErrorOut,
        "description": "Překročen limit požadavků (rate_limited, too_many_concurrent_requests). "
        "Hlavička Retry-After říká, za kolik sekund to zkusit znovu.",
    },
    503: {"model": ErrorOut, "description": "Služba je pro tým dočasně nedostupná."},
}
MATCH_ERRORS = {**COMMON_ERRORS, 404: {"model": ErrorOut, "description": "Neznámé utkání."}}

router = APIRouter(prefix="/api/v1", responses=COMMON_ERRORS)

SLOT_LABELS = [
    ("lw", "levé křídlo"),
    ("c", "center"),
    ("rw", "pravé křídlo"),
    ("ld", "levý obránce"),
    ("rd", "pravý obránce"),
]


def match_item(row) -> dict:
    return {
        "id": row["id"],
        "home": row["home_name"],
        "away": row["away_name"],
        "date": row["date"],
    }


def periods_of(match) -> list[dict]:
    length = format_mmss(match["period_length_min"] * 60)
    periods = [
        {"period": n, "label": f"{n}. třetina" if match["period_count"] == 3 else f"{n}. část",
         "length": length, "overtime": False}
        for n in range(1, match["period_count"] + 1)
    ]
    if match["overtime_min"]:
        periods.append(
            {
                "period": match["period_count"] + 1,
                "label": "Prodloužení",
                "length": format_mmss(match["overtime_min"] * 60),
                "overtime": True,
            }
        )
    return periods


MAX_ID = 2**31 - 1
MatchId = Annotated[int, Path(ge=1, le=MAX_ID, description="Id utkání z `/me`.")]


def own_match(
    request: Request,
    match_id: MatchId,
    team: Team = Depends(current_team),
    conn=Depends(_conn),
):
    """The team's own match. Someone else's match looks exactly like one that does not exist."""
    row = repo.match_for_team(conn, match_id, team.id)
    if row is None:
        raise ApiError(404, "not_found", "Takové utkání neexistuje.")
    return row


@router.get("/me", tags=["tým"], summary="Kdo jsem a jaká mám utkání", response_model=MeOut,
            operation_id="getMe")
def me(team: Team = Depends(current_team), conn=Depends(_conn)) -> dict:
    return {
        "team": {"id": team.id, "name": team.name},
        "matches": [match_item(row) for row in repo.matches_of_team(conn, team.id)],
    }


@router.put(
    "/me/error-mode",
    tags=["tým"],
    summary="Vyzkoušet si chování aplikace při chybě API",
    operation_id="setMyErrorMode",
    response_model=ErrorModeOut,
)
def set_my_error_mode(
    body: ErrorModeIn, team: Team = Depends(authenticate), conn=Depends(_conn)
) -> dict:
    """Zapne režim, ve kterém služba zápisy odmítá nebo neodpovídá. Aplikace si na něm ověří,
    že zapisovateli chybu ukáže a o nic nepřijde. Přepínač funguje i při zapnutém režimu."""
    repo.set_error_mode(conn, team.id, body.mode)
    return {"mode": body.mode}


@router.get("/codebooks", tags=["číselníky"], summary="Číselníky a hřiště",
            response_model=CodebooksOut, operation_id="getCodebooks")
def codebooks(team: Team = Depends(current_team)) -> dict:
    return {
        "shot_results": [
            {"code": "miss", "label": "mimo branku"},
            {"code": "on_goal", "label": "na branku (chycená)"},
            {"code": "post", "label": "tyčka"},
            {"code": "goal", "label": "gól"},
        ],
        "strengths": [
            {"code": "even", "label": "vyrovnaný stav"},
            {"code": "power_play", "label": "přesilovka"},
            {"code": "short_handed", "label": "oslabení"},
        ],
        "positions": [
            {"code": "G", "label": "brankář"},
            {"code": "D", "label": "obránce"},
            {"code": "F", "label": "útočník"},
        ],
        "formation_slots": [{"code": code, "label": label} for code, label in SLOT_LABELS],
        "rink": {
            "width": RINK_WIDTH,
            "height": RINK_HEIGHT,
            "center_x": RINK_CENTER_X,
            "origin": "top_left",
            "home_attacks": "right",
            "note": "Souřadnice jsou v pixelech obrázku hřiště 890 × 501, počátek vlevo nahoře. "
            "Domácí útočí po celé utkání doprava (x ≥ 445), hosté doleva – bez ohledu na třetinu "
            "a na to, kde týmy v hale stojí. Výměnu stran řeší aplikace zobrazením.",
        },
    }


@router.get("/matches", tags=["utkání"], summary="Moje utkání", response_model=MatchesOut,
            operation_id="listMatches")
def matches(team: Team = Depends(current_team), conn=Depends(_conn)) -> dict:
    return {"matches": [match_item(row) for row in repo.matches_of_team(conn, team.id)]}


@router.get(
    "/matches/{match_id}",
    tags=["utkání"],
    summary="Hlavička utkání a hrací části",
    operation_id="getMatch",
    response_model=MatchOut,
    responses=MATCH_ERRORS,
)
def match_detail(match=Depends(own_match)) -> dict:
    return {
        "id": match["id"],
        "competition": match["competition"],
        "date": match["date"],
        "venue": match["venue"],
        "home": {"name": match["home_name"], "short_name": match["home_short"]},
        "away": {"name": match["away_name"], "short_name": match["away_short"]},
        "periods": periods_of(match),
        "version": match["version"],
    }


@router.get(
    "/matches/{match_id}/roster",
    tags=["utkání"],
    summary="Soupisky obou týmů",
    operation_id="getRoster",
    response_model=RosterOut,
    responses=MATCH_ERRORS,
)
def roster(match=Depends(own_match), conn=Depends(_conn)) -> dict:
    result: dict[str, list] = {"home": [], "away": []}
    for p in repo.players_of_match(conn, match["id"]):
        result[p["side"]].append(
            {
                "id": p["id"],
                "jersey": p["jersey"],
                "first_name": p["first_name"],
                "last_name": p["last_name"],
                "position": p["position"],
                "captain": bool(p["captain"]),
            }
        )
    return result


@router.get(
    "/matches/{match_id}/formations",
    tags=["utkání"],
    summary="Předvolby formací (řady)",
    operation_id="getFormations",
    response_model=FormationsOut,
    responses=MATCH_ERRORS,
)
def formations(match=Depends(own_match), conn=Depends(_conn)) -> dict:
    result: dict[str, list] = {"home": [], "away": []}
    for f in repo.formations_of_match(conn, match["id"]):
        result[f["side"]].append({"line": f["line"], **{slot: f[slot] for slot, _ in SLOT_LABELS}})
    return result


# --- events ------------------------------------------------------------------

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_EVENT_IN = TypeAdapter(EventIn)

TOO_LARGE = {413: {"model": ErrorOut, "description": "Tělo je větší než 16 kB."}}
EVENT_ERRORS = {
    **MATCH_ERRORS,
    422: {"model": ErrorOut, "description": "Neplatná událost nebo neplatné client_id."},
}
WRITE_ERRORS = {
    **EVENT_ERRORS,
    400: {"model": ErrorOut, "description": "Tělo není JSON objekt."},
    409: {"model": ConflictOut, "description": "Konflikt: version_conflict (v odpovědi je aktuální stav události) nebo duplicate_time."},
    410: {"model": ErrorOut, "description": "Událost byla smazána."},
    413: {"model": ErrorOut, "description": "Tělo je větší než 16 kB."},
}


def client_id_of(client_id: str) -> str:
    """The event id chosen by the client: a UUID in the usual 8-4-4-4-12 form, any letter case."""
    value = client_id.lower()
    if _UUID.fullmatch(value) is None:
        raise ApiError(
            422,
            "invalid_client_id",
            "client_id musí být UUID, například 550e8400-e29b-41d4-a716-446655440000.",
            fields={"client_id": "invalid_client_id"},
        )
    return value


async def event_payload(request: Request):
    """Read and check the body ourselves so that every malformed body gets the same clear answer."""
    raw = await request.body()
    try:
        body = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        body = None
    if not isinstance(body, dict):
        raise ApiError(400, "invalid_json", "Tělo požadavku musí být JSON objekt.")
    try:
        return _EVENT_IN.validate_python(body)
    except ValidationError as exc:
        fields = validation_fields(_strip_union_prefix(exc.errors(), body))
        raise ApiError(
            422,
            "validation_error",
            "Událost má neplatný tvar. Podrobnosti jsou v poli fields.",
            fields=fields,
        ) from None


def _strip_union_prefix(errors: list[dict], body: dict) -> list[dict]:
    """Pydantic reports a union member in front of the field name; keep only the member the client meant."""
    kind = body.get("type")
    wanted = {"shot": "ShotIn", "substitution": "SubstitutionIn"}.get(kind) if isinstance(kind, str) else None
    if wanted is None:
        return [{"loc": ("type",), "type": "unknown_type"}]
    cleaned = []
    for err in errors:
        loc = tuple(err.get("loc", ()))
        if loc and loc[0] in ("ShotIn", "SubstitutionIn"):
            if loc[0] != wanted:
                continue
            loc = loc[1:]
        cleaned.append({**err, "loc": loc})
    return cleaned


@router.get(
    "/matches/{match_id}/events",
    tags=["události"],
    summary="Události utkání",
    operation_id="listEvents",
    response_model=EventsOut,
    response_model_exclude_unset=True,
    responses=MATCH_ERRORS,
)
def events(
    match=Depends(own_match),
    conn=Depends(_conn),
    include_deleted: bool = Query(False, description="Vrátit i smazané události."),
) -> dict:
    # One read snapshot: the version and the events always belong together.
    conn.execute("BEGIN")
    try:
        version = repo.match_by_id(conn, match["id"])["version"]
        rows = repo.list_events(conn, match["id"], include_deleted)
    finally:
        conn.execute("COMMIT")
    return {"match_version": version, "events": repo.events_out(rows)}


@router.get(
    "/matches/{match_id}/events/{client_id}",
    tags=["události"],
    summary="Jedna událost",
    operation_id="getEvent",
    response_model=EventOneOut,
    response_model_exclude_unset=True,
    responses=EVENT_ERRORS,
)
def event_one(
    client_id: str, request: Request, match=Depends(own_match), conn=Depends(_conn)
) -> dict:
    row = repo.get_event(conn, match["id"], client_id_of(client_id))
    if row is None:
        raise ApiError(404, "unknown_event", "Taková událost v utkání není.")
    return {"event": repo.event_out(conn, row)}


@router.put(
    "/matches/{match_id}/events/{client_id}",
    tags=["události"],
    summary="Zapsat nebo opravit událost",
    operation_id="putEvent",
    response_model=PutEventOut,
    response_model_exclude_unset=True,
    responses={
        **WRITE_ERRORS,
        200: {"model": PutEventOut, "description": "Událost upravena, nebo beze změny (`unchanged: true`)."},
        201: {"model": PutEventOut, "description": "Událost vznikla."},
    },
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {
                        "oneOf": [
                            {"$ref": "#/components/schemas/ShotIn"},
                            {"$ref": "#/components/schemas/SubstitutionIn"},
                        ],
                        "discriminator": {
                            "propertyName": "type",
                            "mapping": {
                                "shot": "#/components/schemas/ShotIn",
                                "substitution": "#/components/schemas/SubstitutionIn",
                            },
                        },
                    }
                }
            },
        }
    },
)
def put_event(
    client_id: str,
    request: Request,
    response: Response,
    match=Depends(own_match),
    payload=Depends(event_payload),
    conn=Depends(_conn),
) -> dict:
    """Jedna operace pro vytvoření i opravu. `client_id` je UUID, které si klient vygeneruje sám.

    První doručení událost vytvoří (201). Další doručení se stejným `client_id` ji upraví (200).
    Když je tělo shodné s uloženým stavem, nic se nezmění a odpověď má `unchanged: true` –
    frontu po výpadku proto jde poslat znovu bez obav z duplicit.
    """
    cid = client_id_of(client_id)
    settings = request.app.state.settings
    with transaction(conn):
        ctx = context_from(match, repo.players_of_match(conn, match["id"]))
        normalized = normalize(ctx, payload)
        result = repo.upsert_event(
            conn, match["id"], cid, normalized, payload.version, settings.max_events
        )
        out = repo.event_out(conn, result.row)
    response.status_code = 201 if result.created else 200
    return {"event": out, "created": result.created, "unchanged": result.unchanged}


@router.delete(
    "/matches/{match_id}/events/{client_id}",
    tags=["události"],
    summary="Smazat událost",
    operation_id="deleteEvent",
    status_code=204,
    responses={**EVENT_ERRORS, **TOO_LARGE},
)
def delete_event(
    client_id: str, request: Request, match=Depends(own_match), conn=Depends(_conn)
) -> Response:
    """Smazání je konečné: další `PUT` na stejné `client_id` vrátí 410. Opakované smazání je 204."""
    cid = client_id_of(client_id)
    with transaction(conn):
        found = repo.delete_event(conn, match["id"], cid)
    if not found:
        raise ApiError(404, "unknown_event", "Taková událost v utkání není.")
    return Response(status_code=204)


@router.post(
    "/matches/{match_id}/reset",
    tags=["události"],
    summary="Vyprázdnit utkání",
    operation_id="resetMatch",
    response_model=ResetOut,
    responses={**MATCH_ERRORS, **TOO_LARGE},
)
def reset(match=Depends(own_match), conn=Depends(_conn)) -> dict:
    """Smaže všechny události utkání včetně smazaných, takže jejich `client_id` jdou použít znovu."""
    with transaction(conn):
        deleted = repo.reset_match(conn, match["id"])
    return {"deleted": deleted}
