#!/usr/bin/env bash
set -o errexit
set -o pipefail
set -o nounset

python -m pip install --upgrade pip

# Fail loudly, and early, if the interpreter cannot satisfy the pinned
# dependencies. Render defaults to Python 3.14 for services created after
# 2026-02-11, and langchain-pinecone==0.2.13 declares <3.14, so without this the
# build dies inside pip with an unhelpful list of "Ignored the following versions
# that require a different python version".
#
# .python-version is what actually pins Render; see the note in that file.
python - <<'PYTHON_VERSION_CHECK'
import sys

if sys.version_info >= (3, 14):
    sys.exit(
        f"FATAL: building on Python {sys.version.split()[0]}, but requirements.txt "
        "caps Python below 3.14 (langchain-pinecone==0.2.13). Check .python-version "
        "at the repo root and Render's PYTHON_VERSION environment variable."
    )
PYTHON_VERSION_CHECK

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
