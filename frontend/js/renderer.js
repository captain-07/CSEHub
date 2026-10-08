/**
 * Article content renderer — the single source of truth for turning stored
 * article content into DOM-safe HTML.
 *
 * Article bodies are authored with Editor.js and therefore contain
 * user-controlled text.  Every value is escaped before it reaches the DOM, block
 * types are dispatched through an allow-list, heading levels are clamped, and
 * URLs are restricted to http(s).  Nothing here injects untrusted HTML.
 *
 * Used by both the public article page and the admin preview so the two can
 * never drift apart.
 */

export const escapeHtml = (value = '') => String(value ?? '')
  .replaceAll('&', '&amp;')
  .replaceAll('<', '&lt;')
  .replaceAll('>', '&gt;')
  .replaceAll('"', '&quot;')
  .replaceAll("'", '&#039;');

/** Returns a normalised http(s) URL, or '' when the input is not a safe link. */
export function safeUrl(candidate) {
  if (!candidate || typeof candidate !== 'string') return '';
  try {
    const parsed = new URL(candidate, window.location.origin);
    if (parsed.protocol === 'http:' || parsed.protocol === 'https:') return parsed.href;
  } catch {
    /* malformed URL */
  }
  return '';
}

/*
 * Editor.js stores inline emphasis (bold, italic, links, inline code) as a small
 * HTML fragment *inside* the block text. Escaping that wholesale would render
 * `<b>term</b>` literally, so inline markup is sanitized instead: text is always
 * escaped, and only the tags on this allow-list survive. Everything else —
 * including all attributes — is dropped, so no event handler, style, `src` or
 * `javascript:` URL authored in the editor can reach the DOM.
 */
const ALLOWED_INLINE_TAGS = new Set([
  'b', 'strong', 'i', 'em', 'u', 's', 'del', 'ins', 'mark', 'sub', 'sup',
  'code', 'kbd', 'samp', 'var', 'br', 'a',
]);

const INLINE_TAG_RE = /<(\/?)([a-zA-Z][a-zA-Z0-9]*)((?:\s[^<>]*?)?)\/?>/g;
const HREF_ATTR_RE = /href\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))/i;

/** Renders one tag found inside block text, or '' when it must be discarded. */
function renderInlineTag(closing, rawName, rawAttrs) {
  const name = rawName.toLowerCase();
  if (!ALLOWED_INLINE_TAGS.has(name)) return '';

  if (closing) return name === 'br' ? '' : `</${name}>`;
  if (name === 'br') return '<br />';
  if (name !== 'a') return `<${name}>`;

  const attrs = rawAttrs || '';
  const match = HREF_ATTR_RE.exec(attrs);
  const href = safeUrl(match ? (match[1] ?? match[2] ?? match[3]) : '');
  // An anchor with an unusable href degrades to plain text rather than a dead link.
  if (!href) return '';
  return `<a href="${escapeHtml(href)}" target="_blank" rel="noopener noreferrer nofollow">`;
}

/**
 * Escapes text, then re-admits only the safe inline tags an Editor.js author can produce.
 *
 * Open tags are tracked so a closing tag is only emitted for a tag that is
 * actually open. Without this, stripping an unsafe construct (say an anchor with
 * a `javascript:` href) would leave its `</a>` behind and unbalance the markup.
 */
function inlineHtml(value = '') {
  const source = String(value ?? '');
  let output = '';
  let cursor = 0;
  const open = new Set();

  INLINE_TAG_RE.lastIndex = 0;
  let match = INLINE_TAG_RE.exec(source);
  while (match) {
    output += escapeHtml(source.slice(cursor, match.index));

    const closing = Boolean(match[1]);
    const name = match[2].toLowerCase();
    let rendered = renderInlineTag(closing, match[2], match[3]);

    if (!closing && rendered && name !== 'br') open.add(name);
    if (closing) {
      if (!open.has(name)) rendered = '';
      open.delete(name);
    }

    output += rendered;
    cursor = match.index + match[0].length;
    match = INLINE_TAG_RE.exec(source);
  }

  return output + escapeHtml(source.slice(cursor));
}

/**
 * Escapes text and converts soft line breaks into <br>.
 *
 * Backtick spans become inline `<code>`. Editor.js itself stores inline code as
 * `<code>` tags, but bodies migrated from Markdown before the JSONField change
 * still carry backticks, and they would otherwise be displayed verbatim.
 */
