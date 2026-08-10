# CSEHub

Backend API for the CSEHub learning platform — a Django REST Framework application for computer science education, featuring articles with code snippets, coding problems with test cases, and an AI-powered chatbot.

[![Python](https://img.shields.io/badge/python-3.11+-blue?logo=python)](https://www.python.org)
[![Django](https://img.shields.io/badge/django-6.0.3-092E20?logo=django)](https://www.djangoproject.com)
[![DRF](https://img.shields.io/badge/djangorestframework-3.16.0-red?logo=django)](https://www.django-rest-framework.org)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Render](https://img.shields.io/badge/deployed%20on-Render-46E3B7?logo=render)](https://render.com)

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
  - [API Documentation](#api-documentation)
  - [Database Migrations](#database-migrations)
  - [Seeding Data](#seeding-data)
  - [Running Tests](#running-tests)
- [Project Structure](#project-structure)
- [API Endpoints](#api-endpoints)
- [Deployment](#deployment)
- [Contributing](#contributing)
- [License](#license)

---

## Features

- **Article Management** — Browse and search educational articles organized by categories and tags, with embedded code snippets
- **Coding Problems** — Problem bank with difficulty levels, test cases, and submission tracking (in development)
- **AI Chatbot** — RAG-powered assistant for answering questions about articles (in development)
- **Supabase Auth** — JWT-based authentication via Supabase for secure, passwordless login
- **API Documentation** — Auto-generated OpenAPI schema with Swagger UI and ReDoc
- **Cloudinary Media** — Image and file hosting via Cloudinary CDN

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Framework** | Django 6.0.3 + Django REST Framework 3.16.0 |
| **Database** | PostgreSQL (via Supabase) |
| **Authentication** | Supabase Auth (JWT, HS256) |
| **API Docs** | drf-spectacular (OpenAPI 3.0, Swagger, ReDoc) |
| **Media Storage** | Cloudinary |
| **RAG Pipeline** | Pinecone (vector DB) + Google Gemini |
| **Deployment** | Render (Gunicorn + WhiteNoise) |
| **Frontend** | Vercel (placeholder) |

---

## Getting Started

### Prerequisites

- Python 3.11+
- PostgreSQL (local or remote)
- Supabase project (for JWT auth)
- Cloudinary account (for media)

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

| Variable | Required | Description |
|----------|----------|-------------|
| `SECRET_KEY` | Yes | Django secret key (generate with `python -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())'`) |
| `DEBUG` | No | Set to `True` for local development (default: `False`) |
| `DATABASE_URL` | Yes* | PostgreSQL connection string (preferred over individual DB_* vars) |
| `DB_NAME`, `DB_USER`, etc. | Yes* | Fallback database variables when `DATABASE_URL` is not set |
| `SUPABASE_JWT_SECRET` | Yes | Your Supabase project JWT secret |
| `SUPABASE_URL` | Yes | Your Supabase project URL |
| `CLOUDINARY_*` | No | Cloudinary credentials (optional, for media uploads) |
| `CORS_ALLOWED_ORIGINS` | No | Comma-separated frontend origins (default: `http://localhost:3000`) |
| `DJANGO_SUPERUSER_*` | No | Auto-create superuser during `build.sh` |

*\*Either `DATABASE_URL` or the individual `DB_*` variables must be provided.*

> **Note:** The `.env` file lives in `backend/`, not the project root. The settings module reads `backend/.env` at import time.

---

## Usage

### Development Server

```bash
# From the project root
python backend/manage.py runserver
# Or from the backend directory
cd backend && python manage.py runserver
```

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

This command is idempotent and safe to run multiple times.

### Running Tests

```bash
# Run all tests
python backend/manage.py test
```

Tests use Django's built-in `TestCase` (no pytest). Test coverage is currently minimal.

---

## Project Structure

```
CSEHub/
├── backend/
│   ├── apps/
│   │   ├── articles/         # Article CRUD (mature)
│   │   │   ├── management/commands/seed.py
│   │   │   ├── migrations/
│   │   │   ├── models.py
│   │   │   ├── serializers.py
│   │   │   ├── urls.py
│   │   │   └── views.py
│   │   ├── chatbot/          # AI chatbot (models only)
│   │   │   ├── models.py
│   │   │   └── views.py      # stub
│   │   ├── problems/         # Coding problems (models only)
│   │   │   ├── models.py
│   │   │   └── views.py      # stub
│   │   └── users/            # Custom auth (auth + model)
│   │       ├── authentication.py
│   │       ├── models.py
│   │       └── views.py      # stub
│   ├── core/
│   │   ├── settings.py
│   │   ├── urls.py
│   │   ├── wsgi.py
│   │   └── asgi.py
│   ├── .env.example
│   └── manage.py
├── frontend/                 # Vercel placeholder
├── build.sh                  # Production build script
├── Procfile                  # Render process declaration
└── requirements.txt
```

### App Maturity

| App | Status | Description |
|-----|--------|-------------|
| `articles` | ✅ Mature | Full CRUD API, admin, serializers |
| `users` | ⚠️ Partial | Auth works, model done, no views yet |
| `problems` | 🚧 Models only | Problem/TestCase/Submission defined, no API |
| `chatbot` | 🚧 Models only | Conversation/Message defined, no API |

---

## API Endpoints

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| `GET` | `/api/articles/` | List published articles | Public |
| `GET` | `/api/articles/{id}/` | Article detail with content & snippets | Public |
| `POST` | `/api/articles/` | Create article | Admin |
| `PUT` | `/api/articles/{id}/` | Update article | Admin |
| `DELETE` | `/api/articles/{id}/` | Delete article | Admin |
| `GET` | `/api/categories/` | List categories | Public |
| `GET` | `/api/tags/` | List tags | Public |
| `GET` | `/api/docs/` | Swagger UI | Public |
| `GET` | `/api/redoc/` | ReDoc UI | Public |
| `GET` | `/api/schema/` | OpenAPI schema (JSON) | Public |
| `/admin/` | Django admin interface | Staff |

**Filtering & Search** — The articles endpoint supports:
- Filtering by `category__slug` and `tags__slug`
- Full-text search on `title` and `content`
- Ordering by `created_at`

---

## Deployment

The project is configured for deployment on Render.

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

### Environment Requirements

The following environment variables **must** be set in production:
- `SECRET_KEY`
- `SUPABASE_JWT_SECRET`
- `SUPABASE_URL`
- `DATABASE_URL` (Render provides this automatically for Postgres add-ons)

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
