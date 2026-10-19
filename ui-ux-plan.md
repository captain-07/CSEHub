# CSEHub — UI/UX plan

Produced from four evidence-based audits of `frontend/` (accessibility, responsive/touch,
design-system consistency, UX flows). Every item below cites the file and line it came from,
so nothing here is a matter of taste without saying so.

The starting point is better than it looks: the visual language is consistent, dark mode is
built the right way (token overrides only, no duplicated component blocks), reduced motion is
honoured in four places, the library's URL-as-state behaviour is genuinely good, and the admin
panel's focus traps / unsaved-changes guard / destructive confirms are all correct. This plan is
therefore **defects, completion and consolidation** — not a rebuild. The one structural
exception is listed as a decision at the end.

---

## Status

**Tier 1 and Tier 2 are done.** All eight Tier 1 defects and all five Tier 2 items are fixed,
and both proposed guards are in place. `node .check-imports.mjs`, `.check-assets.mjs`,
`.check-editor-tools.mjs`, `.check-video-embed.mjs`, `.check-chat-markup.mjs` and
`.check-contrast.mjs` all pass.

Decisions taken:

- Direction: **polish and fix**, not a refresh (decision 1, as recommended).
- Start point: **Tier 1 + Tier 2 as one pass** (decision 2).
- Chat rendering: **hand-rolled**, dependency-free, in `renderer.js` (decision 3) — pinned by
  the new `.check-chat-markup.mjs`, which also asserts a reply can never inject markup.
- Coordination: `frontend/` was paused, so the CSS was edited in place, including moving rules
  between stylesheets (decision 4).

Two things were fixed that the plan did not list, because the guards could not pass without
them: `.theme-icon` and `.toast-message` were rendered by `theme.js`/`toast.js` with no CSS rule
at all (a pre-existing failure in the in-flight theme/toast work). `.toast-message` genuinely
needed one — the flex row let a long unbroken string overflow the toast.

A third small item was taken from Tier 5 (5.1): the chat copy still promised "answers come only
from this article", which the deliberately-changed backend prompt contradicts. It is two strings
in the file the markdown work rewrote anyway.

Tiers 3–7 remain open.

---

## The shape of the problem

| Theme | Count | Worst case |
|---|---|---|
| Dark mode gaps and contrast failures | 9 | Sign-in button is unreadable; primary CTA is ~2.5:1 |
| Mobile / touch defects | 14 | Article body causes page-wide horizontal scroll at 320–390px |
| Reliability & feedback | 12 | Any stalled request spins forever, with no retry on the reader page |
| Reader experience | 16 | The AI assistant prints `**bold**` and ` ``` ` fences literally |
| Design-system drift | 11 | 9 card treatments, 8 pill treatments, 9 border radii for 4 tokens |
| Accessibility (beyond the above) | 13 | Closed chat drawer stays in the tab order |

Two independent audits found the same two blockers (the Google button, and white text on
`--accent`), which is why they lead Tier 1.

Effort: **S** ≈ under an hour · **M** ≈ half a day · **L** ≈ a day or more.

---

## Tier 1 — Broken right now — ✅ done

Small, high-confidence fixes. No design decisions involved; each one is a defect with a known
cause. Worth doing as a single pass.

| # | Item | Evidence | Impact | Effort |
|---|---|---|---|---|
| 1.1 | Sign-in button label is near-white on white in dark mode (**1.17:1**, hover **1.02:1**) — Google is the *only* sign-in method | `auth.css:35,41` uses `var(--text-primary)`; `style.css:129` pins the fill to `#ffffff`; `style.css:96` flips the text to `#e8efea` | Cannot sign in in dark mode | S |
| 1.2 | White text on fills that turn light in dark mode: primary CTA, danger, skip link, brand mark, the reader's own chat bubbles (**~2.5:1**) | `style.css:183,239,265`, `navbar.css:35`, `chat.css:96` vs `style.css:98,109` | Every page's main action is hard to read | S |
| 1.3 | `article.html` never loads `articles.css`, so `.eyebrow`, `.empty-state` and `.article-placeholder` render unstyled there | `article.html:30-35`; rules only at `articles.css:449-478,439-446,10-17` | "Article Not Found" renders as bare text with no card or actions | S |
| 1.4 | The chat drawer, once opened, is never hidden from the tab order or the accessibility tree | `chat.css:2-19` (offscreen only), `chat.js:48-61` toggles a class | Tab walks into an invisible Close button, input and Send | S |
| 1.5 | Three focus indicators are removed with no replacement: the editor's code textarea, the library filter controls, the reaction buttons | `admin.css:279-281`; `articles.css:133-138` (14%-alpha ring); `article.css:758-761` | Keyboard users lose their place | S |
| 1.6 | Article body has no `overflow-wrap`, so one long URL/token scrolls the whole page sideways | `article.css:453-458` (the TOC above it *does* set it, `article.css:101`) | Horizontal scroll on every phone; also breaks the admin preview | S |
| 1.7 | Form controls below 16px make iOS Safari zoom on focus (filters, nav search, chat input, editor fields) | `articles.css:119`, `navbar.css:100`, `chat.css:149`, `admin.css:270,253,313` | Viewport jumps on every field tap | S |
| 1.8 | The assistant prints markdown and fenced code literally | `chat.js:146` escapes then only converts `\n`; no `pre/code` rule in `chat.css` | The headline feature's code answers are unreadable | M |

