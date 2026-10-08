/**
 * CSEHub admin panel.
 *
 * Authorization: the `is_admin` value used here comes from `GET /api/me/`
 * (see auth-state.js) — never from local storage, a URL flag, or an email
 * comparison. Hiding the UI is only UX; the API independently enforces
 * `IsAdminUser` on every write.
 *
 * Routing: hash routes keep the panel a single page while still giving each
 * view a real, linkable URL.
 *   #/                     dashboard
 *   #/articles             article list
 *   #/articles/new         create article
 *   #/articles/:id/edit    edit article
 *   #/taxonomy             categories & tags
 */

import { initNavbar } from './navbar.js';
import { initAuth, getAuthState } from './auth-state.js';
import {
  getArticles, getArticle, getCategories, getTags,
  createArticle, updateArticle, deleteArticle, reindexArticle,
  createCategory, deleteCategory, createTag, deleteTag,
  uploadImage, normalizePage,
} from './api/articles.js';
import { ApiError } from './api.js';
import {
  renderArticleContent, escapeHtml, safeUrl, formatDate, contentToPlainText,
} from './renderer.js';

const app = document.querySelector('#admin-app');

let editor = null;
let taxonomy = { categories: [], tags: [] };

/* ------------------------------------------------------------- utilities */

/** Editor.js and its tools attach to `window` via classic script tags. */
const EDITOR_VERSION = '2.30.8';
const MISSING_TOOLS = [['ImageTool', 'images']];

function editorToolsAvailable() {
  return typeof window.EditorJS === 'function';
}

function destroyEditor() {
  if (editor && typeof editor.destroy === 'function') {
    try {
      editor.destroy();
    } catch (error) {
      console.warn('Editor teardown failed', error);
    }
  }
  editor = null;
}

function statusMessage(text, kind = 'info') {
  const el = document.querySelector('#admin-status');
  if (!el) return;
  el.className = text ? `alert alert-${kind}` : '';
  el.textContent = text || '';
}

function friendlyError(error) {
  if (error instanceof ApiError) {
    // Prefer the API's own wording; it distinguishes "no credentials were sent"
    // from "the token was rejected", which are very different problems.
    if (error.status === 401) return error.message || 'Your session has expired. Sign in again to continue.';
    if (error.status === 403) return 'You are not authorised to perform that action.';
    if (error.status === 0) return error.message || 'Cannot reach the CSEHub API. Check your connection.';
    const details = error.details;
    if (details && typeof details === 'object') {
      const first = Object.entries(details)[0];
      if (first) return `${Array.isArray(first[1]) ? first[1][0] : first[1]}`;
    }
    return error.message;
  }
  return error?.message || 'Something went wrong.';
}

function statCard(label, value) {
  return `<div class="admin-stat"><strong>${escapeHtml(String(value))}</strong><span>${escapeHtml(label)}</span></div>`;
}

function loadingMarkup(message = 'Loading…') {
  return `<div class="loading"><span class="loading-spinner"></span>${escapeHtml(message)}</div>`;
}

function failureMarkup(message) {
  return `
    <div class="empty-state" role="alert">
      <h2>Unable to load</h2>
      <p>${escapeHtml(message)}</p>
      <a class="button button-secondary" href="#/">Back to dashboard</a>
    </div>`;
}

/** Replaces window.confirm so the panel has one consistent confirmation style. */
function confirmAction({ title, message, confirmLabel = 'Confirm', destructive = false }) {
  return new Promise((resolve) => {
    const existing = document.querySelector('#confirm-modal');
    if (existing) existing.remove();

    const modal = document.createElement('div');
    modal.id = 'confirm-modal';
    modal.className = 'modal-backdrop';
    modal.innerHTML = `
      <div class="modal modal-narrow" role="alertdialog" aria-modal="true" aria-labelledby="confirm-title">
        <div class="modal-body">
          <h2 id="confirm-title">${escapeHtml(title)}</h2>
          <p class="confirm-message">${escapeHtml(message)}</p>
          <div class="admin-toolbar">
            <button class="button button-secondary" type="button" data-cancel>Cancel</button>
            <button class="button ${destructive ? 'button-danger' : 'button-primary'}" type="button" data-confirm>${escapeHtml(confirmLabel)}</button>
          </div>
        </div>
      </div>`;

    const close = (result) => {
      modal.remove();
      document.removeEventListener('keydown', onKey);
      resolve(result);
    };
    const onKey = (event) => {
      if (event.key === 'Escape') close(false);
    };

    document.body.appendChild(modal);
    modal.querySelector('[data-cancel]').addEventListener('click', () => close(false));
    modal.querySelector('[data-confirm]').addEventListener('click', () => close(true));
    modal.addEventListener('click', (event) => {
      if (event.target === modal) close(false);
    });
    document.addEventListener('keydown', onKey);
    modal.querySelector('[data-confirm]').focus();
  });
}

