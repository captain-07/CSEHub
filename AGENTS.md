# CSEHub — Agent Guide

## Repo overview

Monorepo: `backend/` (Django 6.0.3 + DRF) and `frontend/` (Vercel placeholder — `.gitkeep` only).
Deployed on Render with Gunicorn + WhiteNoise.

## First-read files

- `backend/.env.example` — all required env vars
- `backend/core/settings.py` — installed apps, auth, REST framework config
- `backend/core/urls.py` — API routing entrypoint
- `requirements.txt`

## Commands (always run from repo root unless noted)

```bash
# Install
pip install -r requirements.txt

# All Django commands need --chdir backend or cd backend
# Dev server
python backend/manage.py runserver

# Migrations
python backend/manage.py makemigrations
python backend/manage.py migrate

# Seed sample data
python backend/manage.py seed

# Tests (Django TestCase, no pytest)
python backend/manage.py test

# Collect static (WhiteNoise)
python backend/manage.py collectstatic --noinput

# Production server
gunicorn core.wsgi:application --chdir backend --bind 0.0.0.0:${PORT:-8000}

# Full build (build.sh)
# Runs: pip install -> collectstatic -> migrate -> seed
```

## Architecture

- **Custom user model**: `apps.users.User` with `email` as `USERNAME_FIELD` (not username), linked via `supabase_uid` to Supabase Auth. `AUTH_USER_MODEL = 'users.User'` is set in settings.
- **Auth**: `SupabaseJWTAuthentication` (custom DRF auth) validates Bearer JWTs against `SUPABASE_JWT_SECRET`. `SUPABASE_JWT_SECRET` + `SUPABASE_URL` are required at import time — settings will crash if missing.
- **DB**: PostgreSQL via `DATABASE_URL` (preferred) or individual `DB_*` vars as fallback.
- **API docs** (drf-spectacular): `/api/schema/`, `/api/docs/` (Swagger), `/api/redoc/`.

## Apps (under `backend/apps/`)

| App | State | Key notes |
|-----|-------|-----------|
| `articles` | Mature | Full ViewSet CRUD. Admin write, public read. Category/Tag/Article + CodeSnippet models. |
| `problems` | Models only | Problem/TestCase/Submission models exist. Views/tests are stubs. |
| `chatbot` | Models only | Conversation/Message models for RAG (Pinecone + Gemini). Views/tests are stubs. |
| `users` | Auth + model | Custom User model, Supabase JWT auth class. Views/tests are stubs. |

## Quirks & gotchas

- `.env` lives in `backend/` (not root). Settings reads `BASE_DIR / '.env'`.
- `DEBUG=False` in `.env` by default — set `True` for local dev.
- `backend/.env` contains live credentials — never commit or expose.
- `frontend/` is a Vercel placeholder — do not assume it has code.
- All test files are empty stubs — tests live outside `tests/` directory per Django default.
- Seed command (`python manage.py seed`) is idempotent (`get_or_create`).
- No pre-commit hooks, no linting/formatting config detected.
- No `pyproject.toml`, `setup.py`, `setup.cfg`, or `pytest.ini`.

## Reserved env (needed to run)

`SECRET_KEY`, `SUPABASE_JWT_SECRET`, `SUPABASE_URL`, database connection (either `DATABASE_URL` or `DB_NAME`/`DB_USER`/`DB_PASSWORD`/`DB_HOST`/`DB_PORT`).