**Guard for 1.3 and its whole class — ✅ implemented.** `.check-assets.mjs` verified a class *has*
a rule somewhere, not that the page *loads* the file holding it — which is exactly why
`article.html` slipped through. It now also walks each page: the stylesheets it links, plus the
modules reachable from *that page alone*, and fails if a class the page can render has no
substantive rule in a stylesheet that page loads. Verified against the real bug — with the
`articles.css` link removed it reports `UNSTYLED CLASS article.html .empty-state`.

Two limits are deliberate. Shared modules (`renderer.js`, `theme.js`) carry markup for several
pages at once, so holding every page that loads them to all of their output would demand
`articles.css` on `login.html`; they stay under the global "has a rule somewhere" check. And a
class only counts as styled when its rule sets something *other* than `transition` —
`body, .empty-state, .snippet { transition: … }` in `style.css` is not a definition, and treating
it as one is precisely how `.empty-state` shipped unstyled. (M)

---

## Tier 2 — Finish dark mode — ✅ done

Dark mode is a day old and architecturally right; these are the parts the token override does
not reach.

| # | Item | Evidence | Effort |
|---|---|---|---|
| 2.1 | Introduce `--on-accent` / `--on-error` / `--google-btn-text` and use them, instead of hardcoded `white` and theme-flipping text | the five consumers in 1.1–1.2 | S |
| 2.2 | Editor.js chrome is unthemed: block toolbar, `+`/settings popovers and placeholder text come from the CDN's light stylesheet | `admin.css:200-217` is the *only* Editor.js rule; `admin.html:82` loads the light build | M |
| 2.3 | Scrims and shadows ignore the theme (modal backdrop hardcodes the light shade); the reading-progress gradient's end colour is frozen | `admin.css:384`, `chat.css:10,27`, `navbar.css:8`, `article.css:589,721`, `article.css:12` | S |
| 2.4 | Light-mode status text is marginally under 4.5:1 (Published 4.15:1, Draft 3.88:1, status 4.39:1) | `style.css:544-552,571` | S |
| 2.5 | `.chat-input` and `.nav-search-input` set a themed background but no foreground | `chat.css:143-151`, `navbar.css:92-102` | S |

**Guard — ✅ implemented.** `.check-contrast.mjs` reads both palettes out of `style.css`,
composites translucent values over the surface behind them, and asserts 4.5:1 for 19 pairs the
site actually renders, in both themes. It is what caught the three light-mode failures in 2.4 and
it is the only check that can see 1.1/1.2 at all — no other check reads a colour. (M)

