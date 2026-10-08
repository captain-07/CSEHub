# CSEHub

CSEHub is a computer science learning platform: a Django REST API plus a static frontend. It serves educational articles with code snippets, a per-article RAG chatbot, and Supabase-backed user accounts.

![Python](https://img.shields.io/badge/python-3.11+-blue?logo=python)
![Django](https://img.shields.io/badge/django-6.0.3-092E20?logo=django)
![DRF](https://img.shields.io/badge/djangorestframework-3.16.0-red?logo=django)
![License](https://img.shields.io/badge/license-MIT-green)
![Render](https://img.shields.io/badge/deployed%20on-Render-46E3B7?logo=render)

---



## Table of Contents

- [Features](#features)
- [Tech Stack](#tech-stack)
- [Getting Started](#getting-started)
  - [Prerequisites](#prerequisites)
  - [Installation](#installation)
  - [Environment Variables](#environment-variables)
- [Usage](#usage)
  - [Development Server](#development-server)
  - [Frontend](#frontend)
  - [API Documentation](#api-documentation)
  - [Database Migrations](#database-migrations)
  - [Seeding Data](#seeding-data)
  - [Article Ingestion](#article-ingestion)
  - [Running Tests](#running-tests)
- [Project Structure](#project-structure)
  - [Frontend architecture](#frontend-architecture)
- [API Endpoints](#api-endpoints)
- [Authentication setup (Google only)](#authentication-setup-google-only)
- [Article authoring flow](#article-authoring-flow)
- [Deployment](#deployment)
- [Contributing](#contributing)
- [License](#license)

---



## Features

### Public site

- **Article library** — Browse, search, filter by category and tag, sort, and paginate published articles
- **Long-form reading view** — Sanitized Editor.js rendering with copyable code blocks, images, and related articles
- **Category browser** — Subject index with live article counts, plus a tag cloud
- **AI article assistant** — Authenticated RAG chatbot (Pinecone + Gemini) scoped to a single article, with persisted conversation history
- **Supabase Google OAuth** — "Continue with Google" sign-in; the API auto-provisions a local `User` from a valid Bearer token
- **User profile** — `GET`/`PATCH /api/me/` for display name, username, and avatar
- **Static frontend** — HTML/CSS/JS client deployed on Vercel

### Admin panel

- **Server-enforced publishing** — Every write is gated on Django's `is_staff`; the frontend's `is_admin` mirrors it and is read-only
- **Admin guard** — `/admin` is a UX gate only; a non-editor calling `POST /api/articles/` directly still gets a `403`
- **Editor.js authoring** — Heading, paragraph, list, quote, code, image, link, and delimiter blocks stored as structured JSON
- **Dashboard and article list** — Real counts (published / drafts / total), search, status filter, and pagination
- **Taxonomy management** — Create and delete categories and tags
- **Preview before publishing** — Renders the unsaved document through the same renderer the public page uses
- **Explicit RAG indexing** — Publishing never blocks on an embedding call; admins trigger it, or run `manage.py ingest_articles`

---



## Tech Stack


| Layer              | Technology                                       |
| ------------------ | ------------------------------------------------ |
| **Backend**        | Django 6.0.3 + Django REST Framework 3.16.0      |
| **Database**       | PostgreSQL (via `DATABASE_URL` or `DB_`* vars)   |
| **Authentication** | Supabase Auth (Google OAuth, ES256 JWT via JWKS) |
| **Editor**         | Editor.js (heading, list, quote, code, image, link, delimiter) |
| **API Docs**       | drf-spectacular (OpenAPI 3.0, Swagger, ReDoc)    |
| **RAG Pipeline**   | LangChain + Pinecone (vector DB) + Google Gemini |
| **Backend deploy** | Render (Gunicorn + WhiteNoise)                   |
| **Frontend**       | Static HTML, CSS, and ES modules on Vercel       |


---



## Getting Started



### Prerequisites

- Python 3.12 (pinned for Render in `runtime.txt`)
- PostgreSQL (local or remote)
- Supabase project (JWT auth)
- Pinecone index and Google Gemini API key (required only for ingestion and chatbot use)



### Installation

```bash
# Clone the repository
git clone https://github.com/captain-07/CSEHub.git
cd CSEHub

# Create and activate a virtual environment
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Copy env file and fill in values (see below)
cp backend/.env.example backend/.env

# Run database migrations
python backend/manage.py migrate

# Seed sample data
python backend/manage.py seed

# Start the development server
python backend/manage.py runserver
```



### Environment Variables

Copy `backend/.env.example` to `backend/.env` and fill in the values:

```bash
cp backend/.env.example backend/.env
```


| Variable                                                  | Required | Description                                                                                                                                    |
| --------------------------------------------------------- | -------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| `SECRET_KEY`                                              | Yes      | Django secret key (generate with `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"`) |
| `DEBUG`                                                   | No       | Set to `True` for local development (default: `False`)                                                                                         |
| `ALLOWED_HOSTS`                                           | No       | Comma-separated hosts (default: `127.0.0.1,localhost`)                                                                                         |
| `DATABASE_URL`                                            | Yes*     | PostgreSQL connection string (preferred over individual `DB_`* vars)                                                                           |
| `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` | Yes*     | Fallback database variables when `DATABASE_URL` is not set                                                                                     |
| `SUPABASE_URL`                                            | Auth only | Supabase project URL; ES256 tokens are verified through its public JWKS endpoint                                                              |
| `API_PUBLIC_BASE_URL`                                     | No       | Public origin to prefix uploaded image URLs with, if it differs from the request host. Local filesystem storage only |
| `USE_REMOTE_STORAGE`                                      | No       | `True` to store article images in Supabase Storage instead of the local filesystem (default: `False`)                |
| `SUPABASE_PROJECT_REF`                                    | Storage  | Project ref, e.g. `abcdefghijklm`. Required when `USE_REMOTE_STORAGE=True`                                          |
| `SUPABASE_STORAGE_BUCKET`                                 | No       | Public bucket name (default: `articles`)                                                                             |
| `SUPABASE_S3_ENDPOINT_URL`                                | No       | Defaults to `https://<ref>.storage.supabase.co/storage/v1/s3`                                                          |
| `SUPABASE_S3_ACCESS_KEY_ID` / `SUPABASE_S3_SECRET_ACCESS_KEY` | Storage | S3 protocol keys from **Storage → S3 Settings**. Not the service-role key. Bypass RLS — server-side only     |
| `SUPABASE_S3_REGION`                                      | No       | Defaults to the project ref                                                                                           |
| `IMAGE_MAX_DIMENSION`                                     | No       | Long-edge cap for uploaded images (default: `1600`)                                                                  |
| `IMAGE_WEBP_QUALITY` / `IMAGE_WEBP_METHOD`                | No       | WebP encoder settings (defaults: `82`, `6`)                                                                           |
| `PINECONE_API_KEY`                                        | RAG only | Pinecone API key; server secret                                                                                                                |
| `PINECONE_INDEX_NAME`                                     | RAG only | Pinecone index used for article embeddings                                                                                                     |
| `GEMINI_API_KEY`                                          | RAG only | Google Gemini API key; server secret                                                                                                           |
| `GEMINI_MODEL`                                            | No       | Chat model (default: `gemini-2.5-flash-lite`)                                                                                                 |
| `CORS_ALLOWED_ORIGINS`                                    | No       | Comma-separated frontend origins (default: `http://localhost:3000`)                                                                            |
| `CSRF_TRUSTED_ORIGINS`                                    | No       | Comma-separated CSRF trusted origins (default: `http://localhost:3000`)                                                                        |
| `DJANGO_SUPERUSER_*`                                      | No       | Auto-create superuser during `build.sh`                                                                                                        |


*Either* `DATABASE_URL` *or the individual* `DB_`* *variables must be provided.*

> **Note:** The `.env` file lives in `backend/`, not the project root. The settings module reads `backend/.env` at import time. Do not commit `backend/.env`.

---



## Usage



### Development Server

```bash
# From the project root
python backend/manage.py runserver
# Or from the backend directory
cd backend && python manage.py runserver
```



### Frontend

The frontend is a dependency-free static site. Configure its public deployment values before its module scripts load; never put backend secrets there.

```powershell
python -m http.server 3000 --directory frontend
```

Then open `http://localhost:3000`. Run Django separately on port 8000.

For local development, inject these public values before each page's module script:

```html
<script>
  window.CSEHUB_API_BASE_URL = "http://localhost:8000";
  window.CSEHUB_SUPABASE_URL = "https://your-project.supabase.co";
  window.CSEHUB_SUPABASE_ANON_KEY = "your-publishable-anon-key";
</script>
```

The frontend origin must be listed in the backend's `CORS_ALLOWED_ORIGINS`.

Pages:


| File              | Route (with `cleanUrls`) | Description                                        |
| ----------------- | ------------------------ | -------------------------------------------------- |
| `index.html`      | `/`                      | Home: featured, recent, categories                 |
| `articles.html`   | `/articles`              | Library with search, filters, and pagination        |
| `article.html`    | `/article?id=<id>`       | Long-form reader + learning assistant               |
| `categories.html` | `/categories`            | Subject index and tag cloud                         |
| `login.html`      | `/login`                 | Google sign-in (`?redirect=` returns you to target)|
| `profile.html`    | `/profile`               | Profile editor and sign-out                         |
| `admin.html`      | `/admin`                 | Editor-only publishing panel (hash-routed)          |

Admin panel views (`admin.html`):

| Hash                  | View                                       |
| --------------------- | ------------------------------------------ |
| `#/`                  | Dashboard: counts and recent articles      |
| `#/articles`          | Article list with search and status filter |
| `#/articles/new`      | Create an article                          |
| `#/articles/:id/edit` | Edit an existing article                   |
| `#/taxonomy`          | Categories and tags                        |




### API Documentation

Once the server is running, navigate to:

- **OpenAPI Schema** — `http://localhost:8000/api/schema/`
- **Swagger UI** — `http://localhost:8000/api/docs/`
- **ReDoc** — `http://localhost:8000/api/redoc/`



### Database Migrations

```bash
# Create migrations for model changes
python backend/manage.py makemigrations

# Apply pending migrations
python backend/manage.py migrate
```



### Seeding Data

The seed command creates sample categories, tags, and articles:

```bash
python backend/manage.py seed
```

This command is idempotent (`get_or_create`) and safe to run multiple times.

### Article Ingestion

Published articles are chunked, embedded with Gemini, and stored in Pinecone (namespace `articles`) by an explicit command. Article saves never call external providers, so editorial work remains available while a provider is down. The command replaces existing deterministic vector IDs and is safe to re-run.

```bash
python backend/manage.py ingest_articles

# Re-index a single article (idempotent)
python backend/manage.py ingest_articles --slug two-sum-explained
```

Admins can also index one article from the editor via **Update AI index**, which calls `POST /api/articles/{id}/reindex/`. Drafts are refused (`409`) — publish first.

Before embedding, `article_content_to_text()` flattens the Editor.js document into readable prose: headings become `Heading: …`, code blocks become `Code (python): …`, list items become `- …`, and inline markup is stripped. The vector store therefore receives meaningful text rather than JSON syntax.

`build.sh` does **not** run ingestion: it needs Pinecone and Gemini credentials, and a build must not fail because an optional provider is unreachable. Run it manually after setting the RAG variables.

### Running Tests

```bash
# Run all tests
python backend/manage.py test
```

Tests use Django's built-in `TestCase` / `APITestCase` (no pytest) and require a reachable PostgreSQL — the runner creates `test_<db_name>`. If a previous run left that database behind, use `--keepdb`:

```bash
python backend/manage.py test --keepdb
```

What the suite covers:

- **Articles** — public/staff visibility, admin-only writes, slug derivation and deduplication, Editor.js content validation (including every supported block type), category and tag permissions, pagination, `is_featured` filtering, `reindex` authorization, and image-upload permissions and file-type handling.
- **Users** — Supabase JWT creation and synchronisation, safe rejection of malformed tokens, `/api/me/` reporting `is_admin`, and proof that a client cannot grant itself staff or change its own email.
- **Chatbot** — authentication requirements, conversation persistence and isolation, draft-article `404`, `503`/`502` on provider failure (with no fabricated reply), response-shape normalisation, and Editor.js → readable-text conversion for the vector store.

---



## Project Structure

```
CSEHub/
├── backend/
│   ├── apps/
│   │   ├── articles/              # Article CRUD, taxonomy, image uploads
│   │   │   ├── management/commands/seed.py
│   │   │   ├── media.py           # Admin-only image upload endpoint
│   │   │   ├── models.py          # Category, Tag, Article, CodeSnippet
│   │   │   ├── serializers.py
│   │   │   ├── urls.py
│   │   │   └── views.py           # Public read, IsAdminUser writes
│   │   ├── chatbot/               # RAG chatbot
│   │   │   ├── management/commands/ingest_articles.py
│   │   │   ├── ingestion.py       # Editor.js JSON -> text -> Pinecone
│   │   │   ├── rag_chat.py        # Gemini grounded answers
│   │   │   ├── models.py          # Conversation, Message
│   │   │   ├── urls.py
│   │   │   └── views.py
│   │   └── users/                 # Custom user + JWT auth
│   │       ├── authentication.py  # SupabaseJWTAuthentication
│   │       ├── models.py
│   │       ├── serializers.py
│   │       ├── urls.py
│   │       └── views.py           # GET/PATCH /api/me/
│   ├── core/
│   │   ├── settings.py
│   │   ├── urls.py
│   │   ├── wsgi.py
│   │   └── asgi.py
│   ├── media/                     # Uploaded article images (gitignored)
│   ├── .env.example
│   └── manage.py
├── frontend/                      # Static Vercel client
│   ├── index.html                 # Home
│   ├── articles.html              # Library: search, filters, pagination
│   ├── article.html               # Reader + learning assistant
│   ├── categories.html            # Subject index + tag cloud
│   ├── login.html                 # Google sign-in
│   ├── profile.html               # Profile editor
│   ├── admin.html                 # Editor-only publishing panel
│   ├── css/                       # design-system tokens + per-page styles
│   ├── js/
│   │   ├── config.js              # API base URL + Supabase public config
│   │   ├── api.js                 # the single HTTP client
│   │   ├── api/articles.js        # endpoint bindings
│   │   ├── supabase.js            # Supabase client + session access
│   │   ├── auth.js                # Google OAuth, logout, safe redirects
│   │   ├── auth-state.js          # single source of auth truth (incl. is_admin)
│   │   ├── renderer.js            # Editor.js -> sanitized HTML
│   │   ├── navbar.js              # shared header, admin link from is_admin
│   │   ├── home.js / articles.js / article.js / categories.js
│   │   ├── login.js / profile.js / chat.js
│   │   └── admin.js               # hash-routed publishing panel
│   └── vercel.json
├── build.sh                       # Production build script
├── Procfile                       # Render process declaration
└── requirements.txt
```

### Frontend architecture

One implementation per concern — there is no second router, API client, or article renderer:

| Concern          | Single source of truth                          |
| ---------------- | ----------------------------------------------- |
| HTTP             | `js/api.js` — attaches the Supabase Bearer token, normalises errors |
| Endpoints        | `js/api/articles.js`                            |
| Auth state       | `js/auth-state.js` — `loading` / `authenticated` / `anonymous` |
| Admin status     | `GET /api/me/` → `is_admin` (read-only, server-controlled) |
| OAuth            | `js/auth.js` → `signInWithOAuth({ provider: 'google' })` |
| Rendering        | `js/renderer.js` — escapes all text, allow-lists inline tags |
| Admin routing    | Hash routes in `js/admin.js`                    |

### App maturity


| App        | Status      | Description                                                  |
| ---------- | ----------- | ------------------------------------------------------------ |
| `articles` | Mature      | Full CRUD API, taxonomy, uploads, admin, public read / admin write |
| `chatbot`  | Implemented | Ask + conversation APIs, ingestion, RAG pipeline             |
| `users`    | Functional  | Supabase JWT auth, user sync, `/api/me/` profile            |


---



## API Endpoints


| Method          | Endpoint                             | Description                                 | Auth          |
| --------------- | ------------------------------------ | ------------------------------------------- | ------------- |
| Method          | Endpoint                             | Description                                            | Auth          |
| --------------- | ------------------------------------ | ------------------------------------------------------ | ------------- |
| `GET`           | `/api/articles/`                     | List articles (paginated)                              | Public        |
| `GET`           | `/api/articles/{id}/`                | Article detail: content, tags, snippets, author        | Public        |
| `POST`          | `/api/articles/`                     | Create article                                          | Admin         |
| `PUT` / `PATCH` | `/api/articles/{id}/`                | Update article                                          | Admin         |
| `DELETE`        | `/api/articles/{id}/`                | Delete article                                          | Admin         |
| `POST`          | `/api/articles/{id}/reindex/`        | Send a published article's text to Pinecone (RAG)       | Admin         |
| `GET`           | `/api/categories/`                   | List categories                                         | Public        |
| `POST` / `PUT` / `PATCH` / `DELETE` | `/api/categories/{id}/` | Create / update / delete a category       | Admin         |
| `GET`           | `/api/tags/`                         | List tags                                               | Public        |
| `POST` / `PUT` / `PATCH` / `DELETE` | `/api/tags/{id}/`    | Create / update / delete a tag           | Admin         |
| `POST`          | `/api/uploads/images/`               | Upload an image for an Editor.js image block            | Admin         |
| `GET`           | `/api/me/`                           | Current user profile (includes `is_admin`)             | Authenticated |
| `PATCH`         | `/api/me/`                           | Update display name, username, or avatar                | Authenticated |
| `POST`          | `/api/articles/{slug}/ask/`          | Ask a question about an article (RAG)                   | Authenticated |
| `GET`           | `/api/articles/{slug}/conversation/` | Load the user's conversation for an article             | Authenticated |
| `GET`           | `/media/<path>`                      | Serve an uploaded article image                         | Public        |
| `GET`           | `/api/docs/`                         | Swagger UI                                              | Public        |
| `GET`           | `/api/redoc/`                        | ReDoc UI                                                | Public        |
| `GET`           | `/api/schema/`                       | OpenAPI schema (JSON)                                   | Public        |
| —               | `/admin/`                            | Django admin                                            | Staff         |

> **Note on `ask/`** — the RAG endpoint takes `{ "question": "..." }` and returns the whole conversation, the same shape as `conversation/`, so a client needs one parser. A provider outage returns `503` (`code: "chat_unavailable"`); an unexpected fault returns `502`. Neither stores a fabricated assistant reply.

### Query parameters — `GET /api/articles/`

| Parameter                | Example                | Notes                                        |
| ------------------------ | ---------------------- | -------------------------------------------- |
| `search`                 | `search=graph`         | Matches `title` or `excerpt`                 |
| `category__slug`         | `category__slug=dsa`   | Exact category slug                          |
| `tags__slug`             | `tags__slug=array`     | Exact tag slug                               |
| `is_featured`            | `is_featured=true`     | `true` / `false`                             |
| `ordering`               | `ordering=-created_at` | `-created_at`, `created_at`, `title`, `-title` |
| `page`                   | `page=2`               | Page-number pagination, 20 per page          |

### Pagination envelope

```json
{
  "count": 42,
  "next": "http://host/api/articles/?page=2",
  "previous": null,
  "results": [ /* ... */ ]
}
```

`next` / `previous` are absolute URLs. The frontend follows them directly and will not produce an `/api/api/...` path.

### Error shapes

| Status | Meaning                                                            |
| ------ | ------------------------------------------------------------------ |
| `400`  | Validation failed — `{"slug": ["A slug or a title is required."]}`  |
| `401`  | Missing, expired, or invalid Supabase token                         |
| `403`  | Authenticated but not an editor (`is_staff` is `False`)             |
| `404`  | Not found, or hidden because it is an unpublished draft             |
| `409`  | Action conflicts with current state (e.g. indexing a draft)         |
| `413`  | Uploaded image exceeds 5 MB                                         |
| `415`  | Uploaded file is not a supported image type                         |
| `502` / `503` | RAG provider failure                                    |

### Article content schema

`content` is a `JSONField` holding an Editor.js document:

```json
{
  "time": 1730000000000,
  "version": "2.30.8",
  "blocks": [
    { "type": "header",    "data": { "text": "Binary Search", "level": 2 } },
    { "type": "paragraph", "data": { "text": "It halves the search space…" } },
    { "type": "code",      "data": { "code": "def search(a, t):", "language": "python" } }
  ]
}
```

Allowed block types are declared once in `SUPPORTED_BLOCK_TYPES`
(`backend/apps/articles/models.py`) and enforced by the serializer: `paragraph`,
`header`, `list`, `quote`, `code`, `image`, `delimiter`, `linkTool`. A document
outside that set is rejected with a `400` rather than stored.

**Auth header** — Send `Authorization: Bearer <supabase-access-token>`. A valid JWT creates or updates the matching `users.User` row (`supabase_uid` + email), including display name and avatar from `user_metadata`.

**Authorization** — `is_admin` on `GET /api/me/` is a read-only projection of Django's `is_staff`. It is the *only* thing the frontend uses to decide whether to show the Admin link, and it cannot be written by a client. The API separately enforces `IsAdminUser` on every write, so hiding the UI is never the actual control.

---

## Authentication setup (Google only)

CSEHub exposes a single sign-in method: **Continue with Google**, via Supabase Auth.

### Supabase dashboard

1. **Authentication → Sign In / Providers → Google**
   - Enable the Google provider.
   - Supabase supplies the Google client ID and secret — no Google Cloud project is needed.
2. **Authentication → URL Configuration → Redirect URLs** — add every origin the frontend is served from, e.g.
   - `https://<your-vercel-domain>/`
   - `http://localhost:3000/`
   The OAuth callback always lands on the site's `index.html`; the originally requested page is carried across the round trip in `sessionStorage`.
3. **Project Settings → API** — copy the project URL and the **publishable** (`sb_publishable_…`) or legacy `anon` key into `frontend/js/config.js`.

> The service-role key and the JWT secret are **never** needed by the frontend, and must never appear in it. The backend verifies tokens by fetching Supabase's public JWKS, so `SUPABASE_URL` alone is enough server-side.

### Making an account an editor

A Google sign-in creates a plain reader. To grant publishing rights, promote the account server-side:

```bash
python backend/manage.py shell
>>> from django.contrib.auth import get_user_model
>>> get_user_model().objects.filter(email="you@example.com").update(is_staff=True)
```

or via the Django admin at `/admin/`. There is no frontend path to this flag, by design.

---

## Article authoring flow

```
Admin opens #/articles/new
        ↓
Editor.js composes blocks (code, image, list, quote…)
        ↓
Image blocks upload to /api/uploads/images/ (admin-only; PNG/JPEG/GIF/WebP/AVIF)
        ↓
Server optimises: downscale to 1600px, re-encode WebP, strip EXIF, keep animation
        ↓
Saved to the configured storage backend, and the absolute URL is returned
        ↓
Save → serializer validates the document against SUPPORTED_BLOCK_TYPES
        ↓
JSON stored in articles.content (JSONField)
        ↓
Published → admin clicks "Update AI index", or runs manage.py ingest_articles
        ↓
article_content_to_text() flattens blocks to readable prose
        ↓
Gemini embeddings → Pinecone (namespace "articles", deterministic IDs)
        ↓
The learning assistant retrieves chunks scoped to that article
```

Images go through the API rather than being inlined as base64: the document is stored verbatim and also fed to the RAG pipeline, so embedding binary payloads would bloat both. The browser never receives a storage credential.

### Image optimisation

Every upload is normalised before storage, because the reading column is ~800px wide — serving a 4000px phone screenshot straight to a reader wastes most of the payload. A typical 3000×2000 screenshot drops from ~226 KB to ~9 KB.

| Behaviour | Detail |
| --- | --- |
| Downscale | Long edge capped at 1600px (2× the column). Never upscales. |
| Format | WebP `quality=82`. PNG is kept when the source is transparent and WebP is not meaningfully smaller, so flat diagrams with hard edges stay sharp. |
| Metadata | EXIF stripped — it carries GPS and camera serials and is dead weight. |
| Animation | Preserved. Animated GIFs are re-encoded frame by frame to animated WebP, and the original GIF is kept if that would be *larger* (GIF is very good at flat colour, so this happens). |
| Source limit | 10 MB (20 MB for animated). The limit applies to the **optimised** output, so a 15 MB screenshot that becomes 200 KB is accepted. |
| Failure | A corrupt or undecodable image is stored unchanged rather than rejected — an optimisation failure must never block publishing. |

Tunable via `IMAGE_MAX_DIMENSION`, `IMAGE_WEBP_QUALITY`, `IMAGE_WEBP_METHOD` in `backend/.env`.

> **Keep local and production on different settings.** Leave `USE_REMOTE_STORAGE=False` in `backend/.env` for development — uploads go to `backend/media/` and need no credentials — and set the Supabase variables in **Render's environment dashboard** instead. That keeps local work independent of bucket availability, and means a `backend/.env` can be shared without leaking production credentials.
>
> If you do enable it locally, Django now refuses to start on a placeholder project ref or missing S3 keys rather than silently generating URLs that 404.

### Image storage

`default_storage` is the only thing that knows where files live, so the provider is a settings choice:

| Mode | When | Behaviour |
| --- | --- | --- |
| Local filesystem | `USE_REMOTE_STORAGE=False` (default, dev/CI) | Files in `backend/media/`, served by Django at `/media/…`. Lost on redeploy — fine for development. |
| Supabase Storage | `USE_REMOTE_STORAGE=True` (production) | Files in a public bucket, served by Supabase's CDN. |
| Cloudinary / R2 / S3 | Same env vars, different endpoint | `django-storages` speaks the S3 protocol; Cloudinary has its own backend. No code change. |

> **Migration note.** Editor.js stores the absolute URL it is given *inside* the article document. That is deliberate — the frontend is served from a different origin than the API, so a relative path would break — but it means published articles are coupled to whichever host served the image. After copying files to a new provider, repoint them:
>
> ```bash
> # Preview first — writes nothing
> python backend/manage.py rewrite_image_urls --from old-host.example.com
>
> # Apply
> python backend/manage.py rewrite_image_urls --from old-host.example.com --apply
> ```
>
> Only `image` blocks and `Article.featured_image` are touched; a URL that merely appears in prose is left alone.

---



## Deployment

The backend is configured for Render. The frontend is a static Vercel site (`frontend/vercel.json` enables `cleanUrls`). The active frontend uses `article.html?id=<id>` links consistently.

### Render (Production)

```bash
# Full build (install → collectstatic → migrate → seed)
bash build.sh

# Run with Gunicorn (as defined in Procfile)
gunicorn core.wsgi:application --chdir backend --bind 0.0.0.0:${PORT:-8000}
```



### Build Script

`build.sh` performs the following steps in order:

1. Install/upgrade pip
2. Install Python dependencies
3. Collect static files (WhiteNoise)
4. Apply database migrations
5. Seed sample data
6. Create superuser (if `DJANGO_SUPERUSER_*` env vars are set)

Run `python backend/manage.py ingest_articles` separately after setting the RAG variables. A failed ingestion exits non-zero and reports failed article slugs.



### Environment Requirements

The following environment variables **must** be set in production:

- `SECRET_KEY`
- `SUPABASE_URL`
- `DATABASE_URL` (Render provides this automatically for Postgres add-ons)

`PINECONE_API_KEY`, `PINECONE_INDEX_NAME`, and `GEMINI_API_KEY` are additionally required only when deploying RAG ingestion/chat.

Also set `CORS_ALLOWED_ORIGINS` (and `CSRF_TRUSTED_ORIGINS` if needed) to the Vercel frontend origin.

### Frontend deployment

The frontend is a dependency-free static site — there is no build step. Point Vercel at the `frontend/` directory and set its three public values in `frontend/js/config.js`:

```js
API_BASE_URL      = "https://<your-backend>.onrender.com"
SUPABASE_URL      = "https://<project>.supabase.co"
SUPABASE_ANON_KEY = "sb_publishable_…"   // publishable / anon key only
```

Never place the Supabase service-role key or the JWT secret in frontend code.

---



## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---



## License

Distributed under the MIT License. See `LICENSE` for more information.
