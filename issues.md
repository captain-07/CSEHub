# CSEHub — Project Review Issues

_Reviewed: 2026-10-17 · Branch: `main` · Working tree has uncommitted changes (see note at the end)_

A project-wide review of the Django/DRF backend (`backend/`) and the static vanilla-JS
frontend (`frontend/`). Findings are grouped by severity and each entry lists where it
lives, what goes wrong, why, and a suggested fix.

## Summary

| # | Severity | Area | Issue |
|---|----------|------|-------|
| 1 | 🔴 High | frontend | Featured articles never appear on the home page |
| 2 | 🔴 High | dependencies | `cloudinary==2.6.0` is not a published release — `pip install` fails |
| 2b | 🔴 High | backend storage | Cloudinary `_save` catches a nonexistent exception class — upload errors surface as `AttributeError` |
| 3 | 🟠 Medium | backend auth | First sign-in fails for an existing email-only account |
| 4 | 🟠 Medium | frontend | Reading-time never renders on article cards (dead code) |
| 5 | 🟠 Medium | ops/config | API host vs `ALLOWED_HOSTS` mismatch |
| 6 | 🟡 Low | dependencies | Dependency-hygiene problems in `requirements.txt` |
| 7 | 🟡 Low | frontend | `showError()` writes caller input to `innerHTML` |
| 8 | 🟡 Low | frontend | Two CSS classes referenced but never styled |
| 9 | 🟡 Low | backend | Duplicate placeholder + `SECURE_SSL_REDIRECT` off in prod block |
| 10 | 🟡 Low | docs | Documentation drift (`?id=` vs `?slug=`, stale comments) |
| 11 | 🟡 Low | frontend | `renderer.js` nested identical inline tags can unbalance markup |
| 12 | ⚪ Info | tests | Root-level test discovery silently runs 0 tests |

---

## 🔴 High

### 1. Featured articles never appear on the home page

**Where:** `frontend/index.html:39`, `frontend/js/home.js:21-39`, `frontend/js/home.js:45-49`

**Symptom:** The "Featured lessons" rail is never visible, and the articles an editor
marks as featured are missing from the home page entirely.

**Cause:** Two independent problems combine:

1. `index.html` ships the featured section hidden:
   ```html
   <section class="features-section container" id="featured-section" hidden>
   ```
   `loadFeatured()` _adds_ `section.hidden = true` on the empty/error paths
   (`home.js:29`, `home.js:37`) but never sets `section.hidden = false` when featured
   articles **do** exist. So even with featured content, the section stays hidden.

2. As it renders, `loadFeatured()` records the featured ids in the module-level
   `featuredIds` set (`home.js:33`), and `loadRecent()` filters those ids out of the
   recent grid (`home.js:45`). With the rail hidden, the featured articles are therefore
   removed from the only place they could have appeared.

   (The `home.js:47-49` fallback only repeats featured articles when the library is
   _entirely_ featured, which does not cover the normal mixed library.)

**Suggested fix:** In the success branch of `loadFeatured()`, clear the attribute before
rendering, e.g. `if (section) section.hidden = false;` right after the `featured.length`
guard. Optionally drop the `hidden` attribute in `index.html` and let JS own visibility
(with a `.hidden`/`[hidden]` rule) so the default state is consistent.

---

### 2. `cloudinary==2.6.0` in `requirements.txt` does not exist — installs fail

**Where:** `requirements.txt:17`

**Symptom:** `pip install -r requirements.txt` (called by `build.sh` and any deployment)
cannot resolve `cloudinary==2.6.0`. The Cloudinary Python SDK has never published a `2.x`
release.

**Evidence:**
```
$ pip index versions cloudinary
cloudinary (1.46.3)
Available versions: 1.46.3, 1.46.2, ... 1.0.0, 0.2.8 ...
  INSTALLED: 1.44.0
```
The highest published version is `1.46.3`; the environment actually has `1.44.0`
installed. The `2.6.0` pin was added in the current (uncommitted) working tree:

```diff
+Django==6.0.3
+cloudinary==2.6.0
+django-cloudinary-storage==0.3.0
```

**Suggested fix:** Pin to a version that exists and matches what is installed/tested,
e.g. `cloudinary==1.44.0` (or bump deliberately to `1.46.3` and re-test). Confirm with
`pip install -r requirements.txt` in a clean venv before committing.

---

### 2b. Cloudinary `_save` catches an exception class that does not exist

**Where:** `backend/apps/articles/storage.py:73`

**Symptom:** Any Cloudinary upload that fails does **not** produce the intended
`400` with a readable message. Instead the request blows up with
`AttributeError: module 'cloudinary.api' has no attribute 'Error'`, and the original
Cloudinary error is lost.

