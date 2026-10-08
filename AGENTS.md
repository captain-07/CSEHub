# CSEHub — Agent Guide

## Repo overview

Monorepo: `backend/` (Django 6.0.3 + DRF) and `frontend/` (static vanilla JS + CSS, served on Vercel).
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
- **Auth**: `SupabaseJWTAuthentication` (custom DRF auth) validates Bearer JWTs by fetching signing keys from the Supabase JWKS endpoint (`{SUPABASE_URL}/auth/v1/.well-known/jwks.json`), decoding ES256 with `audience="authenticated"`. `SUPABASE_URL` is the only auth env var — there is no shared JWT secret. Missing `SUPABASE_URL` raises `AuthenticationFailed` per-request, not at import time.
- **DB**: PostgreSQL via `DATABASE_URL` (preferred) or individual `DB_*` vars as fallback. Driver is `psycopg` (v3); `psycopg2-binary` is pinned as a fallback.
- **API docs** (drf-spectacular): `/api/schema/`, `/api/docs/` (Swagger), `/api/redoc/`.

## Apps (under `backend/apps/`)

| App | State | Key notes |
|-----|-------|-----------|
| `articles` | Mature | Full ViewSet CRUD. Admin write, public read. Category/Tag/Article + CodeSnippet models. |
| `chatbot` | Functional | Conversation/Message models, RAG endpoints, `ingest_articles --purge`. See gotchas below. |
| `users` | Functional | Custom User model, Supabase JWKS auth, `MeView` (`GET`/`PATCH /api/auth/me/`). |

The `problems` app (Problem/TestCase/Submission) was **removed** — models dropped via migration, directory deleted.

## Quirks & gotchas

- `.env` lives in `backend/` (not root). Settings reads `BASE_DIR / '.env'`.
- `DEBUG=False` in `.env` by default — set `True` for local dev.
- `backend/.env` contains live credentials — never commit or expose.
- `frontend/` is a real static site (25 files: 5 HTML pages, 13 JS modules, 10 CSS files), served by Vercel. All 5 pages load `css/style.css`; each page's JS is either a module under `frontend/js/` or an inline `<script type="module">`.
- `apps/articles/tests.py`, `apps/users/tests.py`, and `apps/chatbot/tests.py` contain real `APITestCase`/`TestCase` classes. `python manage.py test` requires a reachable Postgres — it hangs at "Creating test database" otherwise.
- Seed command (`python manage.py seed`) is idempotent (`get_or_create`).
- No pre-commit hooks, no linting/formatting config detected.
- No `pyproject.toml`, `setup.py`, `setup.cfg`, or `pytest.ini`.
- **`GEMINI_MODEL` must be a model the key can still call.** Google retires these without warning; a retired id returns `404 NOT_FOUND`, which `answer_question()` turns into a `503 chat_unavailable`, so the frontend shows "The assistant is not configured or is temporarily unavailable" for what is really a config error. Current default is `gemini-3.5-flash-lite`; the whole 2.5 line is retired. When the assistant breaks, check the model first — Pinecone and the embeddings can be fine.
- **Re-ingesting does not clear orphaned vectors.** `ingest_article()` only deletes vectors carrying its own `article_id`, so articles deleted from the database leave vectors behind. Because ids get reused, a filtered similarity search can match an orphan and the assistant answers from the *wrong* article, confidently. Use `manage.py ingest_articles --purge` after deleting or replacing articles; it calls `purge_namespace()` and refuses to be combined with `--slug`.
- `settings.py` uses `STATICFILES_STORAGE`, which Django 6 ignores. To make WhiteNoise's compressed-manifest storage take effect, use a `STORAGES` dict instead.

## Reserved env (needed to run)

`SECRET_KEY`, `SUPABASE_URL`, database connection (either `DATABASE_URL` or `DB_NAME`/`DB_USER`/`DB_PASSWORD`/`DB_HOST`/`DB_PORT`). Optional: `RENDER_EXTERNAL_HOSTNAME` (auto-appends to `ALLOWED_HOSTS`), and `PINECONE_API_KEY`/`PINECONE_INDEX_NAME`/`GEMINI_API_KEY`/`GEMINI_MODEL` for the chatbot RAG.
