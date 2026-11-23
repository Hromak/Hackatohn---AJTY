"""The published API description: FastAPI's output, completed and cleaned."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from pydantic.json_schema import models_json_schema

from app.models import ShotIn, SubstitutionIn

_FRAMEWORK_SCHEMAS = ("HTTPValidationError", "ValidationError")
_PUBLIC_PATHS = {"/api/health"}


def _replace_refs(node, old: str, new: str):
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "$ref" and value == old:
                node[key] = new
            else:
                _replace_refs(value, old, new)
    elif isinstance(node, list):
        for item in node:
            _replace_refs(item, old, new)


def build(app: FastAPI) -> dict:
    spec = get_openapi(
        title=app.title, version=app.version, description=app.description, routes=app.routes
    )
    schemas = spec.setdefault("components", {}).setdefault("schemas", {})

    # The event body is read by hand (to answer malformed bodies clearly), so its two shapes
    # are added here.
    _, definitions = models_json_schema(
        [(ShotIn, "validation"), (SubstitutionIn, "validation")],
        ref_template="#/components/schemas/{model}",
    )
    for name, schema in definitions.get("$defs", {}).items():
        schemas.setdefault(name, schema)

    # Every error has the common shape, including validation errors.
    _replace_refs(spec, "#/components/schemas/HTTPValidationError", "#/components/schemas/ErrorOut")
    for name in _FRAMEWORK_SCHEMAS:
        schemas.pop(name, None)
    for operations in spec["paths"].values():
        for operation in operations.values():
            answer = operation.get("responses", {}).get("422")
            if answer and answer.get("description") == "Validation Error":
                answer["description"] = "Požadavek má neplatný tvar."

    spec["components"]["securitySchemes"] = {"bearer": {"type": "http", "scheme": "bearer"}}
    for path, operations in spec["paths"].items():
        if path in _PUBLIC_PATHS:
            continue
        for operation in operations.values():
            operation["security"] = [{"bearer": []}]
    return spec


def install(app: FastAPI) -> None:
    def openapi() -> dict:
        if app.openapi_schema is None:
            app.openapi_schema = build(app)
        return app.openapi_schema

    app.openapi = openapi
