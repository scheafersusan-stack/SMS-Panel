# syntax=docker/dockerfile:1.7
# One image for the compose services `migrate`, `api` and `worker` (different commands).
# Build context: repository root.
#   docker build -f apps/panel-api/Dockerfile -t payamakyar/panel-api:dev .
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=/usr/local/bin/python3.12 \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /src
COPY . .
# --no-editable installs the workspace members (including the alembic scripts that ship inside
# payamakyar.db) into the venv, so the runtime stage needs no source tree.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --package payamakyar-panel-api

FROM python:3.12-slim
RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --home-dir /app --no-create-home --shell /usr/sbin/nologin app
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
# Fail safe: without settings the image runs as prod (dev secrets refused); the dev compose
# stack sets PAYAMAKYAR_ENV=dev explicitly from infra/.env.
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PAYAMAKYAR_ENV=prod
USER app
EXPOSE 8000
CMD ["python", "-m", "payamakyar.api", "serve", "--host", "0.0.0.0", "--port", "8000"]