async function notify(title, message, kind = 'info') {
  const ok = await confirmAction({ title, message, confirmLabel: 'OK', destructive: kind === 'error' });
  if (ok) statusMessage(title, kind === 'error' ? 'error' : 'success');
}

/* ---------------------------------------------------------------- routing */

/**
 * Resolves the current view from the hash. Unknown routes fall back to the
 * dashboard so a stale bookmark never renders a blank panel.
 */
function parseRoute() {
  const path = window.location.hash.replace(/^#\/?/, '');
  const segments = path.split('/').filter(Boolean);

  if (!segments.length) return { view: 'dashboard' };
  if (segments[0] === 'taxonomy' && segments.length === 1) return { view: 'taxonomy' };

  if (segments[0] === 'articles') {
    if (segments.length === 1) return { view: 'articles' };
    if (segments[1] === 'new' && segments.length === 2) return { view: 'article-form', id: null };
    if (segments[1] && segments[2] === 'edit') return { view: 'article-form', id: segments[1] };
  }

  return { view: 'dashboard' };
}

function navigate(hash) {
  if (window.location.hash === hash) {
    renderRoute();
    return;
  }
  window.location.hash = hash;
}

let currentRoute = null;

/** Guards against a slow request for a view the user has already navigated away from. */
function routeIsCurrent(route) {
  return currentRoute === route;
}

async function renderRoute() {
  const route = parseRoute();
  currentRoute = `${route.view}:${route.id ?? ''}`;

  const renderers = {
    dashboard: renderDashboard,
    articles: renderArticleList,
    taxonomy: renderTaxonomy,
    'article-form': () => renderArticleForm(route.id),
  };

  const render = renderers[route.view] || renderDashboard;
  await render();
}

/* ---------------------------------------------------------- data helpers */

async function loadTaxonomy() {
  const [categories, tags] = await Promise.all([getCategories(), getTags()]);
  taxonomy = { categories, tags };
  return taxonomy;
}

/* ---------------------------------------------------------------- guard */

async function guard() {
  await initAuth();
  // initAuth resolves only after the session and profile have settled, so
  // `ready` is true by this point.
  const { user, profile, profileError } = getAuthState();

  if (!user) {
    window.location.href = 'login.html?redirect=' + encodeURIComponent('admin.html');
    return false;
  }

  // A Supabase session with no backend profile means the API rejected the
  // request. Refuse rather than silently showing an empty dashboard.
  if (!profile) {
    app.innerHTML = failureMarkup(
      profileError
        ? `Signed in, but the server could not confirm your account: ${friendlyError(profileError)}`
        : 'The server did not return a profile for this account.'
    );
    return false;
  }

  if (!profile.is_admin) {
    app.innerHTML = `
      <div class="empty-state" role="alert">
        <h2>Admin access required</h2>
        <p>This area is limited to CSEHub editors. Your account is signed in but does not have publishing rights.</p>
        <a class="button button-secondary" href="index.html">Return home</a>
      </div>`;
    return false;
  }

  return true;
}

/** Navigation shared by every admin view. */
function adminNav(active) {
  const link = (hash, label) =>
    `<a class="admin-nav-link${active === label ? ' is-active' : ''}" href="${hash}"${active === label ? ' aria-current="page"' : ''}>${label}</a>`;

  return `
    <nav class="admin-nav" aria-label="Admin sections">
      ${link('#/', 'Dashboard')}
      ${link('#/articles', 'Articles')}
      ${link('#/articles/new', 'New article')}
      ${link('#/taxonomy', 'Categories & tags')}
    </nav>`;
}

/* ------------------------------------------------------------ dashboard */

/**
 * Dashboard statistics.
 *
 * The listing endpoint is paginated, so the totals come from a full scan of the
 * collection rather than from one page of results — a dashboard that reports
 * "24 articles" when there are 240 is worse than no dashboard.
 */
async function fetchAllArticles() {
  const collected = [];
  let page = 1;
  let total = 0;

  for (let guard = 0; guard < 25; guard += 1) {
    const payload = normalizePage(await getArticles({ page, ordering: '-created_at' }));
    collected.push(...payload.results);
    total = payload.count;
    if (!payload.next || payload.results.length === 0) break;
    page += 1;
  }
  return { articles: collected, total };
}

function articleRow(article) {
  return `
    <tr>
      <td>
        <a class="admin-article-link" href="#/articles/${article.id}/edit">${escapeHtml(article.title)}</a>
        <span class="admin-article-slug">/${escapeHtml(article.slug)}</span>
      </td>
      <td>
        <span class="status ${article.is_published ? 'status-published' : 'status-draft'}">
          ${article.is_published ? 'Published' : 'Draft'}
        </span>
        ${article.is_featured ? '<span class="badge">Featured</span>' : ''}
      </td>
      <td>${escapeHtml(article.category?.name || 'General')}</td>
      <td>${escapeHtml(formatDate(article.updated_at))}</td>
      <td class="admin-actions">
        <a class="button button-secondary" href="#/articles/${article.id}/edit">Edit</a>
        <button class="button button-secondary" type="button" data-toggle="${article.id}" data-published="${article.is_published ? '1' : '0'}">
          ${article.is_published ? 'Unpublish' : 'Publish'}
        </button>
        <button class="button button-danger" type="button" data-delete="${article.id}" data-title="${escapeHtml(article.title)}">Delete</button>
      </td>
    </tr>`;
}

/** Wires the shared edit/publish/delete controls in any table. */
function bindArticleRowActions(root) {
  root.querySelectorAll('[data-toggle]').forEach((el) =>
    el.addEventListener('click', () => togglePublish(el.dataset.toggle, el.dataset.published === '1'))
  );
  root.querySelectorAll('[data-delete]').forEach((el) =>
    el.addEventListener('click', () => removeArticle(el.dataset.delete, el.dataset.title))
  );
}

function dashboardMarkup({ articles, total }) {
  const published = articles.filter((a) => a.is_published).length;
  const recent = articles.slice(0, 8);

  return `
    ${adminNav('Dashboard')}
    <section class="admin-heading">
      <div>
        <p class="eyebrow">CSEHub publishing</p>
        <h1>Dashboard</h1>
      </div>
      <a class="button button-primary" href="#/articles/new">New article</a>
    </section>

    <section class="admin-stats">
      ${statCard('Total articles', total)}
      ${statCard('Published', published)}
      ${statCard('Drafts', total - published)}
      ${statCard('Categories', taxonomy.categories.length)}
    </section>

    <section class="admin-panel">
      <div class="results-heading">
        <h2>Recent articles</h2>
        <a class="text-link" href="#/articles">Manage all articles →</a>
      </div>
      <div class="admin-table-wrap">
        <table class="admin-table">
          <thead>
            <tr><th>Title</th><th>Status</th><th>Category</th><th>Updated</th><th>Actions</th></tr>
          </thead>
          <tbody>${recent.map(articleRow).join('') || '<tr><td colspan="5">No articles yet. Create your first one.</td></tr>'}</tbody>
        </table>
      </div>
    </section>`;
}

async function renderDashboard() {
  const route = currentRoute;
  app.innerHTML = loadingMarkup('Loading dashboard…');
  try {
    await loadTaxonomy();
    const { articles, total } = await fetchAllArticles();
    if (!routeIsCurrent(route)) return;
    app.innerHTML = dashboardMarkup({ articles, total });
    bindArticleRowActions(app);
  } catch (error) {
    if (!routeIsCurrent(route)) return;
    app.innerHTML = failureMarkup(friendlyError(error));
  }
}

async function togglePublish(id, isPublished) {
  const verb = isPublished ? 'unpublish' : 'publish';
  const ok = await confirmAction({
    title: isPublished ? 'Unpublish this article?' : 'Publish this article?',
    message: isPublished
      ? 'It will no longer be visible to readers or indexed for the AI assistant.'
      : 'It will become publicly visible. Remember to update the AI index afterwards.',
    confirmLabel: isPublished ? 'Unpublish' : 'Publish',
  });
  if (!ok) return;

  try {
    await updateArticle(id, { is_published: !isPublished });
    statusMessage(`Article ${verb}ed.`, 'success');
    await renderRoute();
  } catch (error) {
    await notify('Could not change publication state', friendlyError(error), 'error');
  }
}

async function removeArticle(id, title) {
  const ok = await confirmAction({
    title: 'Delete this article?',
    message: `"${title}" will be permanently removed, including its content. This cannot be undone.`,
    confirmLabel: 'Delete permanently',
    destructive: true,
  });
  if (!ok) return;

  try {
    await deleteArticle(id);
    statusMessage('Article deleted.', 'success');
    await renderRoute();
  } catch (error) {
    await notify('Could not delete the article', friendlyError(error), 'error');
  }
}

/* ------------------------------------------------------- article listing */

const LIST_PAGE_SIZE = 20;

function listStateFromQuery() {
  const query = new URLSearchParams(window.location.search);
  const status = query.get('status');
  return {
    search: query.get('q') || '',
    status: ['published', 'draft'].includes(status) ? status : '',
    page: Math.max(1, Number(query.get('page')) || 1),
  };
}

function articleListMarkup({ page, state, total }) {
  const first = (state.page - 1) * LIST_PAGE_SIZE + 1;
  const last = Math.min(state.page * LIST_PAGE_SIZE, total);

  // Preserve the other filters when moving between pages.
  const href = (pageNumber, overrides = {}) => {
    const next = { ...state, ...overrides, page: pageNumber };
    const params = new URLSearchParams();
    if (next.search) params.set('q', next.search);
    if (next.status) params.set('status', next.status);
    if (next.page > 1) params.set('page', String(next.page));
    const query = params.toString();
    return `admin.html${query ? `?${query}` : ''}#/articles`;
  };

  return `
    ${adminNav('Articles')}
    <section class="admin-heading">
      <div>
        <p class="eyebrow">CSEHub publishing</p>
        <h1>Articles</h1>
      </div>
      <a class="button button-primary" href="#/articles/new">New article</a>
    </section>

    <form class="filters admin-filters" id="admin-filters" role="search">
      <label class="search-field">
        <span class="sr-only">Search articles</span>
        <input name="q" type="search" value="${escapeHtml(state.search)}" placeholder="Search by title or excerpt" autocomplete="off" />
      </label>
      <label>
        <span class="sr-only">Status</span>
        <select name="status">
          <option value=""${state.status === '' ? ' selected' : ''}>All statuses</option>
          <option value="published"${state.status === 'published' ? ' selected' : ''}>Published</option>
          <option value="draft"${state.status === 'draft' ? ' selected' : ''}>Drafts</option>
        </select>
      </label>
      <button class="button button-primary" type="submit">Search</button>
    </form>

    <section class="admin-panel">
      <div class="admin-table-wrap">
        <table class="admin-table">
          <thead>
            <tr><th>Title</th><th>Status</th><th>Category</th><th>Updated</th><th>Actions</th></tr>
          </thead>
          <tbody>${page.results.map(articleRow).join('') || '<tr><td colspan="5">No articles match this search.</td></tr>'}</tbody>
        </table>
      </div>
      ${total > LIST_PAGE_SIZE ? `
        <nav class="pagination" aria-label="Article pages">
          ${state.page > 1
            ? `<a class="button button-secondary" href="${href(state.page - 1)}" rel="prev">← Previous</a>`
            : '<span class="button button-secondary is-disabled" aria-disabled="true">← Previous</span>'}
          <span class="pagination-status">Showing ${first}–${last} of ${total}</span>
          ${page.next
            ? `<a class="button button-secondary" href="${href(state.page + 1)}" rel="next">Next →</a>`
            : '<span class="button button-secondary is-disabled" aria-disabled="true">Next →</span>'}
        </nav>` : ''}
    </section>`;
}

async function renderArticleList() {
  const route = currentRoute;
  const state = listStateFromQuery();
  app.innerHTML = loadingMarkup('Loading articles…');

  try {
    const filters = { page: state.page, ordering: '-created_at' };
    if (state.search) filters.search = state.search;
    if (state.status) filters.is_published = state.status === 'published' ? 'true' : 'false';

    const payload = normalizePage(await getArticles(filters));
    if (!routeIsCurrent(route)) return;

    app.innerHTML = articleListMarkup({ page: payload, state, total: payload.count });
    bindArticleRowActions(app);

    document.querySelector('#admin-filters')?.addEventListener('submit', (event) => {
      event.preventDefault();
      const form = event.currentTarget;
      const params = new URLSearchParams();
      if (form.elements.q.value.trim()) params.set('q', form.elements.q.value.trim());
      if (form.elements.status.value) params.set('status', form.elements.status.value);
      const query = params.toString();
      window.location.href = `admin.html${query ? `?${query}` : ''}#/articles`;
    });
  } catch (error) {
    if (!routeIsCurrent(route)) return;
    app.innerHTML = failureMarkup(friendlyError(error));
  }
}

/* ---------------------------------------------------------- taxonomy mgmt */

function taxonomyMarkup() {
  const categoryRows = taxonomy.categories
    .map(
      (category) => `
      <li class="taxonomy-item">
        <span>${escapeHtml(category.name)} <code>/${escapeHtml(category.slug)}</code></span>
        <button class="button button-danger" type="button" data-delete-category="${category.id}" data-name="${escapeHtml(category.name)}">Delete</button>
      </li>`
    )
    .join('');

  const tagRows = taxonomy.tags
    .map(
      (tag) => `
      <li class="taxonomy-item">
        <span>${escapeHtml(tag.name)} <code>/${escapeHtml(tag.slug)}</code></span>
        <button class="button button-danger" type="button" data-delete-tag="${tag.id}" data-name="${escapeHtml(tag.name)}">Delete</button>
      </li>`
    )
    .join('');

  return `
    ${adminNav('Categories & tags')}
    <section class="admin-heading">
      <div><p class="eyebrow">CSEHub publishing</p><h1>Categories &amp; Tags</h1></div>
      <a class="button button-secondary" href="#/">← Back to dashboard</a>
    </section>

    <div class="admin-two-col">
      <section class="admin-panel">
        <h2>Categories</h2>
        <form class="admin-inline-form" id="category-form">
          <div class="field">
            <label for="category-name">New category</label>
            <input class="input" id="category-name" name="name" required placeholder="Data Structures" />
            <span class="field-hint">The URL slug is generated automatically.</span>
          </div>
          <button class="button button-primary" type="submit">Add category</button>
        </form>
        <ul class="taxonomy-list">${categoryRows || '<li class="admin-note">No categories yet.</li>'}</ul>
      </section>

      <section class="admin-panel">
        <h2>Tags</h2>
        <form class="admin-inline-form" id="tag-form">
          <div class="field">
            <label for="tag-name">New tag</label>
            <input class="input" id="tag-name" name="name" required placeholder="Big O" />
            <span class="field-hint">Used for fine-grained filtering.</span>
          </div>
          <button class="button button-primary" type="submit">Add tag</button>
        </form>
        <ul class="taxonomy-list">${tagRows || '<li class="admin-note">No tags yet.</li>'}</ul>
      </section>
    </div>`;
}

async function renderTaxonomy() {
  const route = currentRoute;
  destroyEditor();
  app.innerHTML = loadingMarkup('Loading taxonomy…');
  try {
    await loadTaxonomy();
    if (!routeIsCurrent(route)) return;
    app.innerHTML = taxonomyMarkup();
    statusMessage('');

    const bindCreate = (formId, create, label) => {
      document.querySelector(formId)?.addEventListener('submit', async (event) => {
        event.preventDefault();
        const input = event.target.elements.name;
        const name = input.value.trim();
        if (!name) return;
        try {
          await create({ name, slug: slugify(name) });
          input.value = '';
          statusMessage(`${label} "${name}" created.`, 'success');
          await renderRoute();
        } catch (error) {
          await notify(`Could not create the ${label.toLowerCase()}`, friendlyError(error), 'error');
        }
      });
    };

    bindCreate('#category-form', createCategory, 'Category');
    bindCreate('#tag-form', createTag, 'Tag');

    app.querySelectorAll('[data-delete-category]').forEach((el) =>
      el.addEventListener('click', () => removeTaxonomy('category', el.dataset.deleteCategory, el.dataset.name))
    );
    app.querySelectorAll('[data-delete-tag]').forEach((el) =>
      el.addEventListener('click', () => removeTaxonomy('tag', el.dataset.deleteTag, el.dataset.name))
    );
  } catch (error) {
    if (!routeIsCurrent(route)) return;
    app.innerHTML = failureMarkup(friendlyError(error));
  }
}

async function removeTaxonomy(kind, id, name) {
  const ok = await confirmAction({
    title: `Delete this ${kind}?`,
    message: `"${name}" will be removed. Articles using it simply become uncategorised.`,
    confirmLabel: 'Delete',
    destructive: true,
  });
  if (!ok) return;

  try {
    if (kind === 'category') await deleteCategory(id);
    else await deleteTag(id);
    statusMessage(`${kind === 'category' ? 'Category' : 'Tag'} deleted.`, 'success');
    await renderRoute();
  } catch (error) {
    await notify(`Could not delete the ${kind}`, friendlyError(error), 'error');
  }
}

function slugify(value) {
  return value
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 80);
}

