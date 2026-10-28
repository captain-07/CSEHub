import { getArticle, getArticles, recordArticleView } from './api/articles.js';
import { ApiError, friendlyError } from './api.js';
import { initNavbar } from './navbar.js';
import { openChatForArticle } from './chat.js';
import { initReactions } from './reactions.js';
import {
  renderArticleContent, escapeHtml, safeUrl, formatDate, formatViews, readingTime,
  contentToPlainText, snippetMarkup, highlightSnippets, videoMarkup,
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

/**
 * Sticky table of contents, built from the article's h2 headings.
 *
 * Only added when there are two or more sections — for shorter pieces a TOC
 * is decoration. Side-effecting on purpose: it assigns ids to the headings it
 * links to, so the anchors it hands out always resolve.
 */
function initTableOfContents(shell) {
  const content = shell.querySelector('.article-content');
  const articleEl = shell.querySelector('article');
  if (!content || !articleEl) return;

  const headings = [...content.querySelectorAll('h2')];
  if (headings.length < 2) return;

  const links = headings.map((heading, index) => {
    if (!heading.id) heading.id = `section-${index + 1}`;
    return { id: heading.id, text: heading.textContent.trim() || `Section ${index + 1}` };
  });

  const aside = document.createElement('aside');
  aside.className = 'article-toc';
  aside.innerHTML = `
    <p class="article-toc-title" id="toc-title">On this page</p>
    <nav aria-labelledby="toc-title">
      <ul>
        ${links.map((link) => `<li><a href="#${link.id}">${escapeHtml(link.text)}</a></li>`).join('')}
      </ul>
    </nav>`;
  // Inserted *before* the <article>: the rail renders on the left, so this
  // keeps the DOM order (and therefore the tab order) matching what is seen.
  articleEl.before(aside);
  shell.classList.add('has-toc');

  // Scroll-spy: highlight the last heading that has scrolled past the top of
  // the viewport, with an offset for the sticky navbar (76px) + progress bar.
  const navLinks = new Map(
    [...aside.querySelectorAll('a')].map((a) => [a.getAttribute('href').slice(1), a])
  );
  const offset = 140;
  let activeId = null;

  const spy = () => {
    let current = links[0].id;
    for (const heading of headings) {
      if (heading.getBoundingClientRect().top - offset <= 0) current = heading.id;
      else break;
    }
    // At the very bottom of the page, every listing puts the last entry up.
    if (window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 4) {
      current = links[links.length - 1].id;
    }
    if (current === activeId) return;
    activeId = current;
    navLinks.forEach((link, id) => link.classList.toggle('is-current', id === current));
  };

  window.addEventListener('scroll', spy, { passive: true });
  window.addEventListener('resize', spy, { passive: true });
  spy();
}

const NEIGHBORS_CACHE_KEY = 'csehub-article-order';
const NEIGHBORS_CACHE_TTL = 5 * 60 * 1000;

/**
 * Reads the {id, slug, title} summary list from the small cache, or null.
 * Only the fields the pager needs are stored, keeping the entry tiny.
 */
function readOrderCache() {
  try {
    const cached = JSON.parse(sessionStorage.getItem(NEIGHBORS_CACHE_KEY) || 'null');
    if (cached && Array.isArray(castedList(cached))) return cached.list;
  } catch {
    // Corrupt cache is the same as no cache.
  }
  return null;
}

function castedList(cached) {
  return cached.savedAt && Date.now() - cached.savedAt < NEIGHBORS_CACHE_TTL ? cached.list : null;
}

function writeOrderCache(list) {
  try {
    sessionStorage.setItem(NEIGHBORS_CACHE_KEY, JSON.stringify({ savedAt: Date.now(), list }));
  } catch {
    // Cache-less browsing is fine.
  }
}

/**
 * Chronological neighbours of this article, for prev/next reading.
 *
 * DRF pagination gives no neighbours directly, so the library is walked
 * newest-first for at most three pages. The ordered summary is cached in
 * sessionStorage for a few minutes: reading several articles in a row should
 * not re-walk the library each time. Degrades to "no pager" instead of failing
 * the article.
 */
async function loadNeighbors(article) {
  const key = String(article.id ?? '');
  const findIndex = (items) => items.findIndex(
    (item) => String(item.id) === key || (article.slug && item.slug === article.slug)
  );

  let list = readOrderCache();

  if (!list) {
    try {
      for (let page = 1; page <= 3; page += 1) {
        const data = await getArticles({ ordering: '-created_at', page });
        const results = Array.isArray(data) ? data : data?.results || [];
        // Keep only what the pager renders, so cached entries stay small.
        list = [...(list || []), ...results.map((item) => ({ id: item.id, slug: item.slug, title: item.title }))];

        const index = findIndex(list);
        const hasMore = !Array.isArray(data) && Boolean(data?.next);
        // Stop as soon as the article is found with a following entry, or the
        // library is exhausted — more pages cannot change the neighbours then.
        if (!hasMore || (index !== -1 && index + 1 < list.length)) break;
      }

      const found = findIndex(list);
      if (found !== -1) writeOrderCache(list);
    } catch {
      list = list || [];
    }
  }

  const index = findIndex(list || []);
  if (index === -1) return { newer: null, older: null };
  return {
    newer: index > 0 ? list[index - 1] : null,
    older: list[index + 1] || null,
  };
}

function pagerMarkup(neighbors) {
  const { newer, older } = neighbors || {};
  if (!newer && !older) return '';

  const card = (item, direction) => {
    if (!item) return '<span class="article-pager-slot" aria-hidden="true"></span>';
    const href = `article.html?slug=${encodeURIComponent(item.slug || item.id)}`;
    const label = direction === 'newer' ? '← Newer article' : 'Older article →';
    return `
      <a class="article-pager-card" href="${href}" rel="${direction === 'newer' ? 'prev' : 'next'}">
        <span class="article-pager-label">${label}</span>
        <span class="article-pager-title">${escapeHtml(item.title)}</span>
      </a>`;
  };

  return `
    <nav class="article-pager" aria-label="More articles">
      ${card(newer, 'newer')}
      ${card(older, 'older')}
    </nav>`;
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

/**
 * Contextual AI assistant selection trigger.
 *
 * When a reader highlights a section of text within the article body, a floating
 * "Ask AI" chip appears adjacent to the selection. Clicking it immediately opens
 * the assistant drawer and submits the question quoting the selected snippet.
 */
function initSelectionAi(shell, article) {
  const content = shell.querySelector('.article-content');
  if (!content) return;

  let btn = document.querySelector('#selection-ai-btn');
  if (!btn) {
    btn = document.createElement('button');
    btn.type = 'button';
    btn.id = 'selection-ai-btn';
    btn.className = 'selection-ai-btn';
    btn.hidden = true;
    btn.innerHTML = '<span class="selection-ai-icon" aria-hidden="true">✨</span><span>Ask AI</span>';
    document.body.appendChild(btn);
  }

  const hideButton = () => {
    btn.hidden = true;
  };

  let selectedText = '';

  const updateSelection = () => {
    const selection = window.getSelection();
    if (!selection || selection.isCollapsed || !selection.rangeCount) {
      hideButton();
      return;
    }

    const text = selection.toString().trim();
    if (text.length < 5 || text.length > 500) {
      hideButton();
      return;
    }

    const range = selection.getRangeAt(0);
    // Ensure the selection is inside the article content
    if (!content.contains(range.commonAncestorContainer)) {
      hideButton();
      return;
    }

    selectedText = text;
    const rect = range.getBoundingClientRect();
    if (!rect || (rect.width === 0 && rect.height === 0)) {
      hideButton();
      return;
    }

    btn.hidden = false;
    const btnWidth = btn.offsetWidth || 90;
    const btnHeight = btn.offsetHeight || 32;

    // Position above selection if there's room, otherwise below
    const top = rect.top - btnHeight - 8 > 60
      ? rect.top - btnHeight - 8 + window.scrollY
      : rect.bottom + 8 + window.scrollY;

    const left = Math.max(16, Math.min(
      window.innerWidth - btnWidth - 16,
      rect.left + (rect.width / 2) - (btnWidth / 2) + window.scrollX
    ));

    btn.style.top = `${top}px`;
    btn.style.left = `${left}px`;
  };

  btn.addEventListener('mousedown', (event) => {
    // Prevent clearing the selection on mousedown before the click fires
    event.preventDefault();
  });

  btn.addEventListener('click', () => {
    if (!selectedText) return;
    const question = `Explain this part from the article:\n"${selectedText}"`;
    hideButton();
    openChatForArticle(article.slug, article.title, { question, autoSend: true });
  });

  content.addEventListener('mouseup', () => {
    setTimeout(updateSelection, 10);
  });

  content.addEventListener('touchend', () => {
    setTimeout(updateSelection, 100);
  });

  document.addEventListener('selectionchange', () => {
    const sel = window.getSelection();
    if (!sel || sel.isCollapsed) {
      hideButton();
    }
  });

  window.addEventListener('resize', hideButton, { passive: true });
  window.addEventListener('scroll', hideButton, { passive: true });
}

const VIEW_SESSION_PREFIX = 'csehub:viewed:';

/**
 * Records this read once per browser session and settles the byline tally.
 *
 * Without the `sessionStorage` guard a refresh — or coming back with the back
 * button — would each add a view. The guard lives here rather than on the
 * server because nothing stores a row per view (see `Article.record_view`), so
 * the server has nothing to deduplicate against.
 *
 * It runs after the article is on screen and is never awaited: a slow or failed
 * count must not hold up content, and one lost view is not worth a spinner.
 * Signed-in staff are skipped by the server, so an editor's own previews still
 * cannot inflate the number.
 */
function recordViewOnce(article) {
  const key = `${VIEW_SESSION_PREFIX}${article.slug || article.id}`;
  const tally = document.querySelector('#article-views');

  try {
    if (sessionStorage.getItem(key)) return;
    sessionStorage.setItem(key, '1');
  } catch {
    // Private browsing can refuse sessionStorage. Count anyway rather than drop
    // the view: an over-count is better than never counting at all.
  }

  recordArticleView(article.slug || article.id)
    .then((result) => {
      // The detail payload was read before this request, so the number already
      // rendered is one behind. Show what the server just returned.
      if (tally && result) tally.innerHTML = `&#128065; ${escapeHtml(formatViews(result.view_count))}`;
    })
    .catch((error) => {
      console.warn('Could not record article view', error);
      // A dropped request must not mark the article as counted for the rest of
      // the session.
      try { sessionStorage.removeItem(key); } catch { /* ignore */ }
    });
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
    const [related, neighbors] = await Promise.all([loadRelated(article), loadNeighbors(article)]);
    const hero = safeUrl(article.featured_image);
    const reading = article.reading_time || readingTime(article.content);

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
              ${reading ? `<span class="reading-time-badge">⏱ ${escapeHtml(reading)}</span>` : ''}
              <span class="article-views" id="article-views">&#128065; ${escapeHtml(formatViews(article.view_count))}</span>
              ${article.updated_at && article.updated_at !== article.created_at
                ? `<span class="article-updated">Updated ${escapeHtml(formatDate(article.updated_at))}</span>`
                : ''}
            </div>
            ${hero ? `<img class="article-featured-image" src="${escapeHtml(hero)}" alt="${escapeHtml(article.title)}" />` : ''}
            ${tagsMarkup(article.tags).length ? `<div class="tag-list">${tagsMarkup(article.tags)}</div>` : ''}
          </header>

          <div class="article-content">${renderArticleContent(article.content)}</div>

          ${article.code_snippets?.length
            ? article.code_snippets.map((snippet) => snippetMarkup(snippet)).join('')
            : ''}

          ${videoMarkup(article.video_url, { title: article.title })}

          <div class="article-reactions" id="article-reactions" data-article-key="${escapeHtml(articleKey)}"></div>

          <section class="article-ai-cta">
            <div class="article-ai-cta-content">
              <h3>Have questions about this article?</h3>
              <p>Ask the learning assistant for explanations, alternative code examples, or conceptual breakdowns — grounded in this article.</p>
            </div>
            <button class="button button-primary" id="ask-ai-cta-btn" type="button">Ask AI Assistant</button>
          </section>

          ${relatedMarkup(related)}

          ${pagerMarkup(neighbors)}

          <p class="article-back"><a class="button button-secondary" href="articles.html">← Back to all articles</a></p>
        </article>`;

      bindCopyButtons(shell);
      highlightSnippets(shell);
      initTableOfContents(shell);
      // Not awaited: it resolves the Supabase session first, and the article
      // should not wait on that to appear.
      initReactions(shell, article);
      recordViewOnce(article);
      initSelectionAi(shell, article);

      const askAiBtn = document.querySelector('#ask-ai-cta-btn');
      if (askAiBtn) {
        askAiBtn.addEventListener('click', () => openChatForArticle(article.slug, article.title));
      }
    }
  } catch (error) {
    console.error('Failed to fetch article details:', error);
    if (!shell) return;
    if (error instanceof ApiError && error.status === 404) {
      shell.innerHTML = emptyState('Article Not Found', 'This article may have been unpublished or removed.');
      return;
    }
    // A failed read is usually a dropped connection, so offer the retry in
    // place rather than sending the reader back to the library to start over.
    shell.innerHTML = `
      <div class="empty-state" role="alert">
        <span class="empty-state-icon" aria-hidden="true">\uD83D\uDCE1</span>
        <h2>Failed to load article</h2>
        <p>${escapeHtml(friendlyError(error))}</p>
        <button class="button button-secondary" type="button" data-retry>Try again</button>
      </div>`;
    shell.querySelector('[data-retry]')?.addEventListener('click', () => initArticle());
  }
}

document.addEventListener('DOMContentLoaded', () => {
  initNavbar();
  initReadingProgress();
  initArticle();
});