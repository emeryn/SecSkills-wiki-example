# syntax=docker/dockerfile:1
# Build context: repository root. Final stage: no shell, no package manager, numeric non-root user.
ARG PYTHON_DEV_IMAGE=cgr.dev/chainguard/python:latest-dev@sha256:e8e6a6f7677673d91c9b28fa2ec6ad62cd5ed532179846d2c14e75c93a12c3fc
ARG PYTHON_IMAGE=cgr.dev/chainguard/python:latest@sha256:1c4deeea85db49ab5f6bcd9e7fc0bf3fd8439e99f7bde45330f40400685eb394
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.9@sha256:538e0b39736e7feae937a65983e49d2ab75e1559d35041f9878b7b7e51de91e4

FROM ${UV_IMAGE} AS uv

FROM ${PYTHON_DEV_IMAGE} AS build
USER root
COPY --from=uv /uv /usr/local/bin/uv
ARG UV_INDEX_URL
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/alembic.ini ./
COPY backend/migrations ./migrations
COPY backend/data ./data
COPY backend/app ./app
RUN mkdir -p /skel/run/secrets /skel/var/lib/wiki/attachments /skel/var/lib/wiki/backups

FROM build AS test
RUN uv sync --frozen --no-install-project
COPY backend/tests ./tests
ENV PATH=/opt/venv/bin:$PATH
ENTRYPOINT []
CMD ["pytest"]

FROM test AS audit
RUN uv export --frozen --no-dev --no-emit-project --format requirements-txt -o /tmp/requirements.txt \
 && pip-audit --strict --disable-pip --require-hashes -r /tmp/requirements.txt

FROM ${PYTHON_IMAGE} AS runtime
WORKDIR /app
COPY --from=build /opt/venv /opt/venv
COPY --from=build /app /app
COPY --from=build --chown=10001:10001 --chmod=0755 /skel/run/secrets /run/secrets
COPY --from=build --chown=10001:10001 --chmod=0700 /skel/var/lib/wiki/attachments /var/lib/wiki/attachments
COPY --from=build --chown=10001:10001 --chmod=0700 /skel/var/lib/wiki/backups /var/lib/wiki/backups
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
USER 10001:10001
EXPOSE 8000
ENTRYPOINT []
CMD ["python", "-m", "app.server"]
