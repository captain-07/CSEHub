/**
 * Article library: search, filtering, sorting and pagination.
 *
 * The URL is the single source of truth for the current view. Two naming
 * conventions are involved and they are easy to confuse:
 *
 *   - URL params   `category`, `tag`, `search`, `ordering`, `page` (human-facing)
 *   - API params   `category__slug`, `tags__slug`, `search`, `ordering`, `page`
 *
 * `readFilters` and `toUrlParams` are the only two places that translate
 * between them, so a filter can never be silently dropped from a paginated link.
 */

import { getArticles, getCategories, getTags, normalizePage } from './api/articles.js';
import { ApiError } from './api.js';
import { initNavbar } from './navbar.js';
import { articleCardMarkup, escapeHtml, messageStateMarkup } from './renderer.js';

const PAGE_SIZE_HINT = 20;

const ORDERINGS = [
  ['-created_at', 'Newest first'],
  ['created_at', 'Oldest first'],
  ['title', 'Title A–Z'],
  ['-title', 'Title Z–A'],
];

/** URL query string -> filter object. */
function readFilters() {
  const query = new URLSearchParams(window.location.search);
  const ordering = query.get('ordering');
  return {
    search: query.get('search') || '',
    category: query.get('category') || '',
    tag: query.get('tag') || '',
    ordering: ORDERINGS.some(([value]) => value === ordering) ? ordering : '-created_at',
    page: Math.max(1, Number(query.get('page')) || 1),
  };
}

/** Filter object -> query string the listing page understands. */
function toUrlParams(filters, { includePage = true } = {}) {
  const params = new URLSearchParams();
  if (filters.search) params.set('search', filters.search);
  if (filters.category) params.set('category', filters.category);
  if (filters.tag) params.set('tag', filters.tag);
  if (filters.ordering && filters.ordering !== '-created_at') params.set('ordering', filters.ordering);
  if (includePage && filters.page > 1) params.set('page', String(filters.page));
  return params;
}

/** Filter object -> the query the DRF filterset expects. */
function toApiQuery(filters) {
  return {
    search: filters.search,
    category__slug: filters.category,
    tags__slug: filters.tag,
    ordering: filters.ordering,
    page: filters.page,
  };
}

/** Any non-default filter currently applied, for the summary line. */
function activeFilterChips(filters, categories, tags) {
  const chips = [];
  if (filters.search) chips.push({ key: 'search', label: `“${filters.search}”` });
  if (filters.category) {
    const category = categories.find((item) => item.slug === filters.category);
    chips.push({ key: 'category', label: category?.name || filters.category });
  }
  if (filters.tag) {
    const tag = tags.find((item) => item.slug === filters.tag);
    chips.push({ key: 'tag', label: tag?.name || filters.tag });
  }
  return chips;
}

function paginationMarkup(page, filters) {
  if (!page.next && !page.previous && page.count <= PAGE_SIZE_HINT) return '';

  const href = (pageNumber) => {
    const params = toUrlParams({ ...filters, page: pageNumber });
    return `articles.html${params.toString() ? `?${params.toString()}` : ''}`;
  };

  // DRF returns page numbers; show the range so the position is unambiguous.
  const first = (filters.page - 1) * PAGE_SIZE_HINT + 1;
  const last = Math.min(filters.page * PAGE_SIZE_HINT, page.count);

  return `
    <nav class="pagination" aria-label="Article pages">
      ${page.previous
        ? `<a class="button button-secondary" href="${href(filters.page - 1)}" rel="prev">← Newer</a>`
        : '<span class="button button-secondary is-disabled" aria-disabled="true">← Newer</span>'}
      <span class="pagination-status">Showing ${first}–${last} of ${page.count}</span>
      ${page.next
        ? `<a class="button button-secondary" href="${href(filters.page + 1)}" rel="next">Older →</a>`
        : '<span class="button button-secondary is-disabled" aria-disabled="true">Older →</span>'}
    </nav>`;
}

function emptyStateMarkup(filters) {
  const filtered = filters.search || filters.category || filters.tag;
  return messageStateMarkup({
    title: filtered ? 'No articles match these filters' : 'No articles published yet',
    message: filtered
      ? 'Try a different search term, or clear the filters to see the whole library.'
      : 'Check back soon — new lessons are added regularly.',
    actionHref: filtered ? 'articles.html' : 'categories.html',
    actionLabel: filtered ? 'Clear all filters' : 'Browse by subject',
  });
}

function failureMarkup(message) {
  return `
    <div class="empty-state" role="alert">
      <h2>Unable to load articles</h2>
      <p>${escapeHtml(message)}</p>
      <button class="button button-primary" id="retry-btn" type="button">Try again</button>
    </div>`;
}

