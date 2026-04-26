#!/usr/bin/env bash
set -o errexit

pip install -r requirements.txt

cd /backend

python manage.py collectstatic --noinput
python manage.py migrate
python manage.py seed

# create superuser only if it doesn't exist yet
python manage.py createsuperuser \
  --noinput \
  --email "$DJANGO_SUPERUSER_EMAIL" \
  --username "$DJANGO_SUPERUSER_USERNAME" \
  2>/dev/null || echo "Superuser already exists, skipping."