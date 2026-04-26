#!/usr/bin/env bash
set -o errexit
set -o pipefail
set -o nounset

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

cd backend

python manage.py collectstatic --noinput
python manage.py migrate --noinput
python manage.py seed

# Create superuser only when all required env vars are provided.
if [[ -n "${DJANGO_SUPERUSER_EMAIL:-}" && -n "${DJANGO_SUPERUSER_USERNAME:-}" && -n "${DJANGO_SUPERUSER_PASSWORD:-}" ]]; then
  python manage.py createsuperuser \
    --noinput \
    --email "$DJANGO_SUPERUSER_EMAIL" \
    --username "$DJANGO_SUPERUSER_USERNAME" \
    2>/dev/null || echo "Superuser already exists, skipping."
fi