/** Fills a <select> and selects the current value. */
function populateSelect(select, items, currentValue, allLabel, valueKey = 'slug', labelKey = 'name') {
  if (!select) return;
  select.innerHTML = `<option value="">${escapeHtml(allLabel)}</option>`;
  items.forEach((item) => select.add(new Option(item[labelKey], item[valueKey])));
  select.value = currentValue || '';
}

async function initLibrary() {
  const filters = readFilters();
  const contentArea = document.querySelector('#content-area');
  const filterForm = document.querySelector('#filters');

  if (contentArea) contentArea.innerHTML = '<div class="loading"><span class="loading-spinner"></span>Loading articles…</div>';

  /** Applies a filter change by navigating, which keeps the URL shareable. */
  const applyFilters = (overrides) => {
    const next = { ...filters, page: 1, ...overrides };
    const params = toUrlParams(next, { includePage: false });
    window.location.href = `articles.html${params.toString() ? `?${params.toString()}` : ''}`;
  };

  if (filterForm) {
    filterForm.elements.search.value = filters.search;
    filterForm.elements.ordering.value = filters.ordering;

    // A search field is more useful submitting itself than requiring a click,
    // but only after a pause so each keystroke is not a request.
    let searchTimer = null;
    filterForm.elements.search.addEventListener('input', (event) => {
      clearTimeout(searchTimer);
      const value = event.target.value;
      searchTimer = setTimeout(() => applyFilters({ search: value.trim() }), 450);
    });

    filterForm.elements.category.addEventListener('change', (event) => {
      applyFilters({ category: event.target.value, tag: '' });
    });
    filterForm.elements.tag.addEventListener('change', (event) => {
      applyFilters({ tag: event.target.value });
    });
    filterForm.elements.ordering.addEventListener('change', (event) => {
      applyFilters({ ordering: event.target.value });
    });

    // Kept for the explicit Apply button (and for Enter inside the text input).
    filterForm.addEventListener('submit', (event) => {
      event.preventDefault();
      clearTimeout(searchTimer);
      applyFilters({
        search: filterForm.elements.search.value.trim(),
        category: filterForm.elements.category.value,
        tag: filterForm.elements.tag.value,
        ordering: filterForm.elements.ordering.value,
      });
    });
  }

  try {
    // Taxonomy is only needed for the dropdowns and the filter chips, so a
    // failure here must not prevent the article list itself from rendering.
    const [categories, tags, articleData] = await Promise.all([
      getCategories().catch((error) => { console.warn('Categories unavailable', error); return []; }),
      getTags().catch((error) => { console.warn('Tags unavailable', error); return []; }),
      getArticles(toApiQuery(filters)),
    ]);

    populateSelect(filterForm?.elements.category, categories, filters.category, 'All categories');
    populateSelect(filterForm?.elements.tag, tags, filters.tag, 'All topics');

    const page = normalizePage(articleData);
    if (!contentArea) return;

    if (!page.results.length) {
      contentArea.innerHTML = emptyStateMarkup(filters);
      return;
    }

    const chips = activeFilterChips(filters, categories, tags);
    const chipsMarkup = chips.length
      ? `<div class="filter-chips">
           ${chips.map((chip) => `
             <button class="filter-chip" type="button" data-remove="${escapeHtml(chip.key)}">
               ${escapeHtml(chip.label)} <span aria-hidden="true">✕</span>
               <span class="sr-only">Remove filter</span>
             </button>`).join('')}
           <a class="text-link" href="articles.html">Clear all</a>
         </div>`
      : '';

    contentArea.innerHTML = `
      <div class="results-heading">
        <p>${chips.length
          ? `${page.count} ${page.count === 1 ? 'match' : 'matches'}`
          : `${page.count} ${page.count === 1 ? 'article' : 'articles'} in the library`}</p>
      </div>
      ${chipsMarkup}
      <div class="article-grid">
        ${page.results.map((article) => articleCardMarkup(article)).join('')}
      </div>
      ${paginationMarkup(page, filters)}`;

    contentArea.querySelectorAll('[data-remove]').forEach((button) => {
      button.addEventListener('click', () => {
        const key = button.dataset.remove;
        applyFilters({ search: '', category: '', tag: '', [key]: '' });
      });
    });
  } catch (error) {
    console.error('Failed to load library data:', error);
    if (!contentArea) return;
    const message = error instanceof ApiError
      ? error.message
      : 'Something unexpected happened while retrieving articles.';
    contentArea.innerHTML = failureMarkup(message);
    document.querySelector('#retry-btn')?.addEventListener('click', () => window.location.reload());
  }
}

document.addEventListener('DOMContentLoaded', () => {
  initNavbar();
  initLibrary();
});