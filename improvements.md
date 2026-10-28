# CSEHub — UI/UX Improvement Blueprint

This document tracks planned and in-progress user interface and user experience enhancements across CSEHub, spanning the public reader surface, discovery workflows, and the admin publishing suite.

---

## Implemented Enhancements (Current Sprint)

### ✅ 2. AI Learning Assistant Enhancements
- **Contextual Selection Trigger ("Ask AI")**: Readers can highlight any sentence or code snippet in the article body. A floating `✨ Ask AI` chip appears immediately adjacent to the selection; clicking it opens the assistant drawer and submits the question quoting the selected text.
- **Suggested Starter Prompt Chips**: When the conversation opens with an empty history, interactive suggestion chips appear (💡 *Core intuition*, ⏱️ *Complexity breakdown*, 🧪 *Quiz my understanding*, 💻 *Practical code example*). Tapping any chip immediately fires the prompt.
- **Code Block Chrome & Syntax Highlighting in Chat**: Assistant code responses now carry a dark header bar with a language badge and a one-click copy button with clipboard feedback (`Copied!`), styled to match the main article snippets and highlighted via Highlight.js.
- **Organic Typing Indicator**: Replaced static dots with an aligned assistant chat bubble featuring an animated dot wave and status accessibility.

---

## Remaining UI/UX Improvements Roadmap

### 1. Core Reader Experience

- **[ ] Tabbed Multi-Language Code Snippets**
  - **Why**: Algorithms and data structures articles benefit from showing parallel implementations (e.g., Python, C++, Java, Go) without stacking massive sequential blocks.
  - **What**: Render multi-language code snippets with tab pills so readers can toggle between language implementations in-place.
  - **Where**: `frontend/js/renderer.js`, `frontend/css/syntax.css`, `frontend/css/article.css`.

- **[ ] Code Snippet Utilities**
  - **Why**: Long algorithms require line tracking; horizontal scrolling on mobile can be clunky.
  - **What**: Add line number display toggle, wrap toggle, and an external sandbox link ("Run in Playground" via OneCompiler / Pyodide / CodeSandbox).
  - **Where**: `frontend/js/renderer.js`, `frontend/css/syntax.css`.

- **[ ] Active TOC Scroll-Spy Polish**
  - **Why**: The table of contents highlights sections on scroll, but smooth transition animations and collapsible sub-headings (h3 under h2) improve spatial orientation for 3000+ word guides.
  - **Where**: `frontend/js/article.js`, `frontend/css/article.css`.

- **[ ] Reading Difficulty & Prerequisites Badges**
  - **Why**: Readers need to assess whether an article is suitable for beginners or expects compiler / OS internals knowledge.
  - **What**: Display `Beginner` / `Intermediate` / `Advanced` badges on article headers and cards.
  - **Where**: `backend/apps/articles/models.py`, `frontend/js/renderer.js`, `frontend/css/articles.css`.

- **[ ] Reader Display Controls (Font & Spacing)**
  - **Why**: Accessibility for dyslexic readers or users reading on large monitors.
  - **What**: Discrete reader settings dropdown for font sizing (A- / A+) and line length toggle.
  - **Where**: `frontend/article.html`, `frontend/js/article.js`, `frontend/css/article.css`.

---

### 3. Discovery, Navigation & Search

- **[ ] Instant Global Command Palette (`Cmd/Ctrl + K`)**
  - **Why**: Experienced users navigate by keyboard. Searching currently requires navigating to `articles.html` and submitting a form.
  - **What**: A floating command modal opened by `Cmd+K` or `/` that live-queries articles, subjects, tags, and theme toggle actions.
  - **Where**: `frontend/js/navbar.js`, new `frontend/js/command-palette.js`, `frontend/css/navbar.css`.

- **[ ] Live Debounced Filtering & Active Filter Chips**
  - **Why**: On `articles.html`, users must manually press the "Apply" button to filter results.
  - **What**: Debounce search input (300ms) for instant results; add active removable filter chips (`[ DSA ✕ ]`, `[ Tree ✕ ]`, `[ Clear all ]`).
  - **Where**: `frontend/js/articles.js`, `frontend/css/articles.css`.

- **[ ] Zero-State Recovery on Empty Search**
  - **Why**: A failed search shows "No articles found" with no actionable next steps.
  - **What**: Provide "Did you mean?", popular tags, and quick links back to major subject categories.
  - **Where**: `frontend/js/articles.js`.

---

### 4. Visual Aesthetics & Micro-Interactions

- **[ ] Hero Section Interactive Visual Teaser**
  - **Why**: Landing page hero should immediately showcase technical depth.
  - **What**: Add an interactive code snippet or dynamic concept visualizer (e.g. binary tree traversal animation or syntax-highlighted code preview) beside the hero copy on `index.html`.
  - **Where**: `frontend/index.html`, `frontend/css/articles.css`.

- **[ ] Visual Subject Category Cards**
  - **Why**: Plain category buttons don't feel inspiring.
  - **What**: Custom CS iconography and cards for primary subjects (Data Structures, Algorithms, Operating Systems, Computer Networks, Database Systems, Compilers).
  - **Where**: `frontend/categories.html`, `frontend/css/articles.css`.

- **[ ] Shimmer Skeleton Loading States**
  - **Why**: Replaces jumpy "Loading articles..." spinners with layout-matched skeleton placeholder cards to prevent Cumulative Layout Shift (CLS).
  - **Where**: `frontend/js/renderer.js`, `frontend/css/style.css`, `frontend/css/articles.css`.

---

### 5. Personalization & Retention

- **[ ] Bookmarks / "Read Later"**
  - **Why**: Learners often discover articles they want to read later.
  - **What**: Bookmark icon on cards and article headers. Stored in `localStorage` for guests, and synced to Supabase profile for authenticated users.
  - **Where**: `frontend/js/article.js`, `frontend/js/profile.js`, `frontend/profile.html`.

- **[ ] Reading History & Completion Indicators**
  - **Why**: Tracks reading progress across topics.
  - **What**: Displays "Recently viewed" rail on home/profile and subtle checkmarks on completed articles.
  - **Where**: `frontend/js/profile.js`, `frontend/js/home.js`.

- **[ ] Curated Learning Roadmaps**
  - **Why**: Beginners often don't know which article to read next.
  - **What**: Structured sequencing (e.g., *DSA: Arrays → Linked Lists → Trees → Graphs*).
  - **Where**: New roadmap view or category rail.

---

### 6. Admin & Authoring Experience (Editor UX)

*(See deep-dive section below for comprehensive breakdown)*
- **[ ] Real-time Word Count, Character Count & Estimated Reading Time in Header**
- **[ ] Local Draft Auto-save (`localStorage`) with Disaster Recovery Banner**
- **[ ] Split-Screen Live Preview Mode**
- **[ ] Direct Drag-and-Drop Image Uploading into Editor**
- **[ ] Slug Auto-Generation with Manual Override & Duplicate Warning**
- **[ ] Block Reordering & Keyboard Shortcut Palette (`/` Slash Commands)**
- **[ ] Unsaved Changes Navigation Guard (`beforeunload`)**