**Cause:** The handler names a class the SDK does not expose:
```python
except cloudinary.api.Error as exc:
    if getattr(exc, 'http_code', 0) and exc.http_code < 500:
        raise ValidationError(f'Cloudinary rejected the upload: {exc}') from exc
    raise
```
Verified against the pinned/installed SDK:

```
$ python -c "import cloudinary, cloudinary.api; print(hasattr(cloudinary.api,'Error'))"
False
$ python -c "import cloudinary, cloudinary.api; raise cloudinary.exceptions.Error('boom')" via except cloudinary.api.Error
AttributeError: module 'cloudinary.api' has no attribute 'Error'
```
`cloudinary.api` re-exports `BadRequest`, `NotFound`, `AlreadyExists`, `GeneralError`,
… but **not** `Error`. The base class lives at `cloudinary.exceptions.Error`
(also aliased as `cloudinary.uploader.Error`).

Because the `except` expression is only evaluated when an exception is raised, the
bug is invisible on the happy path — which is exactly why the 41 passing
`test_media` tests do not catch it (none exercises a provider rejection). The code
comment's own intent ("answer 400 with a readable message instead of a 500") is
therefore not achieved; every failure becomes a *different* 500.

**Suggested fix:** Catch the real base class:
```python
except cloudinary.exceptions.Error as exc:
```
(`import cloudinary.exceptions`), or `cloudinary.uploader.Error`. Add a unit test that
stubs `cloudinary.uploader.upload` to raise and asserts a `400`/`ValidationError`
for a 4xx and a re-raise for a 5xx.

---

## 🟠 Medium

### 3. First sign-in fails for an account that already exists by email

**Where:** `backend/apps/users/authentication.py:88-91`, `backend/apps/users/models.py`

**Symptom:** A user whose email already has a `User` row (e.g. created by the seed
command, an admin, or an earlier provider) cannot sign in via Supabase. The request fails
with the generic message `Invalid or expired authentication token`.

**Cause:** Lookup is keyed only on `supabase_uid`:
```python
user, created = User.objects.get_or_create(
    supabase_uid=supabase_uid,
    defaults={"email": email, ...},
)
```
If a row already exists with the same `email` but a **different/blank** `supabase_uid`,
the `get` misses and the `create` hits the unique constraint on `email`, raising
`IntegrityError`. That is caught by the broad `except Exception` at
`authentication.py:122-124` and reported as "Invalid or expired authentication token",
which hides the real cause.

**Suggested fix:** Before `get_or_create`, look up by `email` and adopt/link the row when
its `supabase_uid` is empty (or explicitly handle the collision and log it). At minimum,
log the `IntegrityError` server-side so this is diagnosable.

---

### 4. Reading-time never renders on article cards

**Where:** `frontend/js/renderer.js:399`, `backend/apps/articles/serializers.py:58`

**Symptom:** The `… · 5 min read` fragment in `articleCardMarkup` never shows.

**Cause:** `articleCardMarkup` computes the reading time from `article.content`:
```js
const rt = readingTime(article.content);
```
but the listing serializer (`ArticleListSerializer.fields`) omits `content`, so list
payloads never carry it. `readingTime()` therefore returns an empty string and the
span is never emitted (`renderer.js:413`). The feature is effectively dead until either
the field is added to list payloads or the computation moves to a cheaper source.

**Suggested fix:** Either add a pre-computed `reading_time` field to
`ArticleListSerializer` (preferred — avoids shipping full content in every list response
and avoids doing the work client-side), or include `content` in the list serializer.

---

### 5. Frontend API host disagrees with `ALLOWED_HOSTS`

**Where:** `frontend/js/config.js:11`, `backend/.env.example:5`

**Symptom:** Risk of `400 DisallowedHost` / CORS mismatches when the deployed hostname and
the configured allow-list diverge.

**Cause:**
- `config.js` deployed base URL: `https://csehub-ezdl.onrender.com`
- `.env.example` `ALLOWED_HOSTS=csehub.onrender.com,localhost,127.0.0.1`

These are different hosts (`csehub-ezdl` vs `csehub`). If the real Render host is
`csehub-ezdl.onrender.com`, the example allow-list is wrong; if it is `csehub.onrender.com`,
the frontend points at the wrong backend.

**Suggested fix:** Reconcile to the actual deployed hostname in both places. Note
`settings.py:43-44` already appends `RENDER_EXTERNAL_HOSTNAME`, so prefer relying on that
in production and keep `.env.example` as a local default only.

---

## 🟡 Low

### 6. `requirements.txt` dependency hygiene

**Where:** `requirements.txt`

- `cloudinary==2.6.0` — see issue #2 (invalid pin).
- `filetype==1.2.0` (line 25) is **unused** — `media.py` uses the stdlib `mimetypes`
  module. Safe to remove.
