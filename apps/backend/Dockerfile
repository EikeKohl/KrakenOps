# syntax=docker/dockerfile:1
#
# Multi-stage build for the KrakenOps backend.
#
# Stage 1 (deps) — install python deps into a virtualenv via uv. Cached on
# pyproject.toml + uv.lock changes only.
# Stage 2 (runtime) — slim image carrying just python + the venv + the app.

FROM python:3.12-slim AS deps

# uv is shipped as a single static binary; pull from the official ghcr image.
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /uvx /usr/local/bin/

WORKDIR /app

# Copy only files that affect dependency resolution. Source files come later
# so changes to app code don't bust the dependency layer cache.
COPY pyproject.toml ./
COPY uv.lock* ./

# `--no-install-project` skips installing the project itself; we only want
# its dependencies in this layer. `--no-dev` drops pytest/ruff/etc.
RUN uv sync --no-install-project --no-dev


FROM python:3.12-slim AS runtime

# Same uv binary in case anyone needs to introspect or run a one-off script
# inside a running container.
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /uvx /usr/local/bin/

WORKDIR /app

# Pull in the venv populated in the deps stage.
COPY --from=deps /app/.venv /app/.venv

# Now the actual application source (and migrations + bundled pricing).
COPY app ./app
COPY migrations ./migrations
COPY pricing ./pricing
COPY pyproject.toml ./

# Activate the venv for all subsequent commands.
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

# State dir — the compose file mounts a volume here.
ENV KRAKENOPS_HOME=/data
RUN mkdir -p /data

EXPOSE 8787

# 0.0.0.0 (not 127.0.0.1) so the dashboard container + the host can reach it.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8787"]
