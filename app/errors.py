"""One error shape for the whole API: {"error": {"code", "message", "fields"?}}."""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("zapi")


class ApiError(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        fields: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        extra: dict | None = None,
    ):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.fields = fields
        self.headers = headers
        self.extra = extra


def error_body(code: str, message: str, fields: dict[str, str] | None = None) -> dict:
    error: dict = {"code": code, "message": message}
    if fields:
        error["fields"] = fields
    return {"error": error}


def error_response(
    request: Request | None,
    status: int,
    code: str,
    message: str,
    fields: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    extra: dict | None = None,
) -> JSONResponse:
    body = error_body(code, message, fields)
    if extra:
        body.update(extra)
    return JSONResponse(body, status_code=status, headers=headers)


def validation_fields(errors: list[dict]) -> dict[str, str]:
    fields: dict[str, str] = {}
    for err in errors:
        loc = [str(part) for part in err.get("loc", ()) if part not in ("body", "query", "path")]
        fields[".".join(loc) or "body"] = str(err.get("type", "invalid"))
    return fields


_HTTP_CODES = {
    404: ("not_found", "Tato adresa neexistuje."),
    405: ("method_not_allowed", "Tuto metodu adresa nepodporuje."),
}


def install_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError):
        return error_response(
            request, exc.status, exc.code, exc.message, exc.fields, exc.headers, exc.extra
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        return error_response(
            request,
            422,
            "validation_error",
            "Požadavek má neplatný tvar. Podrobnosti jsou v poli fields.",
            validation_fields(exc.errors()),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        code, message = _HTTP_CODES.get(exc.status_code, ("http_error", "Požadavek nelze zpracovat."))
        return error_response(request, exc.status_code, code, message)

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception):
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        return error_response(request, 500, "internal_error", "Neočekávaná chyba serveru.")


# Every code the API can return. Published in the API description; a test keeps it complete.
ERROR_CODES = [
    "invalid_json", "unauthorized", "not_found", "unknown_event",
    "method_not_allowed", "version_conflict", "duplicate_time", "deleted", "payload_too_large",
    "validation_error", "invalid_client_id", "invalid_period", "invalid_time", "time_out_of_period",
    "unknown_player", "wrong_team", "not_goalkeeper", "assist_is_shooter", "goal_fields_on_non_goal",
    "out_of_rink", "too_few_players", "too_many_players", "empty_net_required", "duplicate_player",
    "goalkeeper_in_line", "type_change", "event_limit", "forced_rejection", "rate_limited",
    "too_many_concurrent_requests", "forced_unavailable", "internal_error",
]