/* ---------------------------------------------------------- article form */

function articleFormMarkup(article) {
  const selectedTags = new Set((article?.tags || []).map((tag) => tag.id));

  const categoryOptions = [
    '<option value="">— No category —</option>',
    ...taxonomy.categories.map(
      (category) =>
        `<option value="${category.id}" ${article?.category?.id === category.id ? 'selected' : ''}>${escapeHtml(category.name)}</option>`
    ),
  ].join('');

  const tagOptions = taxonomy.tags
    .map(
      (tag) =>
        `<option value="${tag.id}" ${selectedTags.has(tag.id) ? 'selected' : ''}>${escapeHtml(tag.name)}</option>`
    )
    .join('');

  const excerpt = article?.excerpt || contentToPlainText(article?.content, 180);

  return `
    ${adminNav(article ? 'Articles' : 'New article')}
    <section class="admin-heading">
      <div>
        <p class="eyebrow">${article ? 'Editing' : 'New'}</p>
        <h1>${article ? escapeHtml(article.title) : 'Create article'}</h1>
      </div>
      <a class="button button-secondary" href="#/articles">← All articles</a>
    </section>

    <form class="admin-form" id="article-form" novalidate>
      <div class="form-grid">
        <div class="field">
          <label for="f-title">Title</label>
          <input class="input" id="f-title" name="title" required value="${escapeHtml(article?.title || '')}" />
        </div>
        <div class="field">
          <label for="f-slug">Slug</label>
          <input class="input" id="f-slug" name="slug" value="${escapeHtml(article?.slug || '')}" placeholder="generated from title" />
          <span class="field-hint">Leave blank to generate it from the title.</span>
        </div>
      </div>

      <div class="field">
        <label for="f-excerpt">Excerpt</label>
        <textarea class="textarea" id="f-excerpt" name="excerpt" placeholder="One or two sentences shown on cards and search results.">${escapeHtml(excerpt)}</textarea>
        <span class="field-hint">Generated from the article body when left blank.</span>
      </div>

      <div class="field">
        <label for="f-featured-image">Featured image URL</label>
        <input class="input" id="f-featured-image" name="featured_image" type="url" value="${escapeHtml(article?.featured_image || '')}" placeholder="https://…" />
        <span class="field-hint">Link to an externally hosted image. Inline images are uploaded from inside the editor.</span>
      </div>

      <div class="form-grid">
        <div class="field">
          <label for="f-category">Category</label>
          <select class="select" id="f-category" name="category">${categoryOptions}</select>
        </div>
        <div class="field">
          <label for="f-tags">Tags</label>
          <select class="select" id="f-tags" name="tags" multiple>${tagOptions}</select>
          <span class="field-hint">Hold Ctrl/Cmd to select several.</span>
        </div>
      </div>

      <div class="field">
        <span class="field-label">Content</span>
        <div id="editorjs" class="editor-holder"></div>
        <span class="field-hint" id="editor-hint">
          Blocks: headings, lists, quotes, code, images and dividers. Bold, italic and links work inside any text block.
        </span>
      </div>

      <div class="check-row-group">
        <label class="check-row"><input type="checkbox" name="is_published" ${article?.is_published ? 'checked' : ''} /> <span>Published — visible to everyone</span></label>
        <label class="check-row"><input type="checkbox" name="is_featured" ${article?.is_featured ? 'checked' : ''} /> <span>Featured — highlighted on the home page</span></label>
      </div>

      <div class="admin-toolbar">
        <button class="button button-secondary" type="button" id="preview-btn">Preview</button>
        ${article?.is_published ? '<button class="button button-secondary" type="button" id="reindex-btn">Update AI index</button>' : ''}
        <button class="button button-primary" type="submit" id="save-btn">${article ? 'Save changes' : 'Create article'}</button>
      </div>
    </form>`;
}