function inlineText(value) {
  const html = inlineHtml(value).replace(/`([^`\n]+)`/g, '<code>$1</code>');
  return html.replaceAll('\n', '<br />');
}

/** Removes inline markup so excerpts, meta tags and search snippets stay plain. */
function stripInlineHtml(value = '') {
  return String(value ?? '')
    .replace(/<br\s*\/?>/gi, ' ')
    .replace(/<[^>]*>/g, '')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#0?39;/g, "'")
    .replace(/&amp;/g, '&')
    .replace(/\s+/g, ' ')
    .trim();
}

function renderCodeBlock(data) {
  const code = typeof data.code === 'string' ? data.code : '';
  const language = data.language ? String(data.language) : '';
  return `<section class="snippet">`
    + `<div class="snippet-bar">`
    + `<span class="snippet-lang">${escapeHtml(language || 'code')}</span>`
    + `<button class="copy-button" type="button" data-code="${encodeURIComponent(code)}">Copy code</button>`
    + `</div>`
    + `<pre><code>${escapeHtml(code)}</code></pre>`
    + `</section>`;
}

function renderImageBlock(data) {
  const url = safeUrl(data.file?.url || data.url || '');
  if (!url) return '';
  const caption = data.caption ? escapeHtml(data.caption) : '';
  return `<figure>`
    + `<img src="${escapeHtml(url)}" alt="${caption || 'Article image'}" loading="lazy" />`
    + (caption ? `<figcaption>${caption}</figcaption>` : '')
    + `</figure>`;
}

function renderLinkBlock(data) {
  const url = safeUrl(data.url || data.link || '');
  const text = escapeHtml(data.text || data.link || url);
  if (!url) return `<p>${text}</p>`;
  return `<p class="article-link"><a href="${escapeHtml(url)}" rel="noopener noreferrer nofollow" target="_blank">${text}</a></p>`;
}

/**
 * Renders one Editor.js block. Unknown types degrade to a paragraph rather than
 * throwing, so a document written with a newer toolset still displays.
 */
function renderEditorBlock(block) {
  if (!block || typeof block !== 'object') return '';
  const data = block.data && typeof block.data === 'object' ? block.data : {};

  switch (block.type) {
    case 'header': {
      const level = Math.min(4, Math.max(1, Number(data.level) || 2));
      return `<h${level}>${inlineText(data.text)}</h${level}>`;
    }
    case 'list': {
      const tag = data.style === 'ordered' ? 'ol' : 'ul';
      const items = Array.isArray(data.items) ? data.items : [];
      const rendered = items
        .map((item) => {
          const content = typeof item === 'string' ? item : item?.content || '';
          return `<li>${inlineText(content)}</li>`;
        })
        .join('');
      return rendered ? `<${tag} class="article-list">${rendered}</${tag}>` : '';
    }
    case 'code':
      return renderCodeBlock(data);
    case 'delimiter':
      return '<hr class="article-delimiter" />';
    case 'quote':
      return `<blockquote>${inlineText(data.text)}${data.caption ? `<footer>${escapeHtml(data.caption)}</footer>` : ''}</blockquote>`;
    case 'image':
      return renderImageBlock(data);
    case 'linkTool':
      return renderLinkBlock(data);
    case 'raw':
      // Editor.js "raw" blocks hold arbitrary HTML — never trust them.
      return data.text ? `<p>${inlineText(data.text)}</p>` : '';
    case 'paragraph':
    default:
      return `<p>${inlineText(data.text)}</p>`;
  }
}

/**
 * Renders a pre-Editor.js body. Kept so an article written before the JSON
 * migration still reads correctly instead of rendering as one escaped blob.
 */
function renderLegacyText(content) {
  return String(content)
    .split(/\n{2,}/)
    .map((block) => {
      // Inline `code` spans first, so the backticks are not re-escaped below.
      const inline = escapeHtml(block).replace(/`([^`]+)`/g, '<code>$1</code>');
      if (block.startsWith('### ')) return `<h3>${inlineHtml(block.slice(4))}</h3>`;
      if (block.startsWith('## ')) return `<h2>${inlineHtml(block.slice(3))}</h2>`;
      if (block.startsWith('# ')) return `<h1>${inlineHtml(block.slice(2))}</h1>`;
      return `<p>${inline.replaceAll('\n', '<br />')}</p>`;
    })
    .join('');
}

/**
 * Entry point: stored article content -> HTML string.
 *
 * Accepts an Editor.js document object, a JSON-encoded string of one, or a
 * legacy plain-text body.  Returns an empty string for unusable input rather
 * than rendering "[object Object]" into the page.
 */
