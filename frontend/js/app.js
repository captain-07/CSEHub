import { ApiError } from "./api/client.js";
import { getArticle, getArticles, getCategories, getTags } from "./api/articles.js";

const app = document.querySelector("#app");
let pageAbortController;

const escapeHtml = (value = "") => String(value)
  .replaceAll("&", "&amp;").replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");

function formatDate(value) {
  return new Intl.DateTimeFormat("en", { day: "numeric", month: "short", year: "numeric" }).format(new Date(value));
}

function normalizePage(data) {
  return Array.isArray(data) ? { results: data, count: data.length, next: null, previous: null } : data;
}

function showError(error, retry) {
  const message = error instanceof ApiError ? error.message : "Something unexpected happened.";
  app.innerHTML = `<section class="status-card" role="alert"><p class="eyebrow">Unable to load</p><h1>We couldn't get that content.</h1><p>${escapeHtml(message)}</p><button class="button button-primary" type="button">Try again</button></section>`;
  app.querySelector("button").addEventListener("click", retry);
}

function tagsMarkup(tags = []) {
  return tags.map((tag) => `<a class="tag" href="#/?tag=${encodeURIComponent(tag.slug)}">${escapeHtml(tag.name)}</a>`).join("");
}

function articleCard(article) {
  return `<article class="article-card"><div class="card-meta">${article.category ? `<a href="#/?category=${encodeURIComponent(article.category.slug)}">${escapeHtml(article.category.name)}</a>` : "Learning note"}<span>·</span><time datetime="${article.created_at}">${formatDate(article.created_at)}</time></div><h2><a href="#/articles/${article.id}">${escapeHtml(article.title)}</a></h2><div class="tag-list">${tagsMarkup(article.tags)}</div><a class="text-link" href="#/articles/${article.id}">Read article <span aria-hidden="true">→</span></a></article>`;
}

async function renderLibrary() {
  const query = new URLSearchParams(location.hash.split("?")[1] || "");
  const filters = {
    search: query.get("search") || "",
    "category__slug": query.get("category") || "",
    "tags__slug": query.get("tag") || "",
    ordering: query.get("ordering") || "-created_at",
    page: query.get("page") || "",
  };
  app.innerHTML = `<section class="hero"><p class="eyebrow">CSEHub learning library</p><h1>Learn the ideas<br /><em>behind the code.</em></h1><p>Focused notes on the computer science topics that matter most.</p></section><section class="library"><form class="filters" id="filters"><label class="search-field"><span class="sr-only">Search articles</span><input name="search" value="${escapeHtml(filters.search)}" type="search" placeholder="Search articles" /></label><label><span class="sr-only">Category</span><select name="category"><option value="">All categories</option></select></label><label><span class="sr-only">Tag</span><select name="tag"><option value="">All topics</option></select></label><label><span class="sr-only">Sort articles</span><select name="ordering"><option value="-created_at">Newest first</option><option value="created_at">Oldest first</option></select></label><button class="button button-primary" type="submit">Apply</button></form><div id="content"><div class="loading"><span></span>Loading articles…</div></div></section>`;
  const form = document.querySelector("#filters");
  form.elements.ordering.value = filters.ordering;
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const values = new FormData(form);
    const next = new URLSearchParams();
    ["search", "category", "tag", "ordering"].forEach((key) => {
      const value = values.get(key);
      if (value && !(key === "ordering" && value === "-created_at")) next.set(key, value);
    });
    location.hash = `/${next.toString() ? `?${next}` : ""}`;
  });

  try {
    const [categoriesData, tagsData, articleData] = await Promise.all([
      getCategories({ signal: pageAbortController.signal }),
      getTags({ signal: pageAbortController.signal }),
      getArticles(filters, { signal: pageAbortController.signal }),
    ]);
    const categories = categoriesData || [];
    const tags = tagsData || [];
    const categorySelect = form.elements.category;
    categories.forEach((category) => categorySelect.add(new Option(category.name, category.slug)));
    categorySelect.value = filters["category__slug"];
    const tagSelect = form.elements.tag;
    tags.forEach((tag) => tagSelect.add(new Option(tag.name, tag.slug)));
    tagSelect.value = filters["tags__slug"];
    const page = normalizePage(articleData);
    const content = document.querySelector("#content");
    if (!page.results?.length) {
      content.innerHTML = `<div class="empty-state"><h2>No articles found</h2><p>Try a different search term or clear a filter.</p><a class="button button-secondary" href="#/">Clear filters</a></div>`;
      return;
    }
    const activeFilter = filters.search || filters["category__slug"] || filters["tags__slug"];
    content.innerHTML = `<div class="results-heading"><p>${activeFilter ? `${page.count} matching article${page.count === 1 ? "" : "s"}` : "Latest articles"}</p></div><div class="article-grid">${page.results.map(articleCard).join("")}</div>${paginationMarkup(page)}`;
  } catch (error) {
    if (error.name !== "AbortError") showError(error, navigate);
  }
}

