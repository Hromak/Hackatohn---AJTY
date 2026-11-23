"""Request and response shapes. The OpenAPI description is generated from these."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Side = Literal["home", "away"]
Position = Literal["G", "D", "F"]
ShotResult = Literal["miss", "on_goal", "post", "goal"]
Strength = Literal["even", "power_play", "short_handed"]

RINK_WIDTH = 890
RINK_HEIGHT = 501
RINK_CENTER_X = 445


class TeamOut(BaseModel):
    id: int
    name: str


class MatchItem(BaseModel):
    id: int
    home: str
    away: str
    date: str


class MeOut(BaseModel):
    team: TeamOut
    matches: list[MatchItem]


class MatchesOut(BaseModel):
    matches: list[MatchItem]


class ClubOut(BaseModel):
    name: str
    short_name: str


class PeriodOut(BaseModel):
    period: int = Field(description="Číslo hrací části, které se posílá v událostech.")
    label: str
    length: str = Field(description="Délka části jako mm:ss. Čas události musí být menší.")
    overtime: bool


class MatchOut(BaseModel):
    id: int
    competition: str | None
    date: str
    venue: str | None
    home: ClubOut
    away: ClubOut
    periods: list[PeriodOut]
    version: int = Field(description="Roste s každou změnou událostí utkání.")


class PlayerOut(BaseModel):
    id: int = Field(description="Id hráče v tomto utkání. Používá se v událostech.")
    jersey: int
    first_name: str
    last_name: str
    position: Position = Field(description="G = brankář, D = obránce, F = útočník.")
    captain: bool


class RosterOut(BaseModel):
    home: list[PlayerOut]
    away: list[PlayerOut]


class LineOut(BaseModel):
    line: int = Field(description="Číslo řady (1–3).")
    lw: int | None = Field(description="Levé křídlo – id hráče, nebo null.")
    c: int | None = Field(description="Center.")
    rw: int | None = Field(description="Pravé křídlo.")
    ld: int | None = Field(description="Levý obránce.")
    rd: int | None = Field(description="Pravý obránce.")


class FormationsOut(BaseModel):
    home: list[LineOut]
    away: list[LineOut]


class CodeLabel(BaseModel):
    code: str
    label: str


class RinkOut(BaseModel):
    width: int
    height: int
    center_x: int
    origin: Literal["top_left"]
    home_attacks: Literal["right"]
    note: str


class CodebooksOut(BaseModel):
    shot_results: list[CodeLabel]
    strengths: list[CodeLabel]
    positions: list[CodeLabel]
    formation_slots: list[CodeLabel]
    rink: RinkOut


from app.errors import ERROR_CODES  # noqa: E402


class ErrorDetail(BaseModel):
    code: str = Field(
        description="Stabilní strojový kód chyby. Všechny kódy jsou v `examples` a v README.",
        examples=ERROR_CODES,
    )
    message: str = Field(description="Česká věta pro člověka.")
    fields: dict[str, str] | None = Field(
        default=None, description="Která pole jsou špatně (jen u chyb validace)."
    )


class ErrorOut(BaseModel):
    model_config = ConfigDict(extra="allow")
    error: ErrorDetail


# --- events: requests --------------------------------------------------------

_STRICT = ConfigDict(extra="forbid", strict=True)


class OnIce(BaseModel):
    """Kdo byl při gólu na hřišti (id hráčů každé strany, nejvýš 6 na stranu)."""

    model_config = _STRICT
    home: list[int] = Field(default_factory=list)
    away: list[int] = Field(default_factory=list)


class _EventBase(BaseModel):
    model_config = _STRICT
    team: Side = Field(description="Tým, kterého se událost týká: home = domácí, away = hosté.")
    period: int = Field(description="Hrací část podle hlavičky utkání (1–3, prodloužení 4).")
    time: str = Field(
        description='Čas od začátku hrací části, jak ho ukazuje časomíra: "mm:ss".',
        examples=["07:42"],
        json_schema_extra={"pattern": "^[0-9]{2}:[0-5][0-9]$"},
    )
    strength: Strength = Field(
        default="even",
        description="Poměr sil z pohledu týmu: even = vyrovnaný, power_play = přesilovka, "
        "short_handed = oslabení.",
    )
    version: int | None = Field(
        default=None,
        description="Nepovinné. Verze události, ze které klient vychází. Když se liší od uložené "
        "a obsah je jiný, vrací se 409 version_conflict.",
    )


class ShotIn(_EventBase):
    """Střela."""

    type: Literal["shot"]
    # Ranges are checked by the rules (so the answer carries a precise code); the schema states them.
    x: int = Field(
        description="Vodorovná souřadnice 0–890. Domácí útočí vždy doprava (x ≥ 445).",
        json_schema_extra={"minimum": 0, "maximum": RINK_WIDTH},
    )
    y: int = Field(
        description="Svislá souřadnice 0–501, počátek vlevo nahoře.",
        json_schema_extra={"minimum": 0, "maximum": RINK_HEIGHT},
    )
    result: ShotResult = Field(
        description="miss = mimo, on_goal = na branku (chycená), post = tyčka, goal = gól."
    )
    shooter_id: int = Field(description="Id střelce; musí být hráč týmu `team`.")
    goalkeeper_id: int | None = Field(
        default=None, description="Id brankáře soupeře; null = prázdná branka nebo neuvedeno."
    )
    assist_id: int | None = Field(
        default=None, description="Jen u gólu: id asistujícího hráče týmu `team`."
    )
    on_ice: OnIce | None = Field(default=None, description="Jen u gólu: kdo byl na hřišti.")


class SubstitutionIn(_EventBase):
    """Střídání: sestava, která v daný čas nastoupila."""

    type: Literal["substitution"]
    players: list[int] = Field(
        description="Id hráčů v poli po střídání (3–6, bez brankářů). "
        "Šest jen při hře bez brankáře (`empty_net: true`).",
        json_schema_extra={"minItems": 3, "maxItems": 6, "uniqueItems": True},
    )
    empty_net: bool = Field(default=False, description="Hra bez brankáře.")


EventIn = ShotIn | SubstitutionIn


# --- events: responses -------------------------------------------------------


_CLIENT_ID = Field(description="UUID, které události přidělil klient.")
_VERSION = Field(description="Začíná na 1, každá skutečná změna ji zvýší.")
_SEQ = Field(description="Pořadí prvního doručení události v utkání.")
_WARNINGS = Field(description="Upozornění, která událost neodmítají, např. shot_from_own_half.")
_DELETED = Field(default=None, description="Vyplněno jen u smazané události.")


class ShotOut(BaseModel):
    client_id: str = _CLIENT_ID
    type: Literal["shot"]
    team: Side
    period: int
    time: str
    x: int
    y: int
    result: ShotResult
    strength: Strength
    shooter_id: int
    goalkeeper_id: int | None
    assist_id: int | None
    on_ice: OnIce | None
    version: int = _VERSION
    seq: int = _SEQ
    created_at: str
    updated_at: str
    warnings: list[str] = _WARNINGS
    deleted_at: str | None = _DELETED


class SubstitutionOut(BaseModel):
    client_id: str = _CLIENT_ID
    type: Literal["substitution"]
    team: Side
    period: int
    time: str
    players: list[int]
    strength: Strength
    empty_net: bool
    in_: list[int] = Field(alias="in", description="Kdo přišel proti předchozímu střídání týmu.")
    out: list[int] = Field(description="Kdo odešel proti předchozímu střídání týmu.")
    version: int = _VERSION
    seq: int = _SEQ
    created_at: str
    updated_at: str
    warnings: list[str] = _WARNINGS
    deleted_at: str | None = _DELETED


EventOut = ShotOut | SubstitutionOut


class PutEventOut(BaseModel):
    event: EventOut
    created: bool = Field(description="true = událost s tímto client_id právě vznikla.")
    unchanged: bool = Field(
        description="true = tělo se shoduje s uloženým stavem, nic se nezměnilo "
        "(opakované doručení)."
    )


class ConflictOut(BaseModel):
    """Chyba 409. U `version_conflict` nese i aktuální stav události."""

    error: ErrorDetail
    event: EventOut | None = Field(
        default=None, description="Aktuální uložený stav události (jen u version_conflict)."
    )


class EventOneOut(BaseModel):
    event: EventOut


class EventsOut(BaseModel):
    match_version: int
    events: list[EventOut]


class ResetOut(BaseModel):
    deleted: int


class ErrorModeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["off", "reject", "unavailable"] = Field(
        description="off = běžný provoz; reject = každý zápis vrací 422 forced_rejection; "
        "unavailable = vše vrací 503 forced_unavailable."
    )


class ErrorModeOut(BaseModel):
    mode: Literal["off", "reject", "unavailable"]