---

## Tier 3 — Mobile & touch

The site has exactly three breakpoints (768 ×10, 900 ×6, 1080 ×3) and **no tier below 768**, so
"mobile" is one bucket covering a 320px phone and a 768px tablet alike.

| # | Item | Evidence | Effort |
|---|---|---|---|
| 3.1 | The `<select multiple>` tag picker cannot be used on touch — tapping a second option clears the first, and the hint says "Hold Ctrl/Cmd" | `admin.js:889-890`; `style.css:474-477` | M |
| 3.2 | Chat drawer uses `100vh` and is covered by the on-screen keyboard; overlay uses `100vw` (adds a scrollbar); the page behind it still scrolls | `chat.css:2-15,21-27`; `chat.js:48-61` | M |
| 3.3 | Mobile nav links have no padding — the tap target is the text height | `navbar.css:52-62` vs the ≤768 block at `210-234` | S |
| 3.4 | Hamburger, chat close and toast close are all ~17–24px | `navbar.css:152-159`, `chat.css:59-66`, `style.css:405-414` | S |
| 3.5 | Admin article table is 34rem wide in a ~264px panel; row actions are off-screen behind a thin scrollbar | `admin.css:68-77,494-496` | M |
| 3.6 | Tag chips and filter chips are ~17–24px with ~5.6px gaps — on `categories.html` the tag cloud *is* the navigation | `articles.css:378-398,200-214` | S |
| 3.7 | Hero keeps `padding: 5.7rem 0 4.3rem` on phones; `auth.css` has no media query at all | `articles.css:6-8`, `auth.css:2-10` | S |
| 3.8 | Card cover images are hard-cropped to 170px in the one-column layout; long titles are clipped without ellipsis | `articles.css:277-283,335-341,248` | S |
| 3.9 | Add a sub-768 tier (~480) and make the component-level breakpoints consistent — related-grid drops to one column at 900 while the sibling grids do it at 768 | `article.css:1011` vs `articles.css:588,608` | M |

---

## Tier 4 — Trust & feedback

| # | Item | Evidence | Effort |
|---|---|---|---|
| 4.1 | No fetch timeout anywhere — a stalled connection spins forever on every page (the code already anticipates `AbortError` but never creates a controller) | `api.js:48-54` | S |
| 4.2 | The reader page has no retry; a transient blip costs the article (the library page already has one) | `article.js:400-408` vs `articles.js:123,266` | S |
| 4.3 | Error copy is inconsistent and leaks HTTP status: a 500 shows "API request failed with status 500". `friendlyError` exists but only in `admin.js`; `chat.js` has a third mapping | `api.js:86-90`, `admin.js:139`, `chat.js:203-212` | M |
| 4.4 | Debounced search pushes a history entry per pause, so Back walks through "sor", "sor", "sortin"… | `articles.js:300,311-315` | S |
| 4.5 | Publish/unpublish/delete rows and taxonomy "Add" have no busy state — double-click fires two requests, the second failing on the unique constraint | `admin.js:500-536,726-745` | S |
| 4.6 | Image uploads surface the provider's raw error and are not size-checked client-side | `admin.js:928-939` | S |
| 4.7 | Retry is missing from `home.js` and `categories.js` too; failure states reuse the search-magnifier icon | `home.js:60-68`, `categories.js:100-105`, `renderer.js:604` | S |

---

## Tier 5 — Reader experience

