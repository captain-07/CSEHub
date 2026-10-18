# syntax=docker/dockerfile:1

# The app runs on Python 3.12 (see .python-version). langchain-pinecone==0.2.13
# caps the interpreter below 3.14 — the same constraint build.sh guards on for
# Render — so the base image is pinned to match rather than tracking latest.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# psycopg[binary], Pillow and cryptography all ship manylinux wheels, so the slim
# base needs no compiler, libpq-dev or image libraries.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend ./backend

# Build the WhiteNoise manifest that is served at runtime. settings.py refuses to
# import without a database URL, even though collectstatic never opens a
# connection, so a throwaway DSN satisfies the import. Both values here are read
# only to get settings loaded: neither leaks a secret into a layer, and the
# hashed asset names do not depend on SECRET_KEY.
RUN SECRET_KEY=build-only \
    DATABASE_URL=postgresql://build:build@localhost:5432/build \
    python backend/manage.py collectstatic --noinput

# The repo is developed on Windows, where a CRLF checkout would leave a stray
# `\r` on every line and break this `#!/bin/sh` script under Linux. Normalise it
# here rather than depend on the checkout's line endings.
COPY docker/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN sed -i 's/\r$//' /usr/local/bin/docker-entrypoint.sh \
    && chmod +x /usr/local/bin/docker-entrypoint.sh \
    && useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/backend/media \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]

# Mirrors the Procfile: Gunicorn over WSGI, bound to ${PORT:-8000}. `--chdir
# backend` puts the process beside manage.py so `core.settings` imports.
# `sh -c` is what lets the shell expand the defaults; the entrypoint execs it.
CMD ["sh", "-c", "exec gunicorn core.wsgi:application --chdir backend --bind 0.0.0.0:${PORT:-8000} --workers ${GUNICORN_WORKERS:-3} --timeout ${GUNICORN_TIMEOUT:-60} --access-logfile -"]
