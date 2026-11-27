import { getArticle, getArticles, recordArticleView } from './api/articles.js';
import { ApiError, friendlyError } from './api.js';
import { initNavbar } from './navbar.js';
import { openChatForArticle } from './chat.js';
import { initReactions } from './reactions.js';
import { initQuiz } from './quiz.js';
import {
  renderArticleContent, escapeHtml, safeUrl, formatDate, formatViews, formatPrice, readingTime,
  contentToPlainText, snippetMarkup, highlightSnippets, videoMarkup,
} from './renderer.js';
import { initAuth, isAuthenticated } from './auth-state.js';
import { buyArticle } from './payments.js';
import { initPdfDownload } from './download.js';
import { initShare } from './share.js';
import { showToast } from './toast.js';

let updateReadingProgress = null;

/** Wire up the thin reading-progress bar that tracks scroll position. */
function initReadingProgress() {
  const bar = document.getElementById('reading-progress');
  if (!bar) return;
  function update() {
    const scrollTop = window.scrollY || document.documentElement.scrollTop;
    const docHeight = document.documentElement.scrollHeight - window.innerHeight;
    const progress = docHeight > 0 ? Math.min(100, Math.max(0, (scrollTop / docHeight) * 100)) : 0;
    bar.style.width = `${progress}%`;
    bar.setAttribute('aria-valuenow', String(Math.round(progress)));
  }
  updateReadingProgress = update;
  window.addEventListener('scroll', update, { passive: true });
  window.addEventListener('resize', update, { passive: true });
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
    heading.setAttribute('tabindex', '-1');
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

  aside.addEventListener('click', (event) => {
    const anchor = event.target.closest('a[href^="#"]');
    if (!anchor) return;
    const targetId = anchor.getAttribute('href').slice(1);
    const targetEl = document.getElementById(targetId);
    if (targetEl) {
      targetEl.focus({ preventScroll: true });
    }
  });
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

  const setMeta = (nameOrProperty, value, isProperty = false) => {
    const attr = isProperty ? 'property' : 'name';
    let tag = document.querySelector(`meta[${attr}="${nameOrProperty}"]`);
    if (!tag && value) {
      tag = document.createElement('meta');
      tag.setAttribute(attr, nameOrProperty);
      document.head.appendChild(tag);
    }
    if (tag && value) tag.setAttribute('content', value);
  };

  const excerpt = article.excerpt || contentToPlainText(article.content, 160);
  const image = safeUrl(article.featured_image);

  setMeta('description', excerpt);
  setMeta('og:site_name', 'CSEHub', true);
  setMeta('og:title', title, true);
  setMeta('og:type', 'article', true);
  setMeta('og:description', excerpt, true);
  if (image) setMeta('og:image', image, true);

  // Twitter / X cards
  setMeta('twitter:card', image ? 'summary_large_image' : 'summary');
  setMeta('twitter:title', title);
  setMeta('twitter:description', excerpt);
  if (image) setMeta('twitter:image', image);

  // Canonical link
  let canonical = document.querySelector('link[rel="canonical"]');
  if (!canonical) {
    canonical = document.createElement('link');
    canonical.setAttribute('rel', 'canonical');
    document.head.appendChild(canonical);
  }
  const canonicalUrl = new URL(window.location.href);
  canonicalUrl.search = '';
  canonicalUrl.hash = '';
  if (article.slug) canonicalUrl.searchParams.set('slug', article.slug);
  canonical.setAttribute('href', canonicalUrl.toString());
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
      if (button.classList.contains('is-copied')) return;
      const original = button.dataset.label || button.textContent;
      button.dataset.label = original;
      const code = decodeURIComponent(button.dataset.code || '');
      try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
          await navigator.clipboard.writeText(code);
        } else {
          const scratch = document.createElement('textarea');
          scratch.value = code;
          scratch.style.position = 'fixed';
          scratch.style.opacity = '0';
          document.body.appendChild(scratch);
          scratch.select();
          document.execCommand('copy');
          scratch.remove();
        }
        button.textContent = 'Copied!';
        button.classList.add('is-copied');
        clearTimeout(button._copyTimeout);
        button._copyTimeout = setTimeout(() => {
          button.textContent = original;
          button.classList.remove('is-copied');
        }, 2000);
      } catch (err) {
        console.error('Failed to copy code to clipboard', err);
        button.textContent = 'Press Ctrl+C';
        clearTimeout(button._copyTimeout);
        button._copyTimeout = setTimeout(() => {
          button.textContent = original;
        }, 2000);
      }
    });
  });
}

const READING_SIZE_KEY = 'csehub-reading-size';

