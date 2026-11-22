# One image: the React app built into static files, served by the FastAPI backend.
#   docker build -t sorter-3dprint-helper .
#   docker run -p 8000:8000 -v sorter3mf-cache:/data sorter-3dprint-helper
#
# Runs as an unprivileged user (uid/gid 10001) and writes only to /data, so it
# also runs with a read-only root filesystem (mount /data, and /tmp as tmpfs).

# The frontend is static files, the same on every platform: build it once, on
# the build machine's own architecture, even when the image is for another.
FROM --platform=$BUILDPLATFORM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:0.8.15 /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
RUN uv sync --frozen --no-dev --no-install-project --python /usr/local/bin/python3
COPY backend/ ./
RUN uv sync --frozen --no-dev --python /usr/local/bin/python3
COPY --from=web /web/dist /app/frontend/dist
COPY LICENSE /app/LICENSE

# The app owns nothing but its data directory; the code stays root-owned and
# read-only to it.
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /data --no-create-home --shell /usr/sbin/nologin app \
    && mkdir -p /data && chown app:app /data && chmod 0750 /data

# Where this app's source is (shown on the page, see README "Licence"). CI
# passes the repository URL; SORTER3MF_SOURCE_URL at run time overrides it.
ARG SOURCE_URL=""
ENV SORTER3MF_SOURCE_URL=$SOURCE_URL \
    SORTER3MF_CACHE=/data \
    SORTER3MF_FRONTEND=/app/frontend/dist \
    HOME=/data \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH=/app/backend/.venv/bin:$PATH
USER 10001:10001
VOLUME /data
EXPOSE 8000
CMD ["uvicorn", "sorter3mf.api:app", "--host", "0.0.0.0", "--port", "8000"]
