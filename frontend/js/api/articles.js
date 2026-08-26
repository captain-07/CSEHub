import { apiFetch } from "../api.js";

function toQuery(params) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      query.set(key, value);
    }
  });
  const serialized = query.toString();
  return serialized ? `?${serialized}` : "";
}

export function getArticles(filters, options) {
  return apiFetch(`/articles/${toQuery(filters)}`, options);
}

export function getArticle(id, options) {
  return apiFetch(`/articles/${encodeURIComponent(id)}/`, options);
}

async function getAllPages(path, options) {
  const firstPage = await apiFetch(path, options);
  // Django rest framework returns pagination object {results: [...], next: ...}
  // but if pagination is disabled or it returns an array directly:
  if (Array.isArray(firstPage)) return firstPage;
  const results = [...firstPage.results];
  let next = firstPage.next;
  while (next) {
    // Extract endpoint path from the full URL returned in next
    const urlObj = new URL(next);
    const relativePath = urlObj.pathname + urlObj.search;
    const page = await apiFetch(relativePath, options);
    results.push(...page.results);
    next = page.next;
  }
  return results;
}

export function getCategories(options) {
  return getAllPages("/categories/", options);
}

export function getTags(options) {
  return getAllPages("/tags/", options);
}