- Both `psycopg==3.3.3` + `psycopg-binary==3.3.3` (lines 62-63) **and**
  `psycopg2-binary==2.9.11` (line 64) are pinned. The project runs on `psycopg` (v3);
  `psycopg2-binary` is only a documented fallback. Carrying both bloats the build and
  can mask which driver is actually in use.
- `httpx2==2.12.0` / `httpcore2==2.12.0` (lines 36, 38) are required only by `openai`,
  which is **not** pinned here — so this looks like an incomplete freeze.

**Suggested fix:** Prune unused/duplicate pins and regenerate the file from a clean
environment so every entry corresponds to a real, load-bearing dependency.

### 7. `showError()` writes caller input straight to `innerHTML`

**Where:** `frontend/js/login.js:9-11`

```js
function showError(message) {
  alertBox.innerHTML = `<div class="alert alert-error" role="alert">${message}</div>`;
}
```
The current caller (`login.js:67`) escapes `error.message`, and intentionally passes its
own `<strong>` markup, so this is safe **today** — but the helper itself has no
escaping contract, so any future caller that passes raw text (e.g. an error message that
echoes server output) becomes an XSS sink.

**Suggested fix:** Give the helper a safe API — e.g. `showError(text)` that
`escapeHtml`s `text`, plus a separate `showErrorHtml()` for the rare trusted case.

### 8. Two CSS classes are referenced but never styled

**Where:** `frontend/js/article.js:149` (`.byline`), `frontend/js/reactions.js:88`
(`.reaction-label`), `frontend/css/article.css`

`node .check-assets.mjs` reports:
```
NO CSS .byline <- frontend\js\article.js
NO CSS .reaction-label <- frontend\js\reactions.js
```
`article.css` styles `.article-byline span` but never defines `.byline`, and
`.reaction-label` has no rule at all — so the byline inherits only generic span styling
and the reaction label is unstyled.

**Suggested fix:** Add the missing rules (or, if the classes are intentional no-ops,
rename them). Keeping the asset check at zero warnings makes it a useful gate.

### 9. Misc. settings nits

**Where:** `backend/core/settings.py:236`, `backend/core/settings.py:345`

- `_PLACEHOLDER_VALUES` lists `'changeme'` twice:
  ```python
  _PLACEHOLDER_VALUES = {'', 'your-project-ref', 'your_project_ref', 'changeme', 'changeme'}
  ```
  Harmless (a set), but should be de-duplicated.
- In the production hardening block, `SECURE_SSL_REDIRECT` defaults to `False`
  (line 345) while the cookie flags above it are hard-set to `True`. A production deploy
  that forgets to set the env var silently serves plain HTTP without redirecting.

**Suggested fix:** Remove the duplicate literal; consider defaulting
`SECURE_SSL_REDIRECT` to `True` when `DEBUG` is False (letting `env.bool` override for
local tunneling).

### 10. Documentation drift

- `README.md` / `frontend/README.md` reference article links as
  `article.html?id=<id>`, but `renderer.js:395` and the rest of the frontend use
  `article.html?slug=<slug>`. Follow the docs literally and you get a broken link.
- `frontend/index.html`'s Open Graph comment points at `js/article.js` for a value that
  lives elsewhere (verify and update the comment).
- `AGENTS.md` says "`image_processing.py` owns that pipeline and `image_processing.py`
  is required" — the second mention should be `Pillow`/`media.py`.

**Suggested fix:** Sweep the docs for `?id=` and the stale file references.

### 11. `renderer.js` inline-tag handling with nested identical tags

**Where:** `frontend/js/renderer.js` (inline-tag tracking via a `Set`/`__hash__`)

Nested occurrences of the same inline tag can be tracked incorrectly because membership
is keyed by identity in a set, which can produce unbalanced markup in rare authoring
cases. Low impact (requires unusual content), but worth a targeted test if inline
formatting is expanded.

### 12. Root-level test discovery runs zero tests

**Where:** repo root

`python manage.py test` from the repo root finds **0** tests and reports success, which is
easy to mistake for a green build. The documented invocation must be explicit:

```bash
python backend/manage.py test apps.articles apps.users apps.chatbot
```

**Suggested fix:** Add a small test runner script (or a `Makefile`/`tox`-style entry) that
invokes the correct paths so CI and contributors cannot run "nothing" and see success.

---

## Verified as working (no action needed)

- `node .check-imports.mjs` → _All imports resolve._
- `node .check-editor-tools.mjs` → _all checks passed._
- Django suite: `python backend/manage.py test apps.articles apps.users apps.chatbot`
  → **119 tests, OK** (uses in-memory SQLite when `test` is in `sys.argv`).

## Note on the working tree

