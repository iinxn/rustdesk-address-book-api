# syntax=docker/dockerfile:1
#
# RustDesk address-book backend: API + React panel + KX shim, one process.
#
#   docker build -t rustdesk-ab-backend:local .
#   docker buildx build --platform linux/amd64,linux/arm64 \
#       -t <dockerhub-user>/rustdesk-ab-backend:<version> --push .
#
# Runtime contract (see docs/development/WORKFLOW.md §4):
#   /app/data  - SQLite DB + auto-generated secrets; mount a volume here.
#   /app/keys  - optional, read-only: hbbs id_ed25519 for the shim.
#   8000/tcp   - HTTP API + panel (plain HTTP, terminate TLS on a proxy).
#   21116/tcp+udp - KX shim, only when SHIM_ENABLED=1.

# ---- Stage 1: React panel ----------------------------------------------------
# The bundle is platform independent: build it once on the build machine's
# native platform even for multi-arch images (no emulated npm).
FROM --platform=$BUILDPLATFORM node:22-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- Stage 2: Python runtime -------------------------------------------------
FROM python:3.13-slim

ARG VERSION=dev
ARG REVISION=unknown
LABEL org.opencontainers.image.title="rustdesk-ab-backend" \
      org.opencontainers.image.description="Self-hosted address book API, web panel and KeyExchange shim for stock RustDesk clients" \
      org.opencontainers.image.source="https://github.com/iinxn/rustdesk-address-book-api" \
      org.opencontainers.image.version="$VERSION" \
      org.opencontainers.image.revision="$REVISION"

# Container defaults; each one can be overridden with `docker run -e`.
# HOST must not stay at the native default 127.0.0.1: that would be the
# container's own loopback and the published port would be dead.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOST=0.0.0.0 \
    PORT=21114 \
    SHIM_LISTEN=0.0.0.0:21116 \
    SHIM_ID_KEY=/app/keys/id_ed25519

WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

# Code is owned by root and read-only for the service user: a compromised
# process cannot rewrite the app or its migrations. Only data/ and logs/
# belong to appuser. Bytecode is compiled now because the runtime cannot.
COPY alembic.ini ./
COPY alembic/ ./alembic/
COPY app/ ./app/
COPY scripts/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
COPY --from=frontend /build/dist ./frontend/dist
# UID/GID 1000 matches the usual first Linux user, so a bind-mounted ./data
# owned by that user stays writable. Otherwise run with `user: UID:GID`.
RUN python -m compileall -q app alembic \
 && groupadd --gid 1000 appuser \
 && useradd --uid 1000 --gid 1000 --no-create-home --home-dir /app \
            --shell /usr/sbin/nologin appuser \
 && mkdir -p /app/data /app/logs /app/keys \
 && chown appuser:appuser /app/data /app/logs \
 && chmod 700 /app/data \
 && chmod 755 /usr/local/bin/docker-entrypoint.sh
USER appuser

# Without a mounted volume the database dies with the container.
VOLUME ["/app/data"]

EXPOSE 21114/tcp 21116/tcp 21116/udp

# /health/ready is 503 when the DB is down or the enabled shim is down.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD ["python", "-c", "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health/ready' % os.environ.get('PORT', '21114'), timeout=4)"]

# The entrypoint fills missing secrets once (persisted in /app/data), then
# execs the app: `python -m app` validates config, runs Alembic migrations
# and serves FastAPI (+ the supervised shim when enabled).
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["python", "-m", "app"]