| # | Item | Evidence | Effort |
|---|---|---|---|
| 5.1 | Chat copy promises "grounded in this article only" / "My answers come only from this article", which the (deliberately changed) backend prompt contradicts | `chat.js:89,186` vs `rag_chat.py:22-32,78-100` | S |
| 5.2 | Signed-out readers never see a reaction control or a sign-in invitation — the container is hidden when empty, while the AI CTA does invite them | `reactions.js:36-40`, `article.css:677` vs `article.js:371-377` | S |
| 5.3 | The article page shows a centred spinner then swaps in the whole article (the biggest layout shift on the busiest page); the library skeleton shows 6 cards for a 20-card page | `article.js:323`, `articles.js:202`, `settings.py:282` | M |
| 5.4 | Home's "Explore by subject" has no loading state and pops in, pushing the next section down; login shows a bare heading until the session check settles | `home.js:71-90`, `index.html:76-82`, `login.html:49` | S |
| 5.5 | When related/pager requests fail they vanish silently, so an article can end with no onward suggestion | `article.js:150-152,200-202` | S |
| 5.6 | Two visually-identical search boxes on the library page that behave differently (one reloads, one filters in place) | `navbar.js:36-51` vs `articles.html:49-52` | S |
| 5.7 | No active nav state while reading an article; the tab title never reflects search state; a deep link with `#section` does not jump | `navbar.js:114-120`, `articles.html:7`, `article.js:34-57` | S |
| 5.8 | Empty/error states on home offer no next action, unlike the library's | `home.js:7-13,60-68` | S |
| 5.9 | Editor-facing copy leaks implementation ("vector store", "chunks embedded", "Update AI index") | `admin.js:909,1136,1140,1146` | S |

---

## Tier 6 — Design-system consolidation

This touches nearly every page, so it should come after the visible fixes.

| # | Item | Evidence | Effort |
|---|---|---|---|
| 6.1 | 9 card treatments with radii of 10/12/14/16px/`--radius-lg` and both 1px and 1.5px borders | `articles.css:240,67,523`; `article.css:905,135`; `admin.css:37`; `profile.css:7`; `auth.css:2`; `style.css:300` | L |
| 6.2 | 8 pill treatments with no shared base (`.badge` vs `.badge-staff`/`.badge-reader`/`.reading-time-badge`/`.field-optional` duplicate the same six declarations) | `style.css:532,486`; `profile.css:68-87`; `article.css:286-296` | M |
| 6.3 | 9 distinct border radii for a 4-token scale; off-token 8/10/14/16/100px values in 7 files | `style.css:80-83` vs 15 sites | M |
| 6.4 | The `.tag`/`.tag-list` component is defined twice with drifted values | `articles.css:378-398` vs `article.css:428-450` | S |
| 6.5 | Two parallel form-label systems (`.field`/`.field-label` in admin, `.form-group`/`.form-label` in profile) that differ in label size and margins | `style.css:432-498` vs `502-514` | M |
| 6.6 | The code-snippet dark palette is hand-duplicated three times and drifts (bar border `#2d3d36` vs `#32413a`); `syntax.css` uses 11 raw hex values | `article.css:583-661`; `admin.css:224-255`; `syntax.css:29-97` | M |
| 6.7 | Dead code: unused tokens (`--error-rgb`, `--space-2xl`, `--text-4xl`), 5 dead selectors (`.badge-draft/published`, `.chat-message-meta`, `.text-center`, `.text-secondary`), a vestigial `.back-link`, and `alert-info` used but never styled | as listed | S |
| 6.8 | `.admin-filters` overrides `.filters` purely by load order; `.article-card-body > p:not(…)` misses any new paragraph class; `transition: all` on `.button` | `admin.css:168-170` vs `articles.css:97-108`; `articles.css:364`; `style.css:235` | S |
| 6.9 | Hardcoded `76px` header offsets in four places; ~150 literal spacing declarations and ~22 off-scale font sizes across the component files | `navbar.css:220`, `article.css:58,64`, `admin.css:439`; per-file counts in the audit | M |

---

## Tier 7 — Accessibility sweep

Mechanical, and mostly copy/wiring rather than layout.