/**
 * Builds the Editor.js instance.
 *
 * The block toolbar mirrors `SUPPORTED_BLOCK_TYPES` in
 * backend/apps/articles/models.py. Adding a block here without adding it there
 * would produce a document the API rejects with a 400. Bold, italic and inline
 * links are internal to Editor.js 2.30 and need no entry here.
 */
function buildEditor(initialData) {
  const tools = {};

  if (typeof window.Header === 'function') {
    tools.header = {
      class: window.Header,
      inlineToolbar: true,
      config: { levels: [2, 3, 4], defaultLevel: 2 },
    };
  }
  if (typeof window.List === 'function') {
    tools.list = {
      class: window.List,
      inlineToolbar: true,
    };
  }
  if (typeof window.Quote === 'function') {
    tools.quote = {
      class: window.Quote,
      inlineToolbar: true,
    };
  }
  if (typeof window.Code === 'function') {
    tools.code = window.Code;
  }
  if (typeof window.Delimiter === 'function') {
    tools.delimiter = window.Delimiter;
  }
  if (typeof window.ImageTool === 'function') {
    tools.image = {
      class: window.ImageTool,
      config: {
        uploader: {
          async uploadByFile(file) {
            const url = await uploadImage(file);
            return { success: 1, file: { url, name: file.name } };
          },
        },
        field: 'file',
        inlineToolbar: true,
      },
    };
  }

  return new window.EditorJS({
    holder: 'editorjs',
    data: initialData,
    placeholder: 'Write the lesson…',
    tools,
  });
}

