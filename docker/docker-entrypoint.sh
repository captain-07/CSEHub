#!/bin/sh
# Container entrypoint: bring the project up, then hand off to the command
# (Gunicorn by default, `runserver` under the dev override).
#
# Seeding is deliberately off by default. `manage.py seed` is idempotent, but it
# writes sample content, and an entrypoint that does that to whatever database
# it is pointed at is a footgun in production. Set SEED_ON_START=true to opt in.
set -e

if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
    echo "[entrypoint] applying database migrations"
    python backend/manage.py migrate --noinput
fi

# Only needed when the collected static files are shadowed or absent — the dev
# override mounts the source tree over the image, so it sets this to true.
if [ "${COLLECTSTATIC_ON_START:-false}" = "true" ]; then
    echo "[entrypoint] collecting static files"
    python backend/manage.py collectstatic --noinput
fi

if [ "${SEED_ON_START:-false}" = "true" ]; then
    echo "[entrypoint] seeding sample data (idempotent)"
    python backend/manage.py seed
fi

exec "$@"
