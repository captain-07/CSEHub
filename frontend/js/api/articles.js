import { apiFetch } from '../api.js';

function toQuery(params = {}) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      query.set(key, value);
    }
  });
  const serialized = query.toString();
  return serialized ? `?${serialized}` : '';
}

/** Normalises DRF's paginated envelope and a bare array into one shape. */
export function normalizePage(payload) {
  if (Array.isArray(payload)) {
    return { results: payload, count: payload.length, next: null, previous: null };
  }
  return {
    results: Array.isArray(payload?.results) ? payload.results : [],
    count: Number.isFinite(payload?.count) ? payload.count : 0,
    next: payload?.next ?? null,
    previous: payload?.previous ?? null,
  };
}

/* ---------------------------------------------------------------- articles */

export function getArticles(filters, options) {
  return apiFetch(`/articles/${toQuery(filters)}`, options);
}

export function getArticle(id, options) {
  return apiFetch(`/articles/${encodeURIComponent(id)}/`, options);
}

export function createArticle(payload) {
  return apiFetch('/articles/', { method: 'POST', body: payload });
}

export function updateArticle(id, payload) {
  return apiFetch(`/articles/${encodeURIComponent(id)}/`, { method: 'PATCH', body: payload });
}

export function deleteArticle(id) {
  return apiFetch(`/articles/${encodeURIComponent(id)}/`, { method: 'DELETE' });
}

/* ----------------------------------------------------------------- uploads */

/**
 * Uploads an image for an Editor.js image block and resolves to its public URL.
 *
 * The file goes to the backend rather than being inlined as a base64 data URI:
 * article content is stored verbatim in a JSONField and also fed to the RAG
 * pipeline, so embedding binary payloads would bloat both. The browser never
 * sees a storage credential.
 */
export async function uploadImage(file) {
  const form = new FormData();
  form.append('file', file);

  const payload = await apiFetch('/uploads/images/', { method: 'POST', body: form });
  return payload?.url || '';
}

/** Pushes an article's content into the vector store for the AI assistant. */
export function reindexArticle(id) {
  return apiFetch(`/articles/${encodeURIComponent(id)}/reindex/`, { method: 'POST' });
}

/**
 * Follows DRF's `next` links and concatenates every page.
 *
 * Used only where a complete collection is genuinely needed (admin statistics,
 * category counts). The bound stops a malformed or cyclic `next` from looping
 * forever.
 */
export async function getAllPages(path, options) {
  const firstPage = await apiFetch(path, options);
  if (Array.isArray(firstPage)) return firstPage;

  const results = [...normalizePage(firstPage).results];
  let next = firstPage?.next ?? null;
  let guard = 0;

  while (next && guard < 50) {
    const page = await apiFetch(next, options);
    results.push(...normalizePage(page).results);
    next = page?.next ?? null;
    guard += 1;
  }
  return results;
}

/* --------------------------------------------------- categories and tags */

export function getCategories(options) {
  return getAllPages('/categories/', options);
}

export function getTags(options) {
  return getAllPages('/tags/', options);
}

export function createCategory(payload) {
  return apiFetch('/categories/', { method: 'POST', body: payload });
}

export function deleteCategory(id) {
  return apiFetch(`/categories/${encodeURIComponent(id)}/`, { method: 'DELETE' });
}

export function createTag(payload) {
  return apiFetch('/tags/', { method: 'POST', body: payload });
}

export function deleteTag(id) {
  return apiFetch(`/tags/${encodeURIComponent(id)}/`, { method: 'DELETE' });
}