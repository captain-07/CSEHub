# CSEHub — Roadmap

Improvement plan for the CSEHub monorepo (`backend/` Django + DRF, `frontend/` static
vanilla JS), derived from the project review in `issues.md`.

Each item has: **why it matters**, **what to do**, **where**, and a rough size
(**S** ≈ hours, **M** ≈ a day or two, **L** ≈ a week+). Tiers are priority order, not
strictly effort order.

> Status legend: `[ ]` not started · `[~]` in progress · `[x]` done

---

## Where the project already stands

Worth stating up front so the plan is read as *incremental*, not remedial:

- 122 passing tests (`apps.articles` / `apps.users` / `apps.chatbot`).
- Three custom frontend check scripts that actually catch real drift
  (`.check-imports.mjs`, `.check-assets.mjs`, `.check-editor-tools.mjs`).
- `ArticleViewSet.get_queryset` already uses `select_related`/`prefetch_related`
  (`backend/apps/articles/views.py:134-137`) — no obvious list N+1.
- Storage configuration fails fast on missing/placeholder credentials, and the
  Cloudinary backend deliberately handles the three "quiet" default traps.
- `drf-spectacular` API docs at `/api/docs/`, `/api/redoc/`, `/api/schema/`.

The gaps below are mostly **process/ops** (no CI, no lint, no throttle, no observability)
and a few **product-level** items.

---

## Tier 1 — highest leverage, low risk

### 1. `[ ]` Add CI (the single biggest win) — **S/M**
**Why:** There is no `.github/` directory at all. Nothing runs on a PR, so the tests and
check scripts only run when someone remembers to run them by hand.
**What:**
- Create `.github/workflows/ci.yml`.
- Steps: `pip install -r requirements.txt`; run `node .check-imports.mjs`,
  `node .check-assets.mjs`, `node .check-editor-tools.mjs`; run
  `python backend/manage.py test apps.articles apps.users apps.chatbot`.
- Tests already resolve to in-memory SQLite when `test` is in `sys.argv`
  (`backend/core/settings.py:105-114`), so no Postgres service is needed.
**Where:** new `.github/workflows/ci.yml`.

