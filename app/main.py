"""Application factory."""
from __future__ import annotations

import logging
import sqlite3

from fastapi import FastAPI, Request

from app.config import Settings
from app.db import connect, init_schema, transaction
from app.errors import install_handlers

log = logging.getLogger("zapi")

DESCRIPTION = """
Data pro tabletovou aplikaci zapisovatele florbalového utkání a sběr toho, co zapsala.

Token posílejte v hlavičce `Authorization: Bearer <token>`. Průvodce je v README repozitáře.
"""


def get_conn(request: Request):
    conn = connect(request.app.state.settings.db_path)
    try:
        yield conn
    finally:
        conn.close()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    app = FastAPI(
        title="Zapisovatel API",
        version="1.0.0",
        description=DESCRIPTION,
        openapi_url="/api/openapi.json",
        # The interactive browser loads its script from a CDN; keep it to local development.
        docs_url="/api/docs" if settings.demo else None,
        redoc_url=None,
        swagger_ui_oauth2_redirect_url=None,
        redirect_slashes=False,
    )
    app.state.settings = settings

    # Fail at startup, not on the first request, when the database cannot be opened or written.
    try:
        conn = connect(settings.db_path)
        try:
            init_schema(conn)
            from app.seed import ensure_bootstrap

            with transaction(conn):
                ensure_bootstrap(conn, settings)
        finally:
            conn.close()
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    except (OSError, sqlite3.Error) as exc:
        raise SystemExit(
            f"Databázi nejde otevřít nebo do ní zapisovat: {settings.db_path} ({exc}). "
            "Zkontrolujte proměnnou ZAPI_DB_PATH a práva k adresáři."
        ) from None
    if settings.demo:
        log.info(
            "Ukázkový tým je připraven. Token: %s (hlavička Authorization: Bearer %s).",
            settings.demo_token,
            settings.demo_token,
        )

    install_handlers(app)

    from app.middleware import install as install_middleware

    install_middleware(app, settings)

    from app.routes_public import router as public_router

    app.include_router(public_router)

    from app.openapi import install as install_openapi

    install_openapi(app)

    @app.get("/api/health", tags=["služba"], summary="Je služba naživu?", operation_id="getHealth")
    def health() -> dict:
        return {"status": "ok"}

    return app


def app_from_env() -> FastAPI:
    """Entry point for uvicorn (--factory): settings from the environment, messages to the console."""
    if not log.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s:     %(message)s"))
        log.addHandler(handler)
        log.setLevel(logging.INFO)
        log.propagate = False
    return create_app(Settings.from_env())