function paginationMarkup(page) {
  if (!page.next && !page.previous) return "";
  const current = Number(new URLSearchParams(location.hash.split("?")[1] || "").get("page") || 1);
  const setPage = (number) => {
    const params = new URLSearchParams(location.hash.split("?")[1] || "");
    params.set("page", number);
    return `#/?${params}`;
  };
  return `<nav class="pagination" aria-label="Article pages">${page.previous ? `<a class="button button-secondary" href="${setPage(current - 1)}">← Newer</a>` : ""}<span>Page ${current}</span>${page.next ? `<a class="button button-secondary" href="${setPage(current + 1)}">Older →</a>` : ""}</nav>`;
}

function renderContent(content) {
  return escapeHtml(content).split(/\n{2,}/).map((block) => {
    if (block.startsWith("## ")) return `<h2>${block.slice(3)}</h2>`;
    return `<p>${block.replace(/`([^`]+)`/g, "<code>$1</code>").replaceAll("\n", "<br />")}</p>`;
  }).join("");
}

async function renderArticle(id) {
  app.innerHTML = `<section class="article-shell"><a class="back-link" href="#/">← Back to articles</a><div class="loading"><span></span>Loading article…</div></section>`;
  try {
    const article = await getArticle(id, { signal: pageAbortController.signal });
    const snippets = article.code_snippets?.map((snippet) => `<section class="snippet"><div><span>${escapeHtml(snippet.language)}</span><button class="copy-button" type="button" data-code="${encodeURIComponent(snippet.code)}">Copy code</button></div><pre><code>${escapeHtml(snippet.code)}</code></pre></section>`).join("") || "";
    app.innerHTML = `<article class="article-shell"><a class="back-link" href="#/">← Back to articles</a><header class="article-header"><div class="card-meta">${article.category ? `<a href="#/?category=${encodeURIComponent(article.category.slug)}">${escapeHtml(article.category.name)}</a>` : "Learning note"}<span>·</span><time datetime="${article.created_at}">${formatDate(article.created_at)}</time></div><h1>${escapeHtml(article.title)}</h1><div class="tag-list">${tagsMarkup(article.tags)}</div>${article.author_email ? `<p class="byline">Published by ${escapeHtml(article.author_email)}</p>` : ""}</header><div class="article-content">${renderContent(article.content)}</div>${snippets}</article>`;
    document.querySelectorAll(".copy-button").forEach((button) => button.addEventListener("click", async () => {
      await navigator.clipboard.writeText(decodeURIComponent(button.dataset.code));
      button.textContent = "Copied";
      setTimeout(() => { button.textContent = "Copy code"; }, 1600);
    }));
  } catch (error) {
    if (error.name !== "AbortError") showError(error, navigate);
  }
}

function navigate() {
  pageAbortController?.abort();
  pageAbortController = new AbortController();
  const match = location.hash.match(/^#\/articles\/(\d+)$/);
  if (match) renderArticle(match[1]);
  else renderLibrary();
  app.focus();
}

window.addEventListener("hashchange", navigate);
if (!location.hash) location.hash = "/";
navigate();
