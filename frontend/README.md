# CSEHub frontend

Dependency-free static client for CSEHub. No build step, no bundler, no npm
install — plain ES modules and CSS.

## Run locally

From the repository root:

```powershell
python -m http.server 3000 --directory frontend
```

Open `http://localhost:3000`. Run Django separately on port 8000.

`js/config.js` automatically targets `http://127.0.0.1:8000` when the page is
served from localhost, and the deployed API otherwise.

## Configuration

`js/config.js` holds the three public values. Override any of them by defining a
global before the module scripts load:

```html
<script>
  window.CSEHUB_API_BASE_URL = "http://127.0.0.1:8000";
  window.CSEHUB_SUPABASE_URL = "https://your-project.supabase.co";
  window.CSEHUB_SUPABASE_ANON_KEY = "sb_publishable_…";
</script>
```

`API_BASE_URL` may be either the backend origin or its `/api` URL; pagination
links returned by DRF are followed directly and never produce `/api/api/...`.

> Only the Supabase **publishable** (or legacy `anon`) key belongs here. The
> service-role key and the JWT secret must never be shipped to a browser.

## Architecture

One implementation per concern:

| Concern          | File                                          |
| ---------------- | --------------------------------------------- |
| HTTP client      | `js/api.js`                                   |
| Endpoint bindings| `js/api/articles.js`                          |
| Supabase client  | `js/supabase.js`                              |
| Auth state       | `js/auth-state.js`                            |
| OAuth / logout   | `js/auth.js`                                  |
| Article rendering| `js/renderer.js`                              |
| Navbar           | `js/navbar.js`                                |
| Admin panel      | `js/admin.js` (hash-routed)                   |

### XSS

`js/renderer.js` is the only place article content becomes HTML. Every value is
escaped; block types are dispatched through an allow-list; heading levels are
clamped; URLs are restricted to `http(s)`; and inline markup inside block text
(Editor.js bold/italic/link/inline-code) is re-admitted only from a small tag
list, with attributes stripped. Nothing injects untrusted HTML.

## Supabase redirect URLs

OAuth lands back on `index.html`. Add every frontend origin to
**Authentication → URL Configuration → Redirect URLs** in the Supabase dashboard.