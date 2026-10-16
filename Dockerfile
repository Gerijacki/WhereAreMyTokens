# syntax=docker/dockerfile:1

# ---- Dashboard build ----
FROM node:22-alpine AS web
WORKDIR /web
RUN corepack enable
COPY web/package.json web/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY web/ ./
RUN pnpm build

# ---- Runtime ----
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    WAMT_STATIC_DIR=/app/static \
    WAMT_CLAUDE_DATA_DIR=/data/claude \
    WAMT_DATABASE_URL=sqlite:////data/wamt/wamt.db
WORKDIR /app
COPY backend/pyproject.toml ./backend/
COPY backend/wamt ./backend/wamt
RUN pip install ./backend
COPY --from=web /web/dist /app/static
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN useradd --create-home --uid 1000 wamt && mkdir -p /data/wamt && chown wamt /data/wamt
# Without PostgreSQL (docker compose sets it up), history is kept in SQLite here: mount a volume.
VOLUME /data/wamt
USER wamt
EXPOSE 8787
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/api/health')"
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["serve"]