### 2. `[ ]` Fix the test-discovery footgun — **S**
**Why:** `python manage.py test` from the repo root finds **0 tests and reports
success** — easy to mistake for a green build (open issue #12).
**What:**
- Add a root runner (Makefile target, `tox.ini`, or a small script) that invokes the
  explicit labels above.
- Point CI at that so "it passed" always means tests actually ran.

### 3. `[ ]` Dependency hygiene — **M**
**Why:** `requirements.txt` is a raw 95-line `pip freeze` containing an unused package
(`filetype`), duplicate Postgres drivers (`psycopg` **and** `psycopg2-binary`), and
`httpx2`/`httpcore2` whose consumer (`openai`) is not pinned. This is exactly how the
bogus `cloudinary==2.6.0` pin went unnoticed until the Cloudinary review.
**What:**
- Introduce `requirements.in` (direct deps only) + `pip-compile` lockfile.
- Split dev/prod requirements.
- Remove unused/duplicate pins; pin `openai` if `httpx2` is really needed.
- Add `pip-audit` and Dependabot.
**Where:** `requirements.txt` → `requirements/` (or `requirements.in` + `.txt`).

### 4. `[ ]` Lint + format + pre-commit — **M**
**Why:** No `pyproject.toml`, `ruff.toml`, ESLint/Prettier, or `.pre-commit-config.yaml`.
Style and import order are enforced by nothing.
**What:**
- Add `pyproject.toml` with `ruff` (lint + import sorting + `ruff format`).
- Add Prettier + ESLint (flat config) for `frontend/js`.
- Add `.pre-commit-config.yaml` wiring both; run in CI.
**Where:** repo root + `frontend/`.

### 5. `[ ]` Rate limiting / abuse protection — **M**
**Why:** No `DEFAULT_THROTTLE_CLASSES` anywhere. The **chat endpoint** (Gemini +
Pinecone — real per-request cost) and the **image upload** endpoint are
unauthenticated-cost or resource-abuse surfaces; the reaction endpoint is spammable.
**What:**
- Configure DRF `DEFAULT_THROTTLE_CLASSES` + rates.
- Use `ScopedRateThrottle` on `apps.chatbot.views` and `apps.articles.media.ImageUploadView`.
**Where:** `backend/core/settings.py`, `apps/chatbot/views.py`, `apps/articles/media.py`.

### 6. `[ ]` Health check + error monitoring — **M**
**Why:** No `/healthz`, no `CACHES`/Sentry. Failures surface to users as
"The assistant is not configured or is temporarily unavailable" with nothing actionable
in a dashboard.
**What:**
- Add a lightweight `/healthz` (DB ping, 200/503) for Render.
- Add Sentry (backend + frontend) or structured JSON logging with request ids.
**Where:** `backend/core/urls.py` + new health view; `frontend/js/config.js` init.

---

## Tier 2 — reliability & correctness

### 7. `[ ]` Automate the RAG lifecycle — **M/L**
**Why:** There are no `post_save`/`pre_delete` signals. Ingestion is manual, and
`manage.py ingest_articles --purge` is a documented footgun: deleted articles leave
vectors behind, and id reuse means the assistant can "answer from the *wrong* article,
confidently".
**What:**
- Signal on article publish/update → re-ingest; on delete → un-ingest.
- Add a reconciliation command comparing DB articles to the vector namespace.
- Keep `--purge` as the repair hatch.
**Where:** `backend/apps/chatbot/ingestion.py`, `apps/articles/signals.py` (new),
`core/apps.py`/`apps.py` `ready()`.

### 8. `[ ]` Real search instead of `ILIKE` — **M**
**Why:** `search_fields = ['title', 'excerpt']` with DRF's `SearchFilter`
(`apps/articles/views.py:102`) issues `icontains` and never searches `content`. For a
learning library that is the most important text.
**What:**
- Add a Postgres `SearchVector` over title + extracted content with a GIN index.
- Keep the existing filter/ordering backends.
**Where:** `apps/articles/views.py`, `apps/articles/models.py` (index), migration.

### 9. `[ ]` Add caching — **M**
**Why:** No `CACHES` config. The article list/detail are fetched on every page view and
are highly cacheable.
**What:**
- Add Redis + Django cache; short-TTL cache for list/detail.
- Emit `ETag`/`Cache-Control` so repeat visits revalidate cheaply.
**Where:** `core/settings.py`, `apps/articles/views.py`.

### 10. `[ ]` Settings structure + config validation — **M**
**Why:** One `settings.py` serves all environments, and only storage/DB are validated
at startup. A placeholder `SECRET_KEY` or missing DB config fails late.
**What:**
- Split `base`/`dev`/`test`/`prod` (or a single file with clearer sections).
- Validate `SECRET_KEY` isn't a placeholder; validate DB config eagerly.
**Where:** `backend/core/settings.py`.

### 11. `[ ]` Image pipeline hardening — **M**
**Why:** No `Image.MAX_IMAGE_PIXELS` guard (decompression-bomb DoS surface). No storage
`delete()` override and no orphan cleanup, so the Cloudinary account grows unbounded.
**What:**
- Set `Image.MAX_IMAGE_PIXELS` and reject oversized decodes.
- Override `delete()` on `CloudinaryArticleStorage`.
- Add a command to purge unreferenced assets.
**Where:** `apps/articles/image_processing.py`, `apps/articles/storage.py`,
new management command.

### 12. `[ ]` Data-integrity guards for reactions — **S/M**
**Why:** `like_count`/`dislike_count` are denormalized (well documented) and can drift
if a row is mutated outside the manager.
**What:**
- Add `CheckConstraint(like_count >= 0)` and `(dislike_count >= 0)`.
- Schedule/automate `recompute_reaction_counts` so drift self-heals.
**Where:** `apps/articles/models.py` (+ migration), ops schedule.

---

## Tier 3 — frontend & product

### 13. `[ ]` SEO / prerendering — **M/L**
**Why:** All 5 pages are client-rendered and OG/meta tags are injected by JS
(`frontend/js/article.js` `applyDocumentMeta`), which many crawlers never execute.
**What:**
- Add `sitemap.xml`, `robots.txt`, canonical URLs.
- Prerender or statically generate article pages so title/description/OG are in the HTML.
**Where:** `frontend/`, deployment config.

### 14. `[ ]` Responsive images — **S/M**
**Why:** Images are stored at up to 1600px WebP; phones still download desktop-sized
files.
**What:** Emit `srcset`/`sizes` using Cloudinary transformations
(`f_auto,q_auto,w_*`).
**Where:** `frontend/js/renderer.js`, `frontend/js/article.js`.

### 15. `[ ]` Frontend tests — **M**
**Why:** Beyond the `.check-*.mjs` scripts there are no automated frontend tests.
**What:**
- Add Vitest for module logic (renderer/reactions).
- Add a Playwright smoke test over the 5 pages; run both in CI.
**Where:** `frontend/` (+ workflow).

### 16. `[ ]` Accessibility pass — **M**
**Why:** Keyboard/focus handling and `aria-pressed` exist in places but there is no
audit.
**What:** Run `axe`; add reduced-motion support and focus-management coverage.
**Where:** `frontend/css/`, `frontend/js/`.

### 17. `[ ]` Product features — **varies**
Choose by roadmap: RSS feed, author pages, comments, bookmarks/"read later", scheduled
publishing, shareable draft-preview links, reading progress, a tags landing page, and
analytics.

---

## Tier 4 — docs & developer experience

### 18. `[ ]` Fix documentation drift — **S**
**Why:** (open issue #10) README/`frontend/README` reference `article.html?id=<id>` but
the app uses `?slug=`; the `index.html` OG comment and `AGENTS.md`'s duplicate
"`image_processing.py`" reference are wrong.
**What:** Sweep for `?id=` and the stale file references; correct them.
**Where:** `README.md`, `frontend/README.md`, `frontend/index.html`, `AGENTS.md`.

### 19. `[ ]` One-command local dev — **M**
**Why:** Bootstrapping requires hand-editing `backend/.env` and having Postgres.
**What:** Add `docker-compose` (Postgres + stubs for Gemini/Pinecone) and a Makefile;
document the happy path.
**Where:** new `docker-compose.yml`, `Makefile`.

### 20. `[ ]` API versioning — **S/M**
**Why:** Routes are unversioned (`/api/...`); introducing `/api/v1/` is cheap now and
enables deprecations later.
**What:** Namespace the included URLconfs under `/api/v1/`.
**Where:** `backend/core/urls.py` (+ frontend base paths).

### 21. `[ ]` Keep the plan and the issue log current — **S**
**What:**
- Maintain this `roadmap.md`; tick items off.
- Mark resolved items in `issues.md`.

---

## Suggested sequencing

1. **Tier 1.1–1.4** first — CI, test runner, dependency lock, lint. They protect
   everything else and are self-contained.
2. **1.5–1.6** — throttling and observability (money + uptime).
3. **2.7 and 2.11** — the two silent cost/data-loss footguns (RAG orphans, image
   orphans/bombs).
4. Then **Tier 2.8–2.12**, then **Tier 3**, then **Tier 4**.

---

## Status of `issues.md` findings

**Resolved:**
- #1 featured articles never render on the home page.
- #2 `cloudinary==2.6.0` invalid pin.
- #2b Cloudinary `_save` caught a nonexistent exception class.
- #4 reading-time never rendered on cards.
- #8 unstyled `.byline` / `.reaction-label`.
- #9 settings nits (duplicate `changeme`, `SECURE_SSL_REDIRECT` default).
- The Cloudinary migration `--to` ambiguity.

**Still open:**
- #3 first sign-in fails for an existing email-only account (auth linking).
- #5 frontend API host vs `ALLOWED_HOSTS` mismatch.
- #6 `requirements.txt` hygiene (tracked here as item 3).
- #7 `showError()` uses unescaped `innerHTML` (defense-in-depth).
- #10 documentation drift (tracked here as item 18).
- #11 `renderer.js` nested identical inline tags.
- #12 root-level test discovery runs zero tests (tracked here as item 2).