export function renderArticleContent(content) {
  if (content === null || content === undefined || content === '') return '';

  let document_ = content;

  if (typeof document_ === 'string') {
    const trimmed = document_.trim();
    if (trimmed.startsWith('{')) {
      try {
        document_ = JSON.parse(trimmed);
      } catch {
        return renderLegacyText(content);
      }
    } else {
      return renderLegacyText(content);
    }
  }

  if (typeof document_ !== 'object' || !Array.isArray(document_.blocks)) return '';

  const html = document_.blocks.map(renderEditorBlock).join('');
  // An empty document is a legitimate state for a draft; say so instead of
  // leaving a silent gap where the lesson should be.
  return html || '<p class="article-placeholder">This article has no content yet.</p>';
}

/** Extracts plain text for meta descriptions, search snippets and excerpts. */
export function contentToPlainText(content, maxLength = 220) {
  const parts = [];
  const push = (value) => {
    const text = stripInlineHtml(value);
    if (text) parts.push(text);
  };

  if (typeof content === 'string') {
    push(content);
  } else if (content && Array.isArray(content.blocks)) {
    for (const block of content.blocks) {
      const data = block?.data || {};
      if (typeof data.text === 'string') push(data.text);
      else if (typeof data.code === 'string') parts.push(data.code);
      else if (Array.isArray(data.items)) data.items.forEach((item) => push(item?.content ?? item));
      else if (typeof data.caption === 'string') push(data.caption);
      else if (typeof data.url === 'string') push(data.url);
    }
  }

  const clean = parts.join(' ').replace(/\s+/g, ' ').trim();
  return clean.length > maxLength ? `${clean.slice(0, maxLength - 1).trimEnd()}…` : clean;
}

/** Approximate reading time, shown in article bylines. */
export function readingTime(content) {
  const words = contentToPlainText(content, Number.MAX_SAFE_INTEGER).split(/\s+/).filter(Boolean).length;
  if (!words) return '';
  const minutes = Math.max(1, Math.round(words / 200));
  return `${minutes} min read`;
}

export function formatDate(value) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return new Intl.DateTimeFormat('en', { day: 'numeric', month: 'short', year: 'numeric' }).format(date);
}

/**
 * Shared article card markup, so the home page and the listing page render
 * identical cards and cannot drift apart.
 */
export function articleCardMarkup(article, { featured = false } = {}) {
  if (!article) return '';
  const slugOrId = article.slug || article.id;
  const href = `article.html?slug=${encodeURIComponent(slugOrId)}`;
  const image = safeUrl(article.featured_image);
  const summary = article.excerpt || '';
  // `author_name` is null for unattributed articles, so the byline is omitted
  // rather than rendered as a dangling separator.
  const authorName = (article.author_name || '').trim();

  return `
    <article class="article-card${featured ? ' article-card-featured' : ''}">
      ${image ? `<a class="article-card-media" href="${href}" tabindex="-1" aria-hidden="true"><img src="${escapeHtml(image)}" alt="" loading="lazy" /></a>` : ''}
      <div class="article-card-body">
        <p class="card-meta">
          ${article.category
            ? `<a href="articles.html?category=${encodeURIComponent(article.category.slug)}">${escapeHtml(article.category.name)}</a>`
            : '<span>General</span>'}
          <span aria-hidden="true">·</span>
          <time datetime="${escapeHtml(article.created_at || '')}">${escapeHtml(formatDate(article.created_at))}</time>
          ${featured ? '<span class="badge">Featured</span>' : ''}
        </p>
        <h3><a href="${href}">${escapeHtml(article.title)}</a></h3>
        ${authorName ? `<p class="card-byline">By ${escapeHtml(authorName)}</p>` : ''}
        ${summary ? `<p>${escapeHtml(summary)}</p>` : ''}
        <a class="text-link" href="${href}">Read article →</a>
      </div>
    </article>`;
}

/** Consistent empty / error block for any API-driven region. */
export function messageStateMarkup({ title, message, actionHref, actionLabel }) {
  return `
    <div class="empty-state">
      <h3>${escapeHtml(title)}</h3>
      ${message ? `<p>${escapeHtml(message)}</p>` : ''}
      ${actionHref ? `<a class="button button-secondary" href="${escapeHtml(actionHref)}">${escapeHtml(actionLabel || 'Continue')}</a>` : ''}
    </div>`;
}