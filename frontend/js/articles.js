import { getArticles, getCategories, getTags } from './api/articles.js';
import { ApiError } from './api.js';
import { initNavbar } from './navbar.js';

const escapeHtml = (value = "") => String(value)
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;")
  .replaceAll("'", "&#039;");

function formatDate(value) {
  return new Intl.DateTimeFormat("en", { day: "numeric", month: "short", year: "numeric" }).format(new Date(value));
}

function normalizePage(data) {
  return Array.isArray(data) ? { results: data, count: data.length, next: null, previous: null } : data;
}

function tagsMarkup(tags = []) {
  return tags.map((tag) => `<a class="tag" href="articles.html?tag=${encodeURIComponent(tag.slug)}">${escapeHtml(tag.name)}</a>`).join("");
}

function articleCard(article) {
  return `
    <article class="article-card">
      <div class="card-meta">
        ${article.category ? `<a href="articles.html?category=${encodeURIComponent(article.category.slug)}">${escapeHtml(article.category.name)}</a>` : "General"}
        <span>·</span>
        <time datetime="${article.created_at}">${formatDate(article.created_at)}</time>
      </div>
      <h2><a href="article.html?id=${article.id}">${escapeHtml(article.title)}</a></h2>
      <div class="tag-list">${tagsMarkup(article.tags)}</div>
      <a class="text-link" href="article.html?id=${article.id}">Read article <span aria-hidden="true">→</span></a>
    </article>
  `;
}

function paginationMarkup(page, currentFilters) {
  if (!page.next && !page.previous) return "";
  const current = Number(currentFilters.page || 1);
  
  const getPageUrl = (pageNumber) => {
    const params = new URLSearchParams();
    Object.entries(currentFilters).forEach(([key, value]) => {
      if (value && key !== 'page') params.set(key, value);
    });
    params.set("page", pageNumber);
    return `articles.html?${params.toString()}`;
  };

  return `
    <nav class="pagination" aria-label="Article pages">
      ${page.previous ? `<a class="button button-secondary" href="${getPageUrl(current - 1)}">← Newer</a>` : ""}
      <span>Page ${current}</span>
      ${page.next ? `<a class="button button-secondary" href="${getPageUrl(current + 1)}">Older →</a>` : ""}
    </nav>
  `;
}

async function initLibrary() {
  const query = new URLSearchParams(location.search);
  const filters = {
    search: query.get("search") || "",
    "category__slug": query.get("category") || "",
    "tags__slug": query.get("tag") || "",
    ordering: query.get("ordering") || "-created_at",
    page: query.get("page") || "1",
  };

  const contentArea = document.querySelector("#content-area");
  const filterForm = document.querySelector("#filters");
  
  // Populate filter inputs with current values
  if (filterForm) {
    filterForm.elements.search.value = filters.search;
    filterForm.elements.ordering.value = filters.ordering;

    filterForm.addEventListener("submit", (event) => {
      event.preventDefault();
      const searchVal = filterForm.elements.search.value;
      const catVal = filterForm.elements.category.value;
      const tagVal = filterForm.elements.tag.value;
      const orderVal = filterForm.elements.ordering.value;

      const nextParams = new URLSearchParams();
      if (searchVal) nextParams.set("search", searchVal);
      if (catVal) nextParams.set("category", catVal);
      if (tagVal) nextParams.set("tag", tagVal);
      if (orderVal && orderVal !== "-created_at") nextParams.set("ordering", orderVal);
      
      window.location.href = `articles.html${nextParams.toString() ? `?${nextParams.toString()}` : ""}`;
    });
  }

  // Load and render
  try {
    if (contentArea) {
      contentArea.innerHTML = `<div class="loading"><span class="loading-spinner"></span>Loading articles…</div>`;
    }

    const [categories, tags, articleData] = await Promise.all([
      getCategories().catch(err => { console.warn(err); return []; }),
      getTags().catch(err => { console.warn(err); return []; }),
      getArticles(filters)
    ]);

    // Populate Category dropdown
    const categorySelect = filterForm?.elements.category;
    if (categorySelect) {
      categorySelect.innerHTML = '<option value="">All categories</option>';
      categories.forEach((category) => {
        const option = new Option(category.name, category.slug);
        categorySelect.add(option);
      });
      categorySelect.value = filters["category__slug"];
    }

    // Populate Tag dropdown
    const tagSelect = filterForm?.elements.tag;
    if (tagSelect) {
      tagSelect.innerHTML = '<option value="">All topics</option>';
      tags.forEach((tag) => {
        const option = new Option(tag.name, tag.slug);
        tagSelect.add(option);
      });
      tagSelect.value = filters["tags__slug"];
    }

    const page = normalizePage(articleData);
    
    if (contentArea) {
      if (!page.results?.length) {
        contentArea.innerHTML = `
          <div class="empty-state">
            <h2>No articles found</h2>
            <p>Try adjusting your search terms or filters.</p>
            <a class="button button-secondary" href="articles.html">Clear all filters</a>
          </div>
        `;
        return;
      }

      const hasActiveFilters = filters.search || filters["category__slug"] || filters["tags__slug"];
      contentArea.innerHTML = `
        <div class="results-heading">
          <p>${hasActiveFilters ? `${page.count} matching article${page.count === 1 ? "" : "s"}` : "Latest articles"}</p>
        </div>
        <div class="article-grid">
          ${page.results.map(articleCard).join("")}
        </div>
        ${paginationMarkup(page, filters)}
      `;
    }

  } catch (error) {
    console.error("Failed to load library data:", error);
    if (contentArea) {
      const message = error instanceof ApiError ? error.message : "Something unexpected happened while retrieving articles.";
      contentArea.innerHTML = `
        <div class="empty-state" role="alert">
          <h2>Failed to load content</h2>
          <p>${escapeHtml(message)}</p>
          <button class="button button-primary" id="retry-btn" type="button">Try again</button>
        </div>
      `;
      document.querySelector("#retry-btn")?.addEventListener("click", () => window.location.reload());
    }
  }
}

// Initialise page components
document.addEventListener("DOMContentLoaded", () => {
  initNavbar();
  initLibrary();
});
