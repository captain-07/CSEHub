import { initNavbar } from './navbar.js';
import { getArticles, getCategories, normalizePage } from './api/articles.js';
import { articleCardMarkup, messageStateMarkup, escapeHtml } from './renderer.js';

function renderCards(container, articles, options) {
  if (!container) return;
  if (!articles.length) {
    container.innerHTML = messageStateMarkup({
      title: 'No articles published yet',
      message: 'Check back soon — new lessons are added regularly.',
      actionHref: null,
    });
    return;
  }
  container.innerHTML = articles.map((article) => articleCardMarkup(article, options)).join('');
}

/** Article ids already shown in the featured rail, so they are not repeated. */
const featuredIds = new Set();

async function loadFeatured(container) {
  const section = container.closest('section');
  try {
    const page = normalizePage(await getArticles({ page: 1, is_featured: 'true', ordering: '-created_at' }));
    const featured = page.results.slice(0, 3);

    // Only surface the rail when an editor has actually featured something.
    if (!featured.length) {
      if (section) section.hidden = true;
      return;
    }

    featured.forEach((article) => featuredIds.add(String(article.id)));
    renderCards(container, featured, { featured: true });
  } catch (error) {
    console.warn('Featured articles unavailable', error);
    if (section) section.hidden = true;
  }
}

async function loadRecent(container) {
  container.innerHTML = '<div class="loading"><span class="loading-spinner"></span>Loading articles…</div>';
  try {
    const page = normalizePage(await getArticles({ page: 1, ordering: '-created_at' }));
    const withoutFeatured = page.results.filter((article) => !featuredIds.has(String(article.id)));

    // A small library may be entirely featured; then the recent grid repeats
    // them rather than rendering an empty section.
    const recent = (withoutFeatured.length ? withoutFeatured : page.results).slice(0, 6);
    renderCards(container, recent);

    const countEl = document.querySelector('#article-count');
    if (countEl) {
      countEl.textContent = `${page.count} ${page.count === 1 ? 'article' : 'articles'} in the library`;
    }
  } catch (error) {
    console.warn('Recent articles unavailable', error);
    container.innerHTML = messageStateMarkup({
      title: 'Unable to load articles',
      message: 'We could not reach the CSEHub API. Please try again in a moment.',
      actionHref: 'articles.html',
      actionLabel: 'Open the library',
    });
  }
}

async function loadCategories(container) {
  const section = container.closest('section');
  try {
    const categories = await getCategories();
    if (!categories.length) {
      if (section) section.hidden = true;
      return;
    }
    container.innerHTML = categories
      .slice(0, 12)
      .map(
        (category) =>
          `<a class="tag category-link" href="articles.html?category=${encodeURIComponent(category.slug)}">${escapeHtml(category.name)}</a>`
      )
      .join('');
  } catch (error) {
    console.warn('Categories unavailable', error);
    if (section) section.hidden = true;
  }
}

document.addEventListener('DOMContentLoaded', async () => {
  initNavbar();

  const featured = document.querySelector('#featured-articles');
  const recent = document.querySelector('#recent-articles');
  const categories = document.querySelector('#popular-categories');

  // Featured is awaited before recent so the "recent" grid can exclude whatever
  // the featured rail already shows; the other two are independent.
  if (featured) await loadFeatured(featured);
  if (recent) loadRecent(recent);
  if (categories) loadCategories(categories);
});