async function renderArticleForm(id) {
  const route = currentRoute;
  destroyEditor();
  app.innerHTML = loadingMarkup(id ? 'Loading article…' : 'Preparing editor…');
  statusMessage('');

  try {
    await loadTaxonomy();
    const article = id ? await getArticle(id) : null;
    if (!routeIsCurrent(route)) return;

    app.innerHTML = articleFormMarkup(article);

    if (!editorToolsAvailable()) {
      statusMessage(
        'The Editor.js library could not be loaded (blocked network or ad-blocker). Article text cannot be edited right now.',
        'error'
      );
      document.querySelector('#save-btn').disabled = true;
      document.querySelector('#preview-btn').disabled = true;
      return;
    }

    const missing = MISSING_TOOLS.filter(([name]) => typeof window[name] !== 'function');
    if (missing.length) {
      // Non-fatal: the remaining blocks still work, so say exactly what is gone.
      statusMessage(
        `Editor tools unavailable: ${missing.map(([, label]) => label).join(', ')}. The article can still be written with the remaining blocks.`,
        'info'
      );
    }

    editor = buildEditor(article?.content || { time: Date.now(), blocks: [], version: EDITOR_VERSION });

    document.querySelector('#article-form').addEventListener('submit', (event) => saveArticle(event, article));
    document.querySelector('#preview-btn').addEventListener('click', openPreview);

    const reindexBtn = document.querySelector('#reindex-btn');
    if (reindexBtn) reindexBtn.addEventListener('click', () => reindex(article));
  } catch (error) {
    if (!routeIsCurrent(route)) return;
    app.innerHTML = failureMarkup(friendlyError(error));
  }
}

