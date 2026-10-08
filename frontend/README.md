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
| Editor tools     | `js/editor-tools/registry.js` (+ `code-block`, `list-block`, `link-block`) |

### Editor tools and save safety

`js/editor-tools/registry.js` is the single source of truth for which block types
the admin editor can edit. Tool availability is measured, not declared: a CDN
script that fails to load or renames its export makes that block type
*unavailable*, and the registry reports it.

That matters because Editor.js silently drops blocks whose tool is missing when
it saves — it renders them as `ce-stub` placeholders and then omits them from the
saved document. Before saving an existing article the panel compares the block
types in the stored document against the tools that actually loaded; if any
cannot be represented it refuses the save, names the block types, and leaves the
article untouched.

Two block types are local tools rather than CDN packages:

* **code** — `@editorjs/code` saves only `{code}` and drops the stored
  `language` that `js/renderer.js` and the API both rely on.
* **list** — neither `@editorjs/list` release reads the stored item shape
  `items: [{ content }]`. list 2.x throws while rendering it; list 1.x renders
  and re-saves it as `[object Object]`. `js/editor-tools/list-block.js` adapts
  list 1.x at the boundary so the stored schema is unchanged.

### XSS

`js/renderer.js` is the only place article content becomes HTML. Every value is
escaped; block types are dispatched through an allow-list; heading levels are
clamped; URLs are restricted to `http(s)`; and inline markup inside block text
(Editor.js bold/italic/link/inline-code) is re-admitted only from a small tag
list, with attributes stripped. Nothing injects untrusted HTML.

## Supabase redirect URLs

OAuth lands back on `index.html`. Add every frontend origin to
**Authentication → URL Configuration → Redirect URLs** in the Supabase dashboard.