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
| `articles` | Mature | Full ViewSet CRUD. Admin write, public read. Category/Article/ArticleReaction + CodeSnippet models; every Tag belongs to one Category. |
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
- **`python manage.py test` from the repo root finds 0 tests.** Run it as `python backend/manage.py test apps.articles apps.users apps.chatbot`; bare discovery silently reports success having run nothing.
- **`Article.like_count` / `dislike_count` are denormalized, and only `ArticleReactionManager.set_reaction` may write them.** The counts are stored rather than aggregated because `get_queryset()` ends in `.distinct()`, and Django folds annotations into a `GROUP BY` when `distinct()` is present — a live `Count()` would tax every article listing. The cost is drift if a reaction row is ever created, edited or deleted outside the manager (the admin is the realistic case). Repair with `manage.py recompute_reaction_counts`. Reads are safe everywhere; do not add a second writer.
- **A reader holds at most one reaction per article, enforced by `unique_together` on `ArticleReaction`.** `POST /api/articles/<slug>/react/` is explicit rather than a toggle — the body states the verdict wanted (`like`/`dislike`/`none`) and the response returns `{value, like_count, dislike_count}`. A toggle endpoint would flip twice under a retried request.
- **`react` is in `ArticleViewSet.AUTHENTICATED_ACTIONS`, not `ADMIN_ACTIONS`.** `AdminWriteOrReadAnyMixin.get_permissions` returns `[AllowAny()]` for anything it does not recognise, and the mixin cannot express "signed in but not staff". Adding an authenticated-but-not-admin action therefore requires extending that tuple; a `permission_classes` on the `@action` is silently ignored.
- **On an `@action`, `@extend_schema` must sit *above* `@action`.** With the reverse order the annotation is discarded and drf-spectacular falls back to the detail serializer as the request body, publishing a wrong schema with no warning.
- **A tag belongs to exactly one category; `Tag.name`/`slug` stay globally unique.** `Tag.category` is required and `PROTECT`: reads nest `category` while writes pass `category_id`, and `?category__slug=` narrows `/api/tags/`. `PROTECT` is deliberate — `CASCADE` would silently strip a tag off every article that carries it, so deleting a category with tags is refused and `CategoryViewSet.destroy` turns the resulting `ProtectedError` into a `409` (the Django admin already renders it). Per-category uniqueness was rejected because a bare `?tags__slug=` and the `TagViewSet` pk route would both become ambiguous. The `0006` backfill repeats the seed's sample-tag→category map on purpose — a migration must be frozen.
- **`GEMINI_MODEL` must be a model the key can still call.** Google retires these without warning; a retired id returns `404 NOT_FOUND`, which `answer_question()` turns into a `503 chat_unavailable`, so the frontend shows "The assistant is not configured or is temporarily unavailable" for what is really a config error. Current default is `gemini-3.5-flash-lite`; the whole 2.5 line is retired. When the assistant breaks, check the model first — Pinecone and the embeddings can be fine.
- **The article assistant is deliberately a tutor, not a quote machine.** `rag_chat.SYSTEM_PROMPT` tiers the rules — answer from the article when it covers the point, otherwise say so and give a clearly-labelled general explanation that is never attributed to the article — and `answer_question()` calls the model even when retrieval returns nothing (`NO_ARTICLE_MATCH`), so "what is LL?" on a linked-lists article that never defines the term gets an answer instead of a refusal. Do not restore the old "use ONLY the context" wording: that strictness is what broke exactly that case. Retrieval stays scoped to the article (`filter={"article_id": …}`), and `history` is passed as untrusted continuity, not as a source.
- **Re-ingesting does not clear orphaned vectors.** `ingest_article()` only deletes vectors carrying its own `article_id`, so articles deleted from the database leave vectors behind. Because ids get reused, a filtered similarity search can match an orphan and the assistant answers from the *wrong* article, confidently. Use `manage.py ingest_articles --purge` after deleting or replacing articles; it calls `purge_namespace()` and refuses to be combined with `--slug`.
- `settings.py` uses a `STORAGES` dict, which is the live mechanism in Django 6 (`DEFAULT_FILE_STORAGE`/`STATICFILES_STORAGE` are not set).
- **`ImageUploadView` is the only writer of article images, and it talks exclusively to `default_storage`.** There is no `ImageField` anywhere — `Article.featured_image` and `User.avatar_url` are `URLField`s holding externally-hosted URLs. `backend/apps/articles/media.py` optimises with Pillow (max 1600px, WebP q82) *before* storing; `image_processing.py` owns that pipeline and `image_processing.py` is required (a missing Pillow returns 503, not 500).
- **`USE_REMOTE_STORAGE` is the only storage switch.** When true, article images go to Cloudinary (`apps.articles.storage.CloudinaryArticleStorage`); when false, to the local filesystem. Supabase Storage (S3) was removed — Cloudinary is the sole remote provider, and it fails fast on missing or placeholder credentials at startup.
- **`CLOUDINARY_STORAGE['PREFIX']` defaults to `MEDIA_URL` and fails quietly.** Left unset, every asset lands one folder deeper (under `media/`), so public ids diverge from the `articles/<token>` keys already stored. `settings.py` pins it to `''`.
- **`CloudinaryArticleStorage` (`apps/articles/storage.py`) exists because three `django-cloudinary-storage` defaults are wrong here, and all three break pages rather than raising:** delivery URLs are *signed* by default (`/s--<sha1 of api_secret>--/`, so rotating the API secret invalidates every URL already in published article JSON); public ids must **not** carry a file extension (`a.webp` renders as `a.webp.webp`); and `_save()` returns the *public id*, not the name passed in, so `default_storage.save()` → `default_storage.url()` must round-trip through that id. Do not swap the backend back to `MediaCloudinaryStorage` to "simplify".
- **Cloudinary's Free plan rejects image uploads over 10 MB.** `settings.STORAGE_MAX_UPLOAD_BYTES` carries that ceiling and `media.provider_max_upload_bytes()` clamps the local 20 MB animated-image limit against it, so an accepted upload cannot fail at the provider. Raising it costs money (the next tier is 20 MB) — it is tied to the plan, not assumed.
- **`rewrite_image_urls` only repoints URLs; it does not move bytes.** It is a plain substring replacement over `image` blocks and `Article.featured_image`, so it needs `--to` (without it the replacement is derived from the currently configured storage, which can make the rewrite a silent no-op) and, when moving onto Cloudinary, `--strip-extension` (Cloudinary public ids have no extension, so without it you get doubled `a.webp.webp` URLs that 404).
- **`--from` on `rewrite_image_urls` must include the bucket path, not just the host.** It is a plain substring replacement, so `--from https://example.com` against `https://example.com/storage/v1/object/public/articles/a.webp` leaves `/storage/v1/object/public/articles` glued onto the new base. Pass the full public bucket base.
- `requirements.txt` lists **direct** dependencies only; pip resolves the transitive ones (88 packages total in a clean install). `pip check` passes and the suite runs green against that resolution. `psycopg[binary]` and `PyJWT[crypto]` carry the extras Django's PostgreSQL backend and ES256 verification need.

## Reserved env (needed to run)

`SECRET_KEY`, `SUPABASE_URL`, database connection (either `DATABASE_URL` or `DB_NAME`/`DB_USER`/`DB_PASSWORD`/`DB_HOST`/`DB_PORT`). Optional: `RENDER_EXTERNAL_HOSTNAME` (auto-appends to `ALLOWED_HOSTS`), `CLOUDINARY_CLOUD_NAME`/`CLOUDINARY_API_KEY`/`CLOUDINARY_API_SECRET` when `USE_REMOTE_STORAGE=True`, and `PINECONE_API_KEY`/`PINECONE_INDEX_NAME`/`GEMINI_API_KEY`/`GEMINI_MODEL` for the chatbot RAG.