The Cloudinary storage additions come from **uncommitted** changes on `main`
(`AGENTS.md`, `backend/.env.example`, `rewrite_image_urls.py`, `media.py`,
`test_media.py`, `settings.py`, `requirements.txt`, plus the new `storage.py`).
The Supabase Storage (S3) backend has since been removed entirely, along with the
one-time `migrate_images_to_cloudinary` import it needed. Confirm the intended
state of these changes before treating them as shipped.

---

## Cloudinary setup — detailed assessment

Prompted by "check if the Cloudinary setup is properly done". Short answer: **the custom
storage layer is thoughtful and largely correct, but two defects break it in production,
and the documented migration procedure is self-inconsistent.**

### What is done well (verified)

- **Registration is correct.** `INSTALLED_APPS` loads `cloudinary_storage` (and its
  `app_settings`), the `CLOUDINARY_STORAGE` dict is defined unconditionally in
  `settings.py:242-248` (so the import-time `cloudinary.config()` in
  `cloudinary_storage/app_settings.py:38` never raises), and the backend is selected
  whenever `USE_REMOTE_STORAGE=True` (Cloudinary is the only remote provider).
- **Fail-fast validation** (`settings.py:250-261`) rejects empty/placeholder
  `CLOUDINARY_CLOUD_NAME` / `API_KEY` / `API_SECRET` at startup, matching the documented
  promise in `.env.example:71-75`.
- **The three "quiet" Cloudinary defaults are handled deliberately** and each is
  covered by a passing test in `test_media.py`:
  - unsigned URLs (`sign_url=False`) — so rotating the API secret does not invalidate
    published image URLs;
  - extension-free public ids — so `a.webp` does not become `a.webp.webp`;
  - `PREFIX: ''` — so ids are `articles/<token>` rather than nested under `media/`.
- **`_save` returns the extension-free public id and `_public_url` consumes it**;
  `default_storage.url()` already yields an absolute `https://res.cloudinary.com/...`
  URL, and `media._public_url` correctly passes it through verbatim
  (`media.py:111`). The end-to-end "upload → stored URL → read" round trip is sound.
- **`get_available_name` is inherited from the library and does no `exists()`/network
  probe**, so `default_storage.save()` does not issue a HEAD request per upload.
- **The provider size ceiling is wired**: in the Cloudinary branch
  `STORAGE_MAX_UPLOAD_BYTES = 10 MB` and `media.provider_max_upload_bytes()` clamps the
  20 MB animated-image limit against it.

### What is broken

1. **`cloudinary==2.6.0` cannot be installed** (issue #2). The SDK's newest release is
   `1.46.3`; the working environment has `1.44.0`. `pip download cloudinary==2.6.0`
   fails outright, so `pip install -r requirements.txt` / `build.sh` cannot succeed.
   `django-cloudinary-storage==0.3.0` is the latest of *its* package and declares the
   dependency unpinned (`Requires: cloudinary, requests`), so the specific `2.6.0` pin is
   simply wrong.
2. **`except cloudinary.api.Error` does not exist** (issue 2b). Upload failures become
   `AttributeError` instead of the intended `400 ValidationError`. Uncovered by the
   suite.

### Migration-procedure inconsistency (resolved)

`.env.example` and the follow-up printed by the (now removed) one-time import
command `migrate_images_to_cloudinary` both presented the rewrite step with
**no `--to`**:

```
python manage.py rewrite_image_urls --from <supabase-public-bucket-base> --strip-extension
```

`rewrite_image_urls` then derives the replacement from `_current_storage_base()`
(`rewrite_image_urls.py:227-239`), i.e. from whatever `default_storage` currently is. If
the provider was still Supabase the replacement resolved back to the Supabase base and the
"rewrite" was a silent no-op.

**Resolution:** the issue became moot — there are no images in Supabase Storage, so there
was nothing to migrate. The Supabase Storage (S3) backend, the `IMAGE_STORAGE_PROVIDER`
switch, the legacy bucket setting and the `migrate_images_to_cloudinary` command were all
removed. `rewrite_image_urls` remains as a generic "repoint image URLs after moving hosts"
tool, and documents that `--to` (plus `--strip-extension` when moving onto Cloudinary) are
required.

### Residual risks (not defects)

- `django-cloudinary-storage==0.3.0` is an old, single-release package; it imports
  successfully under Django 6 and the full app loads, but it is a maintenance risk worth
  noting.
- `CloudinaryArticleStorage` never deletes assets when an article (or its image) is
  removed, so the account accumulates orphaned images. Intentional or not, nothing
  purges them; the library's `delete_orphaned_media` command is not wired in.
- The Cloudinary backend is only exercised by unit tests for URL shape; there is no
  integration test against a real (or mocked) `cloudinary.uploader.upload` success path
  for `_save`, which is why the exception bug slipped through.