function initReadingSize(shell) {
  const content = shell.querySelector('.article-content');
  const controls = shell.querySelector('.reading-controls');
  if (!content || !controls) return;

  let currentSize = 'normal';
  try {
    currentSize = localStorage.getItem(READING_SIZE_KEY) || 'normal';
  } catch {
    /* storage unavailable */
  }

  content.setAttribute('data-reading-size', currentSize);

  const syncButtons = (size) => {
    controls.querySelectorAll('.reading-size-btn').forEach((btn) => {
      const active = btn.dataset.size === size;
      btn.classList.toggle('is-active', active);
      btn.setAttribute('aria-pressed', String(active));
    });
  };

  syncButtons(currentSize);

  controls.querySelectorAll('.reading-size-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      const size = btn.dataset.size || 'normal';
      content.setAttribute('data-reading-size', size);
      syncButtons(size);
      try {
        localStorage.setItem(READING_SIZE_KEY, size);
      } catch {
        /* storage unavailable */
      }
      if (updateReadingProgress) updateReadingProgress();
    });
  });
}

function enhanceCodeSnippets(shell) {
  shell.querySelectorAll('.snippet').forEach((snippet) => {
    const code = snippet.querySelector('pre code');
    if (!code) return;
    const lines = (code.textContent || '').split('\n').length;
    if (lines <= 35) return;

    snippet.classList.add('snippet-collapsible');
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'snippet-expand-btn';
    btn.setAttribute('aria-expanded', 'false');
    btn.innerHTML = `<span class="snippet-expand-text">Show full snippet (${lines} lines)</span>`;
    snippet.appendChild(btn);

    btn.addEventListener('click', () => {
      const isExpanded = snippet.classList.toggle('is-expanded');
      btn.setAttribute('aria-expanded', String(isExpanded));
      const textSpan = btn.querySelector('.snippet-expand-text');
      if (textSpan) {
        textSpan.textContent = isExpanded
          ? 'Show fewer lines'
          : `Show full snippet (${lines} lines)`;
      }
      if (updateReadingProgress) updateReadingProgress();
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

/** The session-dependent half of the paywall copy. */
function paywallNote(signedIn) {
  return signedIn
    ? 'One-time purchase. Nothing is charged automatically.'
    : 'Signing in is free — you only pay when you buy the article.';
}

/**
 * The paywall's one control.
 *
 * A signed-out visitor is sent to sign in with a redirect back here; only a
 * signed-in reader gets a Buy button, because there is nobody to charge
 * otherwise. Kept separate from `paywallMarkup` so it can be swapped in place
 * when the session resolves after the card has already been painted.
 */
function paywallCtaMarkup(article, signedIn) {
  const price = formatPrice(article.price);
  if (!signedIn) {
    const here = `${window.location.pathname}${window.location.search}`;
    return `<a class="button button-primary" href="login.html?redirect=${encodeURIComponent(here)}">Sign in to buy</a>`;
  }
  return `<button class="button button-primary" type="button" id="paywall-buy">Buy${price ? ` for ${escapeHtml(price)}` : ''}</button>`;
}

/**
 * The locked-article card.
 *
 * The body is absent from the payload rather than hidden here — this is the
 * sales pitch for content the server has already withheld, so it must never
 * assume the article text is available to preview.
 */
function paywallMarkup(article, signedIn) {
  const price = formatPrice(article.price);

  return `
    <section class="paywall" aria-labelledby="paywall-title">
      <div class="paywall-card">
        <span class="paywall-eyebrow">Paid article</span>
        <h2 class="paywall-title" id="paywall-title">Buy this article to keep reading</h2>
        <p class="paywall-copy">
          One purchase unlocks the rest of this article${price ? ' and a PDF you can read offline' : ''}.
        </p>
        <ul class="paywall-benefits">
          <li class="paywall-benefit">The complete article, every section</li>
          <li class="paywall-benefit">A PDF download for offline reading</li>
          <li class="paywall-benefit">Access whenever you are signed in</li>
        </ul>
        <div class="paywall-actions">
          <span class="paywall-price">${escapeHtml(price || 'Paid')}</span>
          ${paywallCtaMarkup(article, signedIn)}
        </div>
        <p class="paywall-note">${paywallNote(signedIn)}</p>
      </div>
    </section>`;
}

/**
 * Binds the paywall, and corrects its CTA if the session lands late.
 *
 * `initArticle` waits for `initAuth()` before rendering, but only for a moment:
 * a slow profile request must not hold the sales page hostage. When the session
 * resolves afterwards and disagrees with the state the card was rendered from,
 * the button and its note are swapped in place rather than the whole card,
 * which the reader may already be reading.
 *
 * The purchase itself is `payments.js`; this only owns the button's state.
 * Nothing here decides whether access was granted — a successful payment
 * reloads the page and asks the server again, so the body appears only because
 * the API started sending it.
 */
function initPaywall(shell, article, signedIn) {
  const bindBuy = () => {
    const button = shell.querySelector('#paywall-buy');
    if (!button) return;

    button.addEventListener('click', async () => {
      if (button.disabled) return;
      const label = button.textContent;
      button.disabled = true;
      button.setAttribute('aria-busy', 'true');
      // A spinner is the only signal that the click registered while the order
      // is created and the provider's script loads; without it the label alone
      // looks frozen.
      button.innerHTML = '<span class="button-spinner" aria-hidden="true"></span> Opening checkout…';

      try {
        const result = await buyArticle(article);
        if (result.status === 'paid' || result.status === 'already_owned') {
          button.textContent = 'Unlocked — reloading…';
          window.location.reload();
          return;
        }
        if (result.status === 'pending') {
          showToast(
            'Payment received. Access opens as soon as it is confirmed — refresh in a moment.',
            { type: 'info', timeout: 8000 },
          );
        }
        // 'dismissed' needs no message: the reader closed the sheet.
      } catch (error) {
        showToast(friendlyError(error), { type: 'error', timeout: 8000 });
      }

      button.disabled = false;
      button.removeAttribute('aria-busy');
      button.textContent = label;
    });
  };
  bindBuy();

  initAuth().then(() => {
    const resolved = isAuthenticated();
    if (resolved === signedIn) return;

    const actions = shell.querySelector('.paywall-actions');
    if (!actions) return;
    actions.querySelector('#paywall-buy')?.remove();
    actions.querySelector('a.button')?.remove();
    actions.insertAdjacentHTML('beforeend', paywallCtaMarkup(article, resolved));

    const note = shell.querySelector('.paywall-note');
    if (note) note.textContent = paywallNote(resolved);
    bindBuy();
  }).catch(() => {
    // The card already rendered with the signed-out CTA, which is the safe
    // fallback; nothing further to do.
  });
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
  const articleEl = shell.querySelector('article') || content;
  if (!content || !articleEl) return;

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
    // Ensure the selection intersects the article body
    const isInsideArticle = articleEl.contains(range.commonAncestorContainer)
      || (typeof range.intersectsNode === 'function' && range.intersectsNode(articleEl));
    if (!isInsideArticle) {
      hideButton();
      return;
    }

    selectedText = text;
    const rect = range.getBoundingClientRect();
    if (!rect || (rect.width === 0 && rect.height === 0)) {
      hideButton();
      return;
    }

    // Hide if scrolled entirely off-screen
    if (rect.bottom < 60 || rect.top > window.innerHeight) {
      hideButton();
      return;
    }

    btn.hidden = false;
    const btnWidth = btn.offsetWidth || 96;
    const btnHeight = btn.offsetHeight || 32;

    const isTouch = window.matchMedia('(pointer: coarse)').matches;
    if (isTouch) {
      btn.classList.add('is-docked');
      btn.style.top = '';
      btn.style.left = '';
    } else {
      btn.classList.remove('is-docked');
      // Position above selection if there's room, otherwise below
      const top = rect.top - btnHeight - 10 > 70
        ? rect.top - btnHeight - 10
        : rect.bottom + 10;

      const left = Math.max(16, Math.min(
        window.innerWidth - btnWidth - 16,
        rect.left + (rect.width / 2) - (btnWidth / 2)
      ));

      btn.style.top = `${Math.round(top)}px`;
      btn.style.left = `${Math.round(left)}px`;
    }
  };

  btn.addEventListener('mousedown', (event) => {
    // Prevent clearing the selection on mousedown before the click fires
    event.preventDefault();
  });

  btn.addEventListener('click', () => {
    if (!selectedText) return;
    const question = `Explain this part from the article:\n"${selectedText}"`;
    hideButton();
    openChatForArticle(article.slug || article.id, article.title, { question, autoSend: true });
  });

  document.addEventListener('mouseup', () => {
    setTimeout(updateSelection, 20);
  });

  document.addEventListener('touchend', () => {
    setTimeout(updateSelection, 100);
  });

  document.addEventListener('selectionchange', () => {
    const sel = window.getSelection();
    if (!sel || sel.isCollapsed) {
      hideButton();
    }
  });

  window.addEventListener('scroll', () => {
    if (!btn.hidden) updateSelection();
  }, { passive: true });

  window.addEventListener('resize', hideButton, { passive: true });
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

    // A paid article whose body the server withheld. `has_access` is the
    // authority, not `is_paid`: a buyer looking at a paid article has full
    // access, and inferring the paywall from the price would lock them out of
    // what they already paid for.
    const locked = Boolean(article.is_paid) && !article.has_access;
    if (locked) {
      // Only the CTA depends on the session. Resolving it here keeps a
      // signed-in reader from being offered "Sign in to buy", but the wait is
      // bounded: a hanging profile request would otherwise leave a paid page
      // blank for the full 20 s request timeout. Past the bound we render the
      // signed-out CTA and `initPaywall` swaps it when the session lands.
      await Promise.race([
        initAuth().catch(() => {}),
        new Promise((resolve) => { setTimeout(resolve, 1200); }),
      ]);
    }
    const paywallSignedIn = locked && isAuthenticated();

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
            <div class="article-actions">
              <button class="button button-secondary" type="button" id="article-share" aria-label="Share this article">
                <svg class="article-share-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">
                  <circle cx="18" cy="5" r="3" />
                  <circle cx="6" cy="12" r="3" />
                  <circle cx="18" cy="19" r="3" />
                  <line x1="8.59" y1="13.51" x2="15.42" y2="17.49" />
                  <line x1="15.41" y1="6.51" x2="8.59" y2="10.49" />
                </svg>
                <span>Share</span>
              </button>
              ${article.is_paid && article.has_access ? `
                <button class="button button-secondary" type="button" id="article-download">Download PDF</button>` : ''}
              <div class="reading-controls" role="group" aria-label="Reading font size">
                <button class="reading-size-btn" type="button" data-size="normal" aria-label="Normal font size" title="Normal text size">A</button>
                <button class="reading-size-btn" type="button" data-size="large" aria-label="Large font size" title="Large text size">A+</button>
                <button class="reading-size-btn" type="button" data-size="xlarge" aria-label="Extra large font size" title="Extra large text size">A++</button>
              </div>
            </div>
          </header>

          ${locked ? paywallMarkup(article, paywallSignedIn) : `
          <div class="article-content">${renderArticleContent(article.content)}</div>

          ${article.code_snippets?.length
            ? article.code_snippets.map((snippet) => snippetMarkup(snippet)).join('')
            : ''}

          ${videoMarkup(article.video_url, { title: article.title })}

          ${article.quiz_question_count ? `
            <section class="article-quiz" id="article-quiz">
              <div class="article-quiz-intro">
                <h2 class="article-quiz-title">Quiz me</h2>
                <p class="article-quiz-copy">
                  Test yourself on this article with up to 5 quick multiple-choice
                  questions, one at a time. You will get a score at the end.
                </p>
              </div>
              <button class="button button-primary" type="button" id="quiz-start">Start quiz</button>
            </section>

            <dialog class="quiz-modal" id="quiz-modal" aria-labelledby="quiz-modal-title" aria-describedby="quiz-modal-subtitle">
              <div class="quiz-modal-inner">
                <header class="quiz-modal-header">
                  <div class="quiz-modal-heading">
                    <h2 class="quiz-modal-title" id="quiz-modal-title">Quiz me</h2>
                    <p class="quiz-modal-subtitle" id="quiz-modal-subtitle"></p>
                  </div>
                  <button class="quiz-modal-close" type="button" data-quiz-action="cancel" aria-label="Close quiz">&times;</button>
                </header>
                <div class="quiz-panel" id="quiz-panel"></div>
              </div>
            </dialog>` : ''}

          <div class="article-reactions" id="article-reactions" data-article-key="${escapeHtml(articleKey)}"></div>

          <section class="article-ai-cta">
            <div class="article-ai-cta-content">
              <h3>Have questions about this article?</h3>
              <p>Ask the learning assistant for explanations, alternative code examples, or conceptual breakdowns — grounded in this article.</p>
            </div>
            <button class="button button-primary" id="ask-ai-cta-btn" type="button">Ask AI Assistant</button>
          </section>`}

          ${relatedMarkup(related)}

          ${pagerMarkup(neighbors)}

          <p class="article-back"><a class="button button-secondary" href="articles.html">← Back to all articles</a></p>
        </article>`;

      // Sharing is offered on the paywall too: the excerpt and cover are the
      // pitch, and the link is the same one the buyer follows.
      initShare(shell, article);

      if (updateReadingProgress) updateReadingProgress();

      if (locked) {
        // The body is not on the page, so neither are its affordances: the
        // quiz, reactions, assistant and selection tool are all gated too.
        // Asking for them here would only produce a 402.
        initPaywall(shell, article, paywallSignedIn);
      } else {
        bindCopyButtons(shell);
        enhanceCodeSnippets(shell);
        highlightSnippets(shell);
        initTableOfContents(shell);
        initReadingSize(shell);
        initPdfDownload(shell, article);
        // Not awaited: it resolves the Supabase session first, and the article
        // should not wait on that to appear.
        initReactions(shell, article);
        initQuiz(shell, article);
        recordViewOnce(article);
        initSelectionAi(shell, article);

        const askAiBtn = document.querySelector('#ask-ai-cta-btn');
        if (askAiBtn) {
          askAiBtn.addEventListener('click', () => openChatForArticle(article.slug || article.id, article.title, {
            category: article.category?.name,
          }));
        }
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