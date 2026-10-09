import { getArticle, getArticles } from './api/articles.js';
import { ApiError } from './api.js';
import { initNavbar } from './navbar.js';
import { openChatForArticle } from './chat.js';
import {
  renderArticleContent, escapeHtml, safeUrl, formatDate, readingTime, contentToPlainText,
  snippetMarkup, highlightSnippets,
} from './renderer.js';

/** Wire up the thin reading-progress bar that tracks scroll position. */
function initReadingProgress() {
  const bar = document.getElementById('reading-progress');
  if (!bar) return;
  function update() {
    const el = document.querySelector('.article-content') || document.documentElement;
    const scrollTop = window.scrollY || document.documentElement.scrollTop;
    const docHeight = document.documentElement.scrollHeight - window.innerHeight;
    const progress = docHeight > 0 ? Math.min(100, (scrollTop / docHeight) * 100) : 0;
    bar.style.width = `${progress}%`;
    bar.setAttribute('aria-valuenow', String(Math.round(progress)));
  }
  window.addEventListener('scroll', update, { passive: true });
  update();
}

function tagsMarkup(tags = []) {
  return tags
    .map((tag) => `<a class="tag" href="articles.html?tag=${encodeURIComponent(tag.slug)}">${escapeHtml(tag.name)}</a>`)
    .join('');
}

/** Sibling articles in the same category, used for the "keep learning" rail. */
async function loadRelated(article) {
  if (!article?.category?.slug) return [];
  try {
    // The filterset field is `category__slug`, so that is the query parameter
    // the backend expects — not `category`.
    const page = await getArticles({ category__slug: article.category.slug, page: 1 });
    const results = Array.isArray(page) ? page : page?.results || [];
    return results.filter((item) => item.id !== article.id).slice(0, 3);
  } catch {
    return [];
  }
}

/** Keeps the tab title, description and social preview in step with the article. */
function applyDocumentMeta(article) {
  const title = `${article.title} — CSEHub`;
  document.title = title;

  const setMeta = (selector, value) => {
    const tag = document.querySelector(selector);
    if (tag && value) tag.setAttribute('content', value);
  };

  setMeta('meta[name="description"]', article.excerpt || contentToPlainText(article.content, 160));
  setMeta('meta[property="og:title"]', title);
  setMeta('meta[property="og:type"]', 'article');
  setMeta('meta[property="og:description"]', article.excerpt || contentToPlainText(article.content, 160));
  if (safeUrl(article.featured_image)) setMeta('meta[property="og:image"]', article.featured_image);
}

function relatedMarkup(related) {
  if (!related.length) return '';
  return `
    <section class="article-related">
      <h2 class="article-related-title">Keep learning</h2>
      <div class="article-related-grid">
        ${related
          .map(
            (item) => `
          <a class="article-related-card" href="article.html?slug=${encodeURIComponent(item.slug || item.id)}">
            <h3>${escapeHtml(item.title)}</h3>
            ${item.excerpt ? `<p>${escapeHtml(item.excerpt)}</p>` : ''}
            <p class="card-meta">${item.category ? escapeHtml(item.category.name) : 'General'} · ${escapeHtml(formatDate(item.created_at))}</p>
          </a>`
          )
          .join('')}
      </div>
    </section>`;
}

function bindCopyButtons(root) {
  root.querySelectorAll('.copy-button').forEach((button) => {
    button.addEventListener('click', async () => {
      const original = button.textContent;
      try {
        await navigator.clipboard.writeText(decodeURIComponent(button.dataset.code || ''));
        button.textContent = 'Copied!';
        button.classList.add('is-copied');
      } catch (err) {
        console.error('Failed to copy code to clipboard', err);
        button.textContent = 'Press Ctrl+C';
      }
      setTimeout(() => {
        button.textContent = original;
        button.classList.remove('is-copied');
      }, 2000);
    });
  });
}

function emptyState(title, message, actionHref = 'articles.html', actionLabel = 'Browse Articles') {
  return `
    <div class="empty-state" role="alert">
      <h2>${escapeHtml(title)}</h2>
      <p>${escapeHtml(message)}</p>
      <a class="button button-secondary" href="${actionHref}">${escapeHtml(actionLabel)}</a>
    </div>`;
}

