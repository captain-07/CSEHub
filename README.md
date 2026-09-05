# CSEHub

CSEHub is a computer science learning platform: a Django REST API plus a static frontend. It serves educational articles with code snippets, a per-article RAG chatbot, and Supabase-backed user accounts. Coding problems are modeled but not yet exposed as an API.

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
- [API Endpoints](#api-endpoints)
- [Deployment](#deployment)
- [Contributing](#contributing)
- [License](#license)

---



## Features

- **Article library** — Browse, filter, and search published articles by category and tag, with embedded code snippets
- **AI article assistant** — Authenticated RAG chatbot (Pinecone + Gemini) scoped to a single article, with persisted conversation history
- **Supabase Auth** — JWT authentication via Supabase; the API auto-provisions a local `User` from a valid Bearer token
- **User profile** — `GET`/`PATCH /api/me/` for display name, username, and avatar
- **Static frontend** — HTML/CSS/JS client (home, articles, article + chat, login, profile) deployed on Vercel
- **API documentation** — Auto-generated OpenAPI schema with Swagger UI and ReDoc
- **Cloudinary media** — Optional image and file hosting via Cloudinary CDN
- **Coding problems** — Problem / test case / submission models exist; API and UI are not implemented yet

---



## Tech Stack


| Layer              | Technology                                       |
| ------------------ | ------------------------------------------------ |
| **Backend**        | Django 6.0.3 + Django REST Framework 3.16.0      |
| **Database**       | PostgreSQL (via `DATABASE_URL` or `DB_`* vars)   |
| **Authentication** | Supabase Auth (JWT, ES256)                       |
| **API Docs**       | drf-spectacular (OpenAPI 3.0, Swagger, ReDoc)    |
| **Media Storage**  | Cloudinary                                       |
| **RAG Pipeline**   | LangChain + Pinecone (vector DB) + Google Gemini |
| **Backend deploy** | Render (Gunicorn + WhiteNoise)                   |
| **Frontend**       | Static HTML, CSS, and ES modules on Vercel       |


---



## Getting Started



### Prerequisites

- Python 3.11+
- PostgreSQL (local or remote)
- Supabase project (JWT auth)
- Pinecone index and Google Gemini API key (required — settings fail at import if missing)
- Cloudinary account (optional, for media)



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
| `SUPABASE_JWT_SECRET`                                     | Yes      | Supabase project JWT secret (required at import time)                                                                                          |
| `SUPABASE_URL`                                            | Yes      | Supabase project URL (required at import time)                                                                                                 |
| `PINECONE_API_KEY`                                        | Yes      | Pinecone API key (required at import time)                                                                                                     |
| `PINECONE_INDEX_NAME`                                     | Yes      | Pinecone index used for article embeddings                                                                                                     |
| `GEMINI_API_KEY`                                          | Yes      | Google Gemini API key for embeddings and chat                                                                                                  |
| `CLOUDINARY_*`                                            | No       | Cloudinary credentials (optional, for media uploads)                                                                                           |
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

The frontend is a dependency-free static site. It defaults to the production API at `https://csehub-ezdl.onrender.com`.

```powershell
python -m http.server 3000 --directory frontend
```

Then open `http://localhost:3000`. Run Django separately on port 8000.

To point the client at a local API, set `window.CSEHUB_API_BASE_URL` before `js/config.js`:

```html
<script>window.CSEHUB_API_BASE_URL = "http://localhost:8000";</script>
```

The frontend origin must be listed in the backend's `CORS_ALLOWED_ORIGINS`.

Pages:


| File            | Route (with `cleanUrls`) | Description                             |
| --------------- | ------------------------ | --------------------------------------- |
| `index.html`    | `/`                      | Home / marketing                        |
| `articles.html` | `/articles`              | Article library with search and filters |
| `article.html`  | `/article`               | Article detail + RAG chat               |
| `login.html`    | `/login`                 | Sign in / sign up (Supabase)            |
| `profile.html`  | `/profile`               | Current user profile                    |




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

Published articles are chunked, embedded with Gemini, and stored in Pinecone (namespace `articles`). Saving a published article also triggers ingestion via a `post_save` signal.

```bash
python backend/manage.py ingest_articles
```

`build.sh` runs this after `seed`.

### Running Tests

```bash
# Run all tests
python backend/manage.py test
```

Tests use Django's built-in `TestCase` (no pytest). App `tests.py` files are currently stubs.

---



## Project Structure

```
CSEHub/
├── backend/
│   ├── apps/
│   │   ├── articles/              # Article CRUD (mature)
│   │   │   ├── management/commands/seed.py
│   │   │   ├── models.py          # Category, Tag, Article, CodeSnippet
│   │   │   ├── serializers.py
│   │   │   ├── urls.py
│   │   │   └── views.py
│   │   ├── chatbot/               # RAG chatbot
│   │   │   ├── management/commands/ingest_articles.py
│   │   │   ├── ingestion.py       # Pinecone embeddings
│   │   │   ├── rag_chat.py        # Gemini grounded answers
│   │   │   ├── signals.py         # Re-ingest on article save
│   │   │   ├── models.py          # Conversation, Message
│   │   │   ├── urls.py
│   │   │   └── views.py
│   │   ├── problems/              # Coding problems (models only)
│   │   │   ├── models.py          # Problem, TestCase, Submission
│   │   │   └── views.py           # stub
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
│   ├── .env.example
│   └── manage.py
├── frontend/                      # Static Vercel client
│   ├── index.html
│   ├── articles.html
│   ├── article.html
│   ├── login.html
│   ├── profile.html
│   ├── css/
│   ├── js/
│   └── vercel.json
├── build.sh                       # Production build script
├── Procfile                       # Render process declaration
└── requirements.txt
```



### App Maturity


| App        | Status      | Description                                                  |
| ---------- | ----------- | ------------------------------------------------------------ |
| `articles` | Mature      | Full CRUD API, admin, serializers, public read / admin write |
| `chatbot`  | Implemented | Ask + conversation APIs, ingestion, RAG pipeline             |
| `users`    | Partial     | Auth, model, and `/api/me/` profile; no user admin API       |
| `problems` | Models only | Problem / TestCase / Submission defined, no API              |


---



## API Endpoints


| Method          | Endpoint                             | Description                                 | Auth          |
| --------------- | ------------------------------------ | ------------------------------------------- | ------------- |
| `GET`           | `/api/articles/`                     | List published articles                     | Public        |
| `GET`           | `/api/articles/{id}/`                | Article detail with content and snippets    | Public        |
| `POST`          | `/api/articles/`                     | Create article                              | Admin         |
| `PUT` / `PATCH` | `/api/articles/{id}/`                | Update article                              | Admin         |
| `DELETE`        | `/api/articles/{id}/`                | Delete article                              | Admin         |
| `GET`           | `/api/categories/`                   | List categories                             | Public        |
| `GET`           | `/api/categories/{id}/`              | Category detail                             | Public        |
| `GET`           | `/api/tags/`                         | List tags                                   | Public        |
| `GET`           | `/api/tags/{id}/`                    | Tag detail                                  | Public        |
| `GET`           | `/api/me/`                           | Current user profile                        | Authenticated |
| `PATCH`         | `/api/me/`                           | Update display name, username, or avatar    | Authenticated |
| `POST`          | `/api/articles/{slug}/ask/`          | Ask a question about an article (RAG)       | Authenticated |
| `GET`           | `/api/articles/{slug}/conversation/` | Load the user's conversation for an article | Authenticated |
| `GET`           | `/api/docs/`                         | Swagger UI                                  | Public        |
| `GET`           | `/api/redoc/`                        | ReDoc UI                                    | Public        |
| `GET`           | `/api/schema/`                       | OpenAPI schema (JSON)                       | Public        |
| —               | `/admin/`                            | Django admin                                | Staff         |


**Filtering & search** — The articles list endpoint supports:

- Filtering by `category__slug` and `tags__slug`
- Full-text search on `title` and `content`
- Ordering by `created_at` (default: newest first)
- Page-number pagination (`PAGE_SIZE` = 20)

**Auth header** — Send `Authorization: Bearer <supabase-access-token>`. A valid JWT creates or updates the matching `users.User` row (`supabase_uid` + email).

---



## Deployment

The backend is configured for Render. The frontend is a static Vercel site (`frontend/vercel.json` enables `cleanUrls`).

### Render (Production)

```bash
# Full build (install → collectstatic → migrate → seed → ingest)
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
6. Ingest published articles into Pinecone
7. Create superuser (if `DJANGO_SUPERUSER_*` env vars are set)



### Environment Requirements

The following environment variables **must** be set in production:

- `SECRET_KEY`
- `SUPABASE_JWT_SECRET`
- `SUPABASE_URL`
- `PINECONE_API_KEY`
- `PINECONE_INDEX_NAME`
- `GEMINI_API_KEY`
- `DATABASE_URL` (Render provides this automatically for Postgres add-ons)

Also set `CORS_ALLOWED_ORIGINS` (and `CSRF_TRUSTED_ORIGINS` if needed) to the Vercel frontend origin.

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