| # | Item | Evidence |
|---|---|---|
| 7.1 | Card images jump `h1 → h3` on the library page; article bodies can emit a second `h1` | `articles.js:242-246`; `renderer.js:264,307-309` |
| 7.2 | Alt text: uncaptioned inline images say "Article image"; captioned ones are announced twice; the hero repeats the `<h1>` | `renderer.js:242-243`; `article.js:357` |
| 7.3 | Filter/paging results are never announced (skeletons are `aria-hidden`, the count is not a live region) | `articles.js:202,241-251`; `renderer.js:620` |
| 7.4 | Active nav link is colour-only (no `aria-current="page"`, unlike the admin nav) | `navbar.js:115-143`; `navbar.css:69-71` vs `admin.js:369` |
| 7.5 | Emoji read aloud before their value (⏱ 👁 👍); `target="_blank"` links never warn | `article.js:351-352`; `renderer.js:588,591`; `renderer.js:63,251,503` |
| 7.6 | Profile save errors are silent to AT (no `role="alert"`, unlike the load error); hints and invalid fields are not wired to inputs | `profile.js:216-220` vs `37`; `profile.js:102-106` |
| 7.7 | Admin tables have no `<caption>`; the two tables have identical headers on one route | `admin.js:475-480,595-600` |
| 7.8 | The code-block language label reuses one hardcoded `id`, so it collides with ≥2 blocks | `code-block.js:129,133` |
| 7.9 | Disabled pagination is `aria-disabled` on a bare `<span>` (ignored by AT) | `articles.js:96,100`; `admin.js:606,610` |
| 7.10 | Toasts auto-dismiss at 4.2s with no way to hold them; the chat dialog's accessible name is the article title, not "Learning assistant"; the editor's "Content" label is a `<span>`, unassociated with the editor; repeated context-free "Read article →" / "Browse →" link text | `toast.js:58,17`; `chat.js:71,75`; `admin.js:895-896`; `renderer.js:598`; `categories.js:97` |

---

## Definition of done, per change

- `node .check-imports.mjs`, `.check-assets.mjs`, `.check-editor-tools.mjs`, `.check-video-embed.mjs`
  (plus the two proposed checks, if adopted) all pass.
- Manual pass at **360 / 390 / 768 / 1024 / 1440px**, in **both themes**, for anything in
  Tiers 1–3.
- Keyboard-only pass (Tab/Shift-Tab/Escape) for anything in Tiers 1 and 7.
- No new hardcoded colour in a component file — a token, or a `rgba(var(--…-rgb), …)`.
- `python backend/manage.py test apps.articles apps.users apps.chatbot` still green before any
  backend-touching item (none are proposed here).

---

## Decisions I need from you

1. **Direction** — is this polish-and-fix, or do you want a visual refresh on top (new
   typography scale, spacing rhythm, page layouts)? The audits found the visual language
   coherent, so my recommendation is polish-and-fix, with Tier 6 as the only structural work.
2. **Where to start** — I recommend Tier 1 + Tier 2 as one pass (they overlap: 1.1/1.2 *are*
   dark mode), because it is small, unambiguous, and finishes the feature you just shipped.
3. **Chat rendering** — hand-rolled fenced-code + inline-code + bold rendering (dependency-free,
   matching the repo's no-build ethos) or a CDN library (marked + DOMPurify)? Hand-rolled is my
   recommendation: the backend prompt only invites code and emphasis, and the existing
   `escapeHtml` allow-list pattern means no new trust boundary.
4. **Coordination** — you are mid-edit across most of `frontend/` (`theme.js`, `toast.js`,
   every HTML page, `style.css` +272). Tell me when you've paused, or I'll keep my edits
   surgical and flag anything that touches a file you're in.

## Explicitly not in scope

- Anything that requires a build step or a framework — the site is deliberately dependency-free.
- Backend behaviour. The two RAG-related items here (5.1, 5.9) are *copy* changes only.
- A full contrast audit of every pair; Tier 2 covers the failures the audits measured and the
  proposed check script covers the rest automatically.