async function initArticle() {
  const query = new URLSearchParams(location.search);
  const articleKey = query.get('slug') || query.get('id');
  const shell = document.querySelector('#article-shell');

  if (!articleKey) {
    if (shell) shell.innerHTML = emptyState('Article Not Found', 'No valid article slug or ID was provided in the URL.');
    return;
  }

  try {
    if (shell) shell.innerHTML = '<div class="loading"><span class="loading-spinner"></span>Loading article…</div>';

    const article = await getArticle(articleKey);
    applyDocumentMeta(article);

    // Related articles are a nice-to-have; the article itself must render even
    // if that extra request fails.
    const related = await loadRelated(article);
    const hero = safeUrl(article.featured_image);

    if (shell) {
      shell.innerHTML = `
        <nav class="breadcrumb" aria-label="Breadcrumb">
          <a href="index.html">Home</a>
          <span aria-hidden="true">/</span>
          <a href="articles.html">Articles</a>
          ${article.category ? `<span aria-hidden="true">/</span><a href="articles.html?category=${encodeURIComponent(article.category.slug)}">${escapeHtml(article.category.name)}</a>` : ''}
        </nav>

        <article>
          <header class="article-header">
            <p class="eyebrow">${article.category ? escapeHtml(article.category.name) : 'General'}</p>
            <h1>${escapeHtml(article.title)}</h1>
            ${article.excerpt ? `<p class="article-excerpt">${escapeHtml(article.excerpt)}</p>` : ''}
            <div class="article-byline">
              ${article.author_name ? `<span class="byline">By ${escapeHtml(article.author_name)}</span>` : ''}
              <time datetime="${escapeHtml(article.created_at || '')}">${escapeHtml(formatDate(article.created_at))}</time>
              ${readingTime(article.content) ? `<span class="reading-time-badge">⏱ ${escapeHtml(readingTime(article.content))}</span>` : ''}
              ${article.updated_at && article.updated_at !== article.created_at
                ? `<span class="article-updated">Updated ${escapeHtml(formatDate(article.updated_at))}</span>`
                : ''}
            </div>
            ${hero ? `<img class="article-featured-image" src="${escapeHtml(hero)}" alt="" />` : ''}
            ${tagsMarkup(article.tags).length ? `<div class="tag-list">${tagsMarkup(article.tags)}</div>` : ''}
          </header>

          <div class="article-content">${renderArticleContent(article.content)}</div>

          ${article.code_snippets?.length
            ? article.code_snippets.map((snippet) => snippetMarkup(snippet)).join('')
            : ''}

          <section class="article-ai-cta">
            <div class="article-ai-cta-content">
              <h3>Have questions about this article?</h3>
              <p>Ask the learning assistant for explanations, alternative code examples, or conceptual breakdowns — grounded in this article.</p>
            </div>
            <button class="button button-primary" id="ask-ai-cta-btn" type="button">Ask AI Assistant</button>
          </section>

          ${relatedMarkup(related)}

          <p class="article-back"><a class="button button-secondary" href="articles.html">← Back to all articles</a></p>
        </article>`;

      bindCopyButtons(shell);
      highlightSnippets(shell);

      const askAiBtn = document.querySelector('#ask-ai-cta-btn');
      if (askAiBtn) {
        askAiBtn.addEventListener('click', () => openChatForArticle(article.slug, article.title));
      }
    }
  } catch (error) {
    console.error('Failed to fetch article details:', error);
    if (!shell) return;
    const message = error instanceof ApiError ? error.message : "We couldn't retrieve the article content.";
    const notFound = error instanceof ApiError && error.status === 404;
    shell.innerHTML = notFound
      ? emptyState('Article Not Found', 'This article may have been unpublished or removed.')
      : emptyState('Failed to load article', message);
  }
}

document.addEventListener('DOMContentLoaded', () => {
  initNavbar();
  initReadingProgress();
  initArticle();
});