async function collectPayload() {
  const form = document.querySelector('#article-form');
  if (!editor) throw new Error('The editor is not ready.');

  const content = await editor.save();

  // Keep the excerpt useful without making the author write it twice.
  const excerpt = form.excerpt.value.trim() || contentToPlainText(content, 180);

  return {
    title: form.title.value.trim(),
    slug: form.slug.value.trim(),
    excerpt,
    featured_image: safeUrl(form.featured_image.value.trim()),
    category: form.category.value ? Number(form.category.value) : null,
    tags: [...form.tags.selectedOptions].map((option) => Number(option.value)),
    content,
    is_published: form.is_published.checked,
    is_featured: form.is_featured.checked,
  };
}

async function saveArticle(event, article) {
  event.preventDefault();
  const saveBtn = document.querySelector('#save-btn');
  saveBtn.disabled = true;
  saveBtn.textContent = 'Saving…';
  statusMessage('');

  try {
    const payload = await collectPayload();

    if (!payload.title) {
      statusMessage('A title is required before saving.', 'error');
      saveBtn.disabled = false;
      saveBtn.textContent = article ? 'Save changes' : 'Create article';
      return;
    }

    const saved = article
      ? await updateArticle(article.id, payload)
      : await createArticle(payload);

    statusMessage(
      payload.is_published
        ? 'Saved and published. Update the AI index so the assistant can read it.'
        : 'Saved as a draft.',
      'success'
    );

    // Route to the saved article so a refresh does not create a duplicate.
    navigate(`#/articles/${saved.id}/edit`);
    await renderRoute();
  } catch (error) {
    statusMessage(`Unable to save: ${friendlyError(error)}`, 'error');
    if (saveBtn) {
      saveBtn.disabled = false;
      saveBtn.textContent = article ? 'Save changes' : 'Create article';
    }
  }
}

