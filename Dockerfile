FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.6.17 /uv /usr/local/bin/uv

WORKDIR /srv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PATH="/srv/.venv/bin:$PATH" \
    ZAPI_DB_PATH=/data/zapisovatel.sqlite

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app ./app
COPY data/demo-match.json ./data/demo-match.json
COPY data/matches ./data/matches

RUN useradd --system --uid 10001 --home /srv app \
    && mkdir -p /data && chown app:app /data
USER app
VOLUME /data
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2).status == 200 else 1)"

CMD ["uvicorn", "app.main:app_from_env", "--factory", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", "--limit-concurrency", "200", "--timeout-keep-alive", "5", "--no-server-header"]
