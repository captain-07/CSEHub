import { request } from "./client.js";

function toQuery(params) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value) query.set(key, value);
  });
  const serialized = query.toString();
  return serialized ? `?${serialized}` : "";
}

export function getArticles(filters, options) {
  return request(`/articles/${toQuery(filters)}`, options);
}

export function getArticle(id, options) {
  return request(`/articles/${encodeURIComponent(id)}/`, options);
}

async function getAllPages(path, options) {
  const firstPage = await request(path, options);
  if (Array.isArray(firstPage)) return firstPage;
  const results = [...firstPage.results];
  let next = firstPage.next;
  while (next) {
    const page = await request(next, options);
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