async function reindex(article) {
  const btn = document.querySelector('#reindex-btn');
  btn.disabled = true;
  btn.textContent = 'Indexing…';
  statusMessage('Sending this article to the vector store…');

  try {
    const result = await reindexArticle(article.id);
    statusMessage(`AI index updated — ${result.chunks} chunks embedded.`, 'success');
  } catch (error) {
    await notify('AI indexing failed', friendlyError(error), 'error');
  } finally {
    if (document.body.contains(btn)) {
      btn.disabled = false;
      btn.textContent = 'Update AI index';
    }
  }
}

/* ------------------------------------------------------------- preview */

function openPreview() {
  document.querySelector('#preview-modal')?.remove();

  collectPayload()
    .then((payload) => {
      const modal = document.createElement('div');
      modal.id = 'preview-modal';
      modal.className = 'modal-backdrop';
      modal.innerHTML = `
        <div class="modal" role="dialog" aria-modal="true" aria-labelledby="preview-title">
          <header class="modal-head">
            <div>
              <p class="eyebrow">Preview — not yet saved</p>
              <h2 id="preview-title">${escapeHtml(payload.title || 'Untitled')}</h2>
            </div>
            <button class="button button-secondary" type="button" data-close>Close</button>
          </header>
          <div class="modal-body">
            ${payload.excerpt ? `<p class="article-excerpt">${escapeHtml(payload.excerpt)}</p>` : ''}
            <div class="article-content article-preview">${renderArticleContent(payload.content)}</div>
          </div>
        </div>`;

      document.body.appendChild(modal);
      document.body.style.overflow = 'hidden';

      const close = () => {
        modal.remove();
        document.body.style.overflow = '';
        document.removeEventListener('keydown', onKey);
      };
      const onKey = (event) => {
        if (event.key === 'Escape') close();
      };

      modal.querySelector('[data-close]').addEventListener('click', close);
      modal.addEventListener('click', (event) => {
        if (event.target === modal) close();
      });
      document.addEventListener('keydown', onKey);
      modal.querySelector('[data-close]').focus();
    })
    .catch((error) => statusMessage(`Unable to build preview: ${friendlyError(error)}`, 'error'));
}

/* ------------------------------------------------------------ bootstrap */

document.addEventListener('DOMContentLoaded', async () => {
  initNavbar();
  app.innerHTML = loadingMarkup('Verifying access…');

  if (!(await guard())) return;

  if (!window.location.hash) window.location.hash = '#/';
  await renderRoute();

  // `hashchange` covers back/forward and in-app anchor navigation alike.
  window.addEventListener('hashchange', () => {
    renderRoute();
  });
});