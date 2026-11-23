"""Request guards: body size and rate limits."""
from __future__ import annotations

import hashlib
import logging
import threading
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings
from app.errors import error_response

log = logging.getLogger("zapi")

_PRUNE_ABOVE = 1000
_UNVERIFIED = "unverified"


class TokenBucket:
    """A token bucket per key. `rate` tokens per second, at most `burst` saved up."""

    def __init__(self, rate: float, burst: int):
        self.rate = float(rate)
        self.burst = float(burst)
        self._state: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def __len__(self) -> int:
        return len(self._state)

    def allow(self, key: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        with self._lock:
            tokens, last = self._state.get(key, (self.burst, now))
            tokens = min(self.burst, tokens + (now - last) * self.rate)
            allowed = tokens >= 1.0
            if allowed:
                tokens -= 1.0
            self._state[key] = (tokens, now)
            if len(self._state) > _PRUNE_ABOVE:
                self._prune(now)
            return allowed

    def _prune(self, now: float) -> None:
        """Drop keys that have been idle long enough to be full again."""
        idle = self.burst / self.rate if self.rate > 0 else float("inf")
        self._state = {k: v for k, v in self._state.items() if now - v[1] < idle}


def _token_key(request: Request) -> str | None:
    header = request.headers.get("authorization")
    if not header:
        return None
    return hashlib.sha256(header.encode("utf-8", "surrogateescape")).hexdigest()


async def _read_limited(request: Request, limit: int) -> bool:
    """Read the body, stopping as soon as it exceeds the limit. Returns False when it is too large."""
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > limit:
        return False
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            return False
        chunks.append(chunk)
    request._body = b"".join(chunks)  # let the route read the same bytes again
    return True


def install(app: FastAPI, settings: Settings) -> None:
    per_token = TokenBucket(settings.rate_per_sec, settings.rate_burst)
    unverified = TokenBucket(settings.rate_per_sec, settings.rate_burst)
    everyone = TokenBucket(settings.global_rate_per_sec, settings.global_rate_burst)
    known: set[str] = set()          # hashes of Authorization headers that authenticated
    in_flight: dict[str, int] = {}
    in_flight_lock = threading.Lock()

    def limited(request: Request, key: str | None) -> str | None:
        """Decide whether to refuse the request. Returns an error code or None.

        A token that has authenticated before has its own budget. Everything else – no token,
        an unknown token, the static pages – shares one small budget, so that nobody without a
        valid token can spend a team's or the whole service's allowance.
        """
        if key is not None and key in known:
            if not per_token.allow(key):
                return "rate_limited"
        elif not unverified.allow(_UNVERIFIED):
            return "rate_limited"
        if not everyone.allow("all"):
            return "rate_limited"
        return None

    @app.middleware("http")
    async def guard(request: Request, call_next):
        path = request.url.path
        if path == "/api/health":
            return await call_next(request)
        key = _token_key(request)
        code = limited(request, key)
        if code is not None:
            return error_response(
                request,
                429,
                code,
                "Příliš mnoho požadavků. Zkuste to za chvíli znovu.",
                headers={"Retry-After": "1"},
            )
        slot = key if key is not None and key in known else None
        if slot is not None:
            with in_flight_lock:
                if in_flight.get(slot, 0) >= settings.max_in_flight:
                    return error_response(
                        request,
                        429,
                        "too_many_concurrent_requests",
                        f"Tým má rozpracováno {settings.max_in_flight} požadavků najednou. "
                        "Počkejte na odpovědi a pak pošlete další.",
                        headers={"Retry-After": "1"},
                    )
                in_flight[slot] = in_flight.get(slot, 0) + 1
        try:
            response = None
            if request.method in ("PUT", "POST", "PATCH", "DELETE"):
                if not await _read_limited(request, settings.max_body):
                    response = error_response(
                        request,
                        413,
                        "payload_too_large",
                        f"Tělo požadavku je větší než {settings.max_body} bajtů.",
                    )
            if response is None:
                try:
                    response = await call_next(request)
                except Exception:
                    # Handled here (not by the server's last-resort handler) so that the answer
                    # keeps the common error shape and gets CORS headers.
                    log.exception("unhandled error on %s %s", request.method, path)
                    response = error_response(
                        request, 500, "internal_error", "Neočekávaná chyba serveru."
                    )
        finally:
            if slot is not None:
                with in_flight_lock:
                    remaining = in_flight.get(slot, 1) - 1
                    if remaining > 0:
                        in_flight[slot] = remaining
                    else:
                        in_flight.pop(slot, None)
        if key is not None and getattr(request.state, "team_id", None) is not None:
            known.add(key)
        return response

    # Added last = outermost: every response, including 429 and 413 above, gets CORS headers.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "PUT", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
        allow_credentials=False,
        allow_private_network=True,  # a page served from the internet may call a local instance
        expose_headers=["Retry-After"],
        max_age=600,
    )
