# Local development image for the Sliver API and pipeline worker.
FROM python:3.13.18-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.9.17 /uv /uvx /bin/

ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH=/opt/venv/bin:$PATH

WORKDIR /app

# Dependencies first so source edits do not invalidate the cached layer.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen

COPY . .

EXPOSE 8000
# Open activity streams (server-sent events) must not hold up a reload or stop for long.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn --factory sliver_api.main:create_app --host 0.0.0.0 --port 8000 --reload --reload-dir sliver_api --timeout-graceful-shutdown 3"]
