import { initNavbar } from './navbar.js';
import { getCategories, getTags, getAllPages } from './api/articles.js';
import { escapeHtml, messageStateMarkup } from './renderer.js';

const grid = document.querySelector('#category-grid');
const tagCloud = document.querySelector('#tag-cloud');

function plural(count, singular, pluralForm) {
  return `${count} ${count === 1 ? singular : pluralForm}`;
}

/**
 * The per-card count line.
 *
 * `counts === null` means the tally never arrived, which is not the same as a
 * category holding no articles. Saying "0 articles" there states something the
 * page does not know, so an em dash is shown instead of a fabricated zero.
 */
function countMarkup(counts, categoryId) {
  if (counts === null) return '<p class="category-count category-count-unknown">—</p>';
  const count = counts.get(categoryId) || 0;
  return `<p class="category-count">${escapeHtml(plural(count, 'article', 'articles'))}</p>`;
}

/**
 * Renders the category grid, with the article count for each category.
 *
 * The counts need the whole library, so the full paginated collection is fetched
 * once (getAllPages) and tallied locally — one sequence of requests rather than
 * one request per category.
 */
async function loadCategories() {
  grid.innerHTML = '<div class="loading"><span class="loading-spinner"></span>Loading categories…</div>';

  try {
    const categories = await getCategories();
    if (!categories.length) {
      grid.innerHTML = messageStateMarkup({
        title: 'No categories yet',
        message: 'Categories will appear here once editors create them.',
      });
      return;
    }

    // `null`, not an empty Map: a failed count request has to be
    // distinguishable from a genuine zero, or every category reads "0 articles"
    // as though it were true. See `countMarkup`.
    let counts = null;
    try {
      const articles = await getAllPages('/articles/?ordering=-created_at&is_published=true');
      counts = new Map();
      articles.forEach((article) => {
        const id = article.category?.id;
        if (id) counts.set(id, (counts.get(id) || 0) + 1);
      });
    } catch (error) {
      // Counts are supplementary: the grid is still useful without them, but it
      // must not state a number it does not have.
      console.warn('Article counts unavailable', error);
    }

    grid.innerHTML = categories
      .map((category) => `
          <a class="category-card" href="articles.html?category=${encodeURIComponent(category.slug)}">
            <h2>${escapeHtml(category.name)}</h2>
            ${countMarkup(counts, category.id)}
            <span class="text-link">Browse →</span>
          </a>`)
      .join('');
  } catch (error) {
    grid.innerHTML = messageStateMarkup({
      title: 'Unable to load categories',
      message: error?.message || 'Please try again shortly.',
    });
  }
}

async function loadTags() {
  try {
    const tags = await getTags();
    if (!tags.length) {
      tagCloud.innerHTML = '';
      document.querySelector('#tags-section')?.setAttribute('hidden', '');
      return;
    }
    tagCloud.innerHTML = tags
      .map(
        (tag) =>
          `<a class="tag" href="articles.html?tag=${encodeURIComponent(tag.slug)}">${escapeHtml(tag.name)}</a>`
      )
      .join('');
  } catch {
    tagCloud.innerHTML = '';
    document.querySelector('#tags-section')?.setAttribute('hidden', '');
  }
}

document.addEventListener('DOMContentLoaded', () => {
  initNavbar();
  loadCategories();
  loadTags();
});
