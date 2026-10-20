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

# Docker (PostgreSQL + Gunicorn + nginx). Needs backend/.env for secrets.
docker compose up --build                                  # dev: mounted source, autoreload, seed
docker compose -f docker-compose.yml up --build             # production-shaped (no override)
docker compose run --rm backend python backend/manage.py test apps.articles
```

## Architecture

- **Custom user model**: `apps.users.User` with `email` as `USERNAME_FIELD` (not username), linked via `supabase_uid` to Supabase Auth. `AUTH_USER_MODEL = 'users.User'` is set in settings.
- **Auth**: `SupabaseJWTAuthentication` (custom DRF auth) validates Bearer JWTs by fetching signing keys from the Supabase JWKS endpoint (`{SUPABASE_URL}/auth/v1/.well-known/jwks.json`), decoding ES256 with `audience="authenticated"`. `SUPABASE_URL` is the only auth env var — there is no shared JWT secret. Missing `SUPABASE_URL` raises `AuthenticationFailed` per-request, not at import time.
- **DB**: PostgreSQL via `DATABASE_URL` (preferred) or individual `DB_*` vars as fallback. Driver is `psycopg` (v3); `psycopg2-binary` is pinned as a fallback.
- **API docs** (drf-spectacular): `/api/schema/`, `/api/docs/` (Swagger), `/api/redoc/`.

## Apps (under `backend/apps/`)

| App | State | Key notes |
|-----|-------|-----------|
| `articles` | Mature | Full ViewSet CRUD. Admin write, public read, plus a public read-count POST. Category/Article/ArticleReaction + CodeSnippet models; every Tag belongs to one Category; an article may carry one optional video URL. |
| `chatbot` | Functional | Conversation/Message models, RAG endpoints, `ingest_articles --purge`. See gotchas below. |
| `users` | Functional | Custom User model, Supabase JWKS auth, `MeView` (`GET`/`PATCH /api/auth/me/`). |

The `problems` app (Problem/TestCase/Submission) was **removed** — models dropped via migration, directory deleted.

## Quirks & gotchas

- `.env` lives in `backend/` (not root). Settings reads `BASE_DIR / '.env'`.
- `DEBUG=False` in `.env` by default — set `True` for local dev.
- `backend/.env` contains live credentials — never commit or expose.
- `frontend/` is a real static site (44 files: 7 HTML pages, 23 JS modules, 10 CSS files), served by Vercel. All 7 pages load `css/style.css`; each page's JS is either a module under `frontend/js/` or an inline `<script type="module">`.
- `apps/articles/tests.py`, `apps/users/tests.py`, and `apps/chatbot/tests.py` contain real `APITestCase`/`TestCase` classes. `python manage.py test` requires a reachable Postgres — it hangs at "Creating test database" otherwise.
- Seed command (`python manage.py seed`) is idempotent (`get_or_create`).
- No pre-commit hooks, no linting/formatting config detected.
- No `pyproject.toml`, `setup.py`, `setup.cfg`, or `pytest.ini`.
- **`python manage.py test` from the repo root finds 0 tests.** Run it as `python backend/manage.py test apps.articles apps.users apps.chatbot`; bare discovery silently reports success having run nothing.
- **`Article.like_count` / `dislike_count` are denormalized, and only `ArticleReactionManager.set_reaction` may write them.** The counts are stored rather than aggregated because `get_queryset()` ends in `.distinct()`, and Django folds annotations into a `GROUP BY` when `distinct()` is present — a live `Count()` would tax every article listing. The cost is drift if a reaction row is ever created, edited or deleted outside the manager (the admin is the realistic case). Repair with `manage.py recompute_reaction_counts`. Reads are safe everywhere; do not add a second writer.
- **A reader holds at most one reaction per article, enforced by `unique_together` on `ArticleReaction`.** `POST /api/articles/<slug>/react/` is explicit rather than a toggle — the body states the verdict wanted (`like`/`dislike`/`none`) and the response returns `{value, like_count, dislike_count}`. A toggle endpoint would flip twice under a retried request.
- **`react` is in `ArticleViewSet.AUTHENTICATED_ACTIONS`, not `ADMIN_ACTIONS`.** `AdminWriteOrReadAnyMixin.get_permissions` returns `[AllowAny()]` for anything it does not recognise, and the mixin cannot express "signed in but not staff". Adding an authenticated-but-not-admin action therefore requires extending that tuple; a `permission_classes` on the `@action` is silently ignored.
- **`Article.view_count` has exactly one writer: `Article.record_view()`.** It is denormalized for the same reason as the reaction tallies (the listing ends in `.distinct()`), but it is the one counter with **no repair hatch**: nothing stores a row per view, so there is no equivalent of `recompute_reaction_counts` and the field is read-only in the Django admin. The increment uses `F()` through `QuerySet.update()`, so it is race-free *and* leaves `auto_now`'s `updated_at` alone — a read must not make an article look freshly edited.
- **`POST /api/articles/<slug>/view/` counts every request; deduplication lives in the client.** The server has no per-view rows to deduplicate against, so `recordViewOnce()` in `article.js` guards on a `sessionStorage` key per slug and re-arms it when the request fails. Do not move the guard server-side without first adding a table to hold the rows. It is deliberately **not** a side effect of `GET` on the detail route (that route also serves the admin editor), and signed-in staff are answered with the current total but never counted.
- **The `view` action is deliberately absent from `AUTHENTICATED_ACTIONS`.** Anonymous readers are the entire point of a view count, and the mixin already returns `AllowAny` for actions it does not recognise — so adding it there would be the bug, not the fix.
- **`Article.video_url` is one optional link per article, stored as a plain `URLField`.** It renders at the end of the article body, above the reactions block. It is an article-level field rather than an Editor.js block on purpose: there is one per article, and a block type would have to be added to `SUPPORTED_BLOCK_TYPES`, mirrored in the frontend tool registry, rendered by the renderer and handled by the RAG ingestion — four places, for a field an editor usually leaves blank.
- **The reader never frames the stored video URL.** `videoEmbed()` in `renderer.js` matches the hostname *exactly* against an allow-list (YouTube, Vimeo, + `youtube-nocookie`), reads a video id out of the URL, and rebuilds the embed source from that id; anything else renders as a link card, and a value that is not an absolute http(s) URL renders as nothing. That derivation is the entire security property of the feature and `node .check-video-embed.mjs` pins it — do not "simplify" it by putting the pasted string into an iframe `src`. The player is embedded directly rather than behind a click-to-load facade, so a provider's scripts and cookies load with the article; that is the accepted price of the reader not having to press anything, and it is why the allow-list and the id derivation have to stay.
- **The frontend has no test runner; its invariants live in root-level `node .check-*.mjs` scripts.** `.check-imports.mjs` (every imported name is exported), `.check-assets.mjs` (every statically-declared class has a CSS rule, every local asset named by a page *or a module* exists, **and** every class a page can render is defined by a stylesheet *that page loads*), `.check-editor-tools.mjs` (the editor tool registry matches `SUPPORTED_BLOCK_TYPES`), `.check-video-embed.mjs` (the video allow-list) and `.check-chat-markup.mjs` (the assistant's markdown subset — it renders, and a reply can never inject markup). They are dependency-free and run from the repo root, and they report failures through the exit code (so `node .check-assets.mjs && …` is a real gate); note that a new frontend class with no CSS rule fails `.check-assets.mjs`. `.check-chat-markup.mjs` stubs `window.location.origin` before importing `renderer.js`, because `safeUrl()` resolves against it and Node has no `window`.
- **`.check-assets.mjs`'s per-page rule only inspects the page's own HTML plus the modules reachable from *that page alone*.** A shared module (`renderer.js`, `theme.js`) carries markup for several pages at once, so requiring every page that loads it to style all of its output would demand `articles.css` on `login.html`. Shared modules stay covered by the global "has a rule somewhere" check. It also counts a class as styled only when its rule sets something other than `transition` — `body, .empty-state, .snippet { transition: … }` in `style.css` is not a definition, and treating it as one is exactly how `article.html` once shipped with `.empty-state` unstyled.
- **An article card renders the same three bands whether or not it has a cover: media strip, meta line, footer.** The strip holds the article image when there is one and otherwise carries the subject as a decorative ghosted word (`.article-card-media-empty`); a card that skips the strip starts its text higher than its neighbours and the row stops being flush. The like/view tallies sit in `.card-foot` beside the read link, not in the meta line — reads in the meta line pushed it past the width of a three-column card and it wrapped to a line holding nothing but a lone tally. Covers render whole on a mat (`contain`) because every one of them is a diagram with labels running to the edge, and `.skeleton-media` mirrors the strip's height so the loading state does not jump. `.check-assets.mjs` is what catches a band losing its rule.
- **`friendlyError()` in `api.js` is the only place a failure becomes a sentence.** Every page renders errors through it (admin, article, library, home, categories, profile), and `chat.js` delegates every status it has no assistant-specific wording for. A page-local status→copy map drifts, and the raw alternative is "API request failed with status 500", which names the transport instead of the problem; DRF field errors still win because they name the actual field. `apiFetch` additionally abandons a request after 20 s (`options.timeout` overrides it; image uploads pass 120 s), so no page can spin forever — the `AbortError` branch can only ever mean that timeout, because no caller passes its own signal.
- **A failed region renders `messageStateMarkup({ retry: true })` and binds `[data-retry]` to the loader it already has.** Retry rather than a link elsewhere: sending the reader to another page does not bring the missing articles back, and the library page already worked this way. The block also spans the full row inside `.article-grid`/`.category-grid` — left as one grid item it was ~300px wide, so "Unable to load articles" wrapped over three lines while two empty columns stood beside it.
- **The chat drawer locks the page behind it and measures the viewport, not `100vh`.** `body.chat-open` (set by `setDrawerOpen`) stops a touch scroll from dragging the article under the conversation, `height: 100dvh` keeps Send above a phone's URL bar, and the overlay uses `inset: 0` because `100vw` includes the desktop scrollbar. Tap targets on the way in and out — hamburger, chat close, toast close, nav links, tag and filter chips — are sized on the control, not left to the glyph.
- **`logo.svg` and `favicon.svg` are edited traces, not exports.** Both are VTracer output with the source raster's baked white plate removed (on the dark header it rendered as an opaque white slab) and a `viewBox` added so CSS height scales them; the favicon's viewBox is cropped to the badge, which otherwise sat in a ~9%-per-side margin. The wordmark is traced in near-black, so `navbar.css` lifts it with `filter: invert(1) hue-rotate(180deg)` under `[data-theme='dark']` instead of shipping a second file — remove either half of that pair and the logo is either a white box or an unreadable one. Its `alt` is the brand text, and the `<img>` carries `width`/`height` so the header does not shift.
- **Dark mode flips the fills, so a label sitting *on* `--accent`/`--error` needs its own token.** `--accent` is a dark green in light mode and a light green in dark, so a hardcoded `white` label (or one inheriting `--text-primary`) is legible in exactly one theme. Use `--on-accent`/`--on-error`, and note the Google button persists as white in both themes so its label uses `--google-btn-text` rather than `--text-primary`. `.check-contrast.mjs` reads both palettes out of `style.css`, composites translucent values over their real surface, and fails if any declared pair drops below 4.5:1 — the whole reason it exists is that this defect is invisible to every other check.
- **Editor.js's light theme is re-pointed, not restyled element by element.** Its stylesheet declares its palette as custom properties on `:root`, on `.ce-popover` and on `.ce-inline-toolbar`; because a declaration on the element itself beats an inherited value, the dark overrides in `admin.css` must be scoped to at least the same selector (`:root[data-theme='dark'] .ce-popover`), not just set on `:root`. The handful of colours it hardcodes (the toolbar `+`/settings buttons, `.cdx-button`, `.cdx-search-field`, the three tool placeholders) get an explicit override.
- **The admin editor marks its required fields with a red `*`, and the save path is what enforces them.** `Title` and `Content` are the two an article cannot ship without, so `.field-required` sits on those labels and `saveArticle()` refuses the save when either is blank. The mark is not decorative: the form is `novalidate`, so the title input's own `required` attribute never speaks, and a `*` with no check behind it would be a lie. The body check asks `documentHasBody()`: text is measured with the shared `contentToPlainText()`, so the rule cannot drift from the excerpt builder, and an image block is counted on top of it because that helper flattens a document to its text and a picture has none (its URL sits under `file.url`, as `renderImageBlock` reads it). A bare `blocks.length` test would accept an empty paragraph. The glyph is `aria-hidden` — the title input's `required` supplies the audible meaning, and the Content label, which owns no control, carries an `.sr-only` "required" instead. There is no `optional` chip to counteract it: unmarked now means optional.
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
- **The backend image is `python:3.12-slim`, pinned to match `.python-version`; do not move it to `latest`.** Django 6 runs fine on 3.13/3.14, but `langchain-pinecone==0.2.13` declares `<3.14` — the same cap `build.sh` asserts for Render. `psycopg[binary]`, Pillow and cryptography ship manylinux wheels, so the image needs no compiler or `libpq-dev`; a future dependency that only ships an sdist means adding a build stage, not adding `apt` packages to this one.
- **`settings.py` cannot be imported without a database URL**, so the `Dockerfile` passes a throwaway `DATABASE_URL=postgresql://build:build@localhost:5432/build` to `collectstatic`. Nothing connects during collectstatic, but removing that line fails the *build* with `ImproperlyConfigured: Set the DB_NAME environment variable`, not the runtime.
- **A bare `docker compose up` is the development stack.** `docker-compose.override.yml` is merged automatically (bind-mounted `backend/`, `runserver`, `SEED_ON_START=true`), so a server must use `-f docker-compose.yml` or it silently gets autoreload and seeded sample data. The bind mount also hides the static files collected into the image, which is why the override sets `COLLECTSTATIC_ON_START=true`: without a manifest, `ManifestStaticFilesStorage` raises `Missing staticfiles manifest entry` on every admin page.
- **`docker/docker-entrypoint.sh` migrates but never seeds unless asked** (`SEED_ON_START=true`), and `.dockerignore` excludes `backend/.env`, so secrets reach the container only through `env_file`/the platform environment and never sit in a layer. The Dockerfile strips CR from that script (`sed -i 's/\r$//'`) because a CRLF checkout on Windows would otherwise break the `#!/bin/sh` shebang under Linux.

## Reserved env (needed to run)

`SECRET_KEY`, `SUPABASE_URL`, database connection (either `DATABASE_URL` or `DB_NAME`/`DB_USER`/`DB_PASSWORD`/`DB_HOST`/`DB_PORT`). Optional: `RENDER_EXTERNAL_HOSTNAME` (auto-appends to `ALLOWED_HOSTS`), `CLOUDINARY_CLOUD_NAME`/`CLOUDINARY_API_KEY`/`CLOUDINARY_API_SECRET` when `USE_REMOTE_STORAGE=True`, and `PINECONE_API_KEY`/`PINECONE_INDEX_NAME`/`GEMINI_API_KEY`/`GEMINI_MODEL` for the chatbot RAG.
