# Execs NOW HQ — one image for all three Railway services (Phase 7):
# web (gunicorn), qcluster (the worker) and backup (the nightly cron). Each
# service runs the same build with its own start command (railway/*.json).
#
# A Dockerfile rather than Railway's auto-detected build, because two things
# here must be exact and visible: WeasyPrint's system libraries (without them
# the strategy PDF and the value report fail only when someone uses them, not
# at boot), and the pg_dump major version (a backup taken with an older
# pg_dump than the server's refuses to run).

# Base images (2026-11-27, docs/security_updates.md): each is pinned to the
# exact image by its digest, so a build uses what was tested and the image
# changes only in a commit. Dependabot (.github/dependabot.yml) proposes the new
# digest on dev when Docker publishes a rebuilt image of the same tag; the
# tags themselves (Python 3.12, Node 24, Debian 12) move only by decision.

# ---------------------------------------------------------------- the bundle
FROM node:24-bookworm-slim@sha256:873f586f3794f52281bd039bf02c048a0be08fde619338f9941bad1eb6b34530 AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ------------------------------------------------------------------- the app
FROM python:3.12-slim-bookworm@sha256:44cf1793efa7c7a476bb0f2cff81443f4a072c90c1cb127e2924933daa3e8c64

# pg_dump must be at least the server's major version. Production's Railway
# Postgres is 18 and the demo's 16 (2026-09-29); pg_dump 18 dumps both.
ARG PG_MAJOR=18

# Current system packages on every build (2026-11-27, docs/security_updates.md).
# Railway keeps a layer cache: Release 54's build reused the system-package
# step as it was last built, printing nothing. Railway gives a GitHub-triggered
# build its commit as RAILWAY_GIT_COMMIT_SHA when it is declared here, and a
# changed ARG used by a RUN is a cache miss, so the step below runs afresh for
# every commit: `apt-get upgrade` brings Debian's security fixes released since
# the base image was made. The step records what it did in
# /etc/enhq-system-packages (commit, time, and packages still upgradable,
# which should be 0); `cat` it in a running service to check. "unknown" there
# means Railway passed no commit and the layer may have come from the cache.
ARG RAILWAY_GIT_COMMIT_SHA=unknown

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# WeasyPrint: Pango (with HarfBuzz and its subsetter) and fonts. The PDFs ask
# for Helvetica/Arial; fonts-croscore's Arimo is what the laptop resolves that
# to, so the PDF lays out the same here. pg_dump from PGDG, at PG_MAJOR.
RUN echo "system packages for commit ${RAILWAY_GIT_COMMIT_SHA}" \
 && apt-get update \
 && apt-get upgrade -y --no-install-recommends \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl gnupg \
      libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libharfbuzz-subset0 \
      fonts-croscore fonts-liberation fonts-dejavu-core fontconfig \
 && install -d /usr/share/postgresql-common/pgdg \
 && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
      -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
 && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" \
      > /etc/apt/sources.list.d/pgdg.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends postgresql-client-${PG_MAJOR} \
 && apt-get purge -y gnupg && apt-get autoremove -y \
 && echo "commit=${RAILWAY_GIT_COMMIT_SHA} built=$(date -u +%Y-%m-%dT%H:%M:%SZ) still_upgradable=$(apt-get -s upgrade | grep -c '^Inst ')" \
      > /etc/enhq-system-packages \
 && cat /etc/enhq-system-packages \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY . .
COPY --from=frontend /build/dist ./frontend/dist

# collectstatic needs settings to import, and settings refuse production
# defaults — so it runs with localhost values that exist only for this step.
RUN PUBLIC_BASE_URL=http://localhost:8100 DJANGO_SECRET_KEY=collectstatic-only \
    DEV_REAL_SEND_ALLOWLIST= DATABASE_URL=postgres://build@localhost/build \
    python manage.py collectstatic --noinput

RUN useradd --create-home --uid 10001 app && chown -R app /app
USER app

# 8080: the port both custom domains are pointed at (owner, 2026-09-29).
# Each service overrides this command (railway/*.json).
EXPOSE 8080
CMD ["scripts/start_web.sh"]
