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

/**
 * Maps the `language` value stored on a code block to a highlight.js language
 * name. `language` is unvalidated free text on the API and the editor only
 * offers a fixed list, so an old or hand-written value may be absent, an
 * alias, or something no grammar exists for.
 *
 * A null return means "do not highlight" — highlight.js would otherwise fall
 * back to guessing the language from the code itself and confidently colour
 * keywords in a language it got wrong.
 */
const HIGHLIGHT_LANGUAGES = {
  python: 'python',
  py: 'python',
  javascript: 'javascript',
  js: 'javascript',
  jsx: 'javascript',
  typescript: 'typescript',
  ts: 'typescript',
  tsx: 'typescript',
  java: 'java',
  c: 'c',
  cpp: 'cpp',
  'c++': 'cpp',
  cplusplus: 'cpp',
  csharp: 'csharp',
  'c#': 'csharp',
  cs: 'csharp',
  go: 'go',
  golang: 'go',
  rust: 'rust',
  rs: 'rust',
  sql: 'sql',
  bash: 'bash',
  sh: 'bash',
  shell: 'bash',
  zsh: 'bash',
  html: 'xml',
  xml: 'xml',
  svg: 'xml',
  css: 'css',
  json: 'json',
  yaml: 'yaml',
  yml: 'yaml',
};

/**
 * Markup for a code snippet, shared by Editor.js code blocks and the
 * `code_snippets` relation.
 *
 * Both storage paths exist (a block's language lives inside `Article.content`,
 * a CodeSnippet row carries its own), so they rendered this markup separately
 * and had to be kept in sync by hand. One function keeps them from drifting.
 */
export function snippetMarkup({ code = '', language = '' } = {}) {
  const text = typeof code === 'string' ? code : '';
  const label = typeof language === 'string' ? language.trim() : '';
  const known = HIGHLIGHT_LANGUAGES[label.toLowerCase()] || '';
  // The class carries the grammar, not the raw label: an unrecognised value
  // would otherwise emit a class that no stylesheet matches.
  const codeClass = known ? ` class="language-${escapeHtml(known)}"` : '';
  return `<section class="snippet">`
    + `<div class="snippet-bar">`
    + `<span class="snippet-lang">${escapeHtml(label || 'code')}</span>`
    + `<button class="copy-button" type="button" data-code="${encodeURIComponent(text)}">Copy code</button>`
    + `</div>`
    + `<pre><code${codeClass}>${escapeHtml(text)}</code></pre>`
    + `</section>`;
}

/**
 * Highlight every rendered snippet under `root`.
 *
 * Must run after the markup is in the DOM, and must tolerate highlight.js
 * being absent: it is loaded from a CDN like Supabase and Editor.js, so a
 * blocked or failed request should leave readable plain code rather than
 * break the page.
 */
export function highlightSnippets(root = document) {
  // Read via globalThis, not `window`: highlight.js still attaches to the
  // window object in a browser (where they are the same), but this module is
  // also imported under Node by the repo's editor-tool checks, where a bare
  // `window` reference throws instead of being undefined.
  const hljs = globalThis.hljs;
  if (!hljs || typeof hljs.highlightElement !== 'function') return 0;

  let count = 0;
  root.querySelectorAll('.snippet pre code').forEach((el) => {
    const requested = (el.className.match(/language-([\w+#-]+)/) || [])[1];
    // `snippetMarkup` only emits a class for languages it recognises, so a
    // missing one means "plain text" and the block is left alone.
    if (!requested) return;
    // The class comes from our own lookup table, but markup can also arrive
    // from another source; skip rather than let highlight.js guess.
    if (typeof hljs.getLanguage === 'function' && !hljs.getLanguage(requested)) return;
    try {
      hljs.highlightElement(el);
      count += 1;
    } catch (err) {
      // One unparseable block must not strip highlighting from the rest.
      console.error('Syntax highlighting failed', err);
    }
  });
  return count;
}

function renderCodeBlock(data) {
  return snippetMarkup({ code: data.code, language: data.language });
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
 * Reader-facing view tally, pluralised.
 *
 * Shared so the card and the article page cannot disagree about "1 view" versus
 * "1 views". The locale is pinned to `en-US` for the thousands separator, for
 * the same reason `formatDate` pins `en`: the surrounding copy is English, and
 * a browser set to German would otherwise render "1.204 views" mid-sentence.
 */
export function formatViews(count) {
  const total = Number(count) || 0;
  return `${total.toLocaleString('en-US')} ${total === 1 ? 'view' : 'views'}`;
}

/*
 * The providers this site will frame inline, and what a valid id looks like for
 * each. The id is the *only* thing taken from a pasted URL: the frame's source is
 * rebuilt from these templates, so a URL that points somewhere else can never
 * become the `src`. Anything unrecognised degrades to a plain link instead.
 */
const YOUTUBE_HOSTS = new Set([
  'youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com',
  'youtube-nocookie.com', 'www.youtube-nocookie.com', 'youtu.be',
]);
const VIMEO_HOSTS = new Set(['vimeo.com', 'www.vimeo.com', 'player.vimeo.com']);
const YOUTUBE_ID = /^[A-Za-z0-9_-]{6,20}$/;
const VIMEO_ID = /^\d{5,12}$/;

/** Pulls the video id out of the several URL shapes YouTube hands out. */
function youTubeVideoId(url) {
  const explicit = url.searchParams.get('v');
  if (explicit && YOUTUBE_ID.test(explicit)) return explicit;

  const segments = url.pathname.split('/').filter(Boolean);
  // /embed/, /shorts/, /live/ and /v/ put the id second; youtu.be/<id> puts it
  // first, as does a bare youtube.com/<id> (which does not resolve, but parses).
  const candidate = ['embed', 'shorts', 'live', 'v'].includes(segments[0])
    ? segments[1]
    : segments[0];
  return candidate && YOUTUBE_ID.test(candidate) ? candidate : '';
}

/** Vimeo puts the id last, except on the player host, where it follows /video. */
function vimeoVideoId(url) {
  const segments = url.pathname.split('/').filter(Boolean);
  const candidate = segments[0] === 'video' ? segments[1] : segments[segments.length - 1];
  return candidate && VIMEO_ID.test(candidate) ? candidate : '';
}

/**
 * Classifies a pasted video URL.
 *
 * Resolves to `null` when there is nothing to show, `{provider, id, src}` when
 * the URL is a video on a provider this site is willing to frame, and
 * `{provider: null, href}` for anything else — the caller renders that last case
 * as a link, never as an embed.
 *
 * Parsed without a base on purpose: a video link has to be absolute, and
 * resolving a relative or blank string against the site would turn a typo into a
 * link pointing at our own origin.
 */
export function videoEmbed(candidate) {
  if (typeof candidate !== 'string') return null;

  let url;
  try {
    url = new URL(candidate.trim());
  } catch {
    return null;
  }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') return null;

  const host = url.hostname.toLowerCase();

  if (YOUTUBE_HOSTS.has(host)) {
    const id = youTubeVideoId(url);
    if (id) {
      return {
        provider: 'YouTube',
        id,
        // The nocookie host serves the same player without setting tracking
        // cookies before playback, which is the point of the facade below.
        src: `https://www.youtube-nocookie.com/embed/${id}`,
      };
    }
  }

  if (VIMEO_HOSTS.has(host)) {
    const id = vimeoVideoId(url);
    if (id) {
      return { provider: 'Vimeo', id, src: `https://player.vimeo.com/video/${id}` };
    }
  }

  return { provider: null, href: url.href };
}

/**
 * The player (or the link) for an article's optional video.
 *
 * A recognised provider renders as a real frame whose source is the one
 * `videoEmbed` assembled out of an allow-listed host and a validated id — never
 * the stored string, which is the whole security property here. The frame is
 * embedded directly rather than behind a click-to-load facade: the reader gets
 * the player without pressing anything, and a provider's scripts and cookies
 * therefore load with the article. Anything that cannot be embedded renders as
 * an outbound link — never a frame, because that frame's source would be an
 * unvetted URL.
 */
export function videoMarkup(videoUrl, { title = '' } = {}) {
  const video = videoEmbed(videoUrl);
  if (!video) return '';

  const label = video.provider ? `Watch on ${video.provider}` : 'Watch the video';

  if (!video.src) {
    return `
      <aside class="article-video article-video-external">
        <span class="article-video-heading">Video</span>
        <a class="article-video-link" href="${escapeHtml(video.href)}" target="_blank" rel="noopener noreferrer">
          ${escapeHtml(label)} →
        </a>
      </aside>`;
  }

  return `
    <aside class="article-video">
      <iframe class="article-video-frame" src="${escapeHtml(video.src)}"
        title="${escapeHtml(title || label)}" loading="lazy"
        referrerpolicy="strict-origin-when-cross-origin"
        allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
        allowfullscreen></iframe>
    </aside>`;
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
  const authorName = (article.author_name || '').trim();
  // The list endpoint omits `content`, so the server now sends a ready-made
  // `reading_time`; the local computation stays as a fallback for detail views.
  const rt = article.reading_time || readingTime(article.content);
  // Likes stay gated on a positive count — a zero adds nothing there.
  const likes = Number(article.like_count) || 0;
  // Reads are not gated: a zero is itself information ("nobody has opened this
  // yet"), and hiding it made a freshly-migrated library look as though the
  // counter had never shipped at all.
  const views = Number(article.view_count) || 0;
  const categoryName = (article.category && article.category.name) || 'General';
  // Every card gets a media strip, so no card starts its text at a different
  // height from its neighbours. Without a cover, the strip carries the subject
  // as a large ghosted word rather than sitting there blank.
  const media = image
    ? `<a class="article-card-media" href="${href}" tabindex="-1" aria-hidden="true"><img src="${escapeHtml(image)}" alt="" loading="lazy" /></a>`
    : `<span class="article-card-media article-card-media-empty" aria-hidden="true"><span class="article-card-media-empty-label">${escapeHtml(categoryName)}</span></span>`;

  return `
    <article class="article-card${featured ? ' article-card-featured' : ''}">
      ${media}
      <div class="article-card-body">
        <p class="card-meta">
          ${featured ? '<span class="badge">Featured</span>' : ''}
          ${article.category
            ? `<a href="articles.html?category=${encodeURIComponent(article.category.slug)}">${escapeHtml(article.category.name)}</a>`
            : '<span>General</span>'}
          <time datetime="${escapeHtml(article.created_at || '')}">${escapeHtml(formatDate(article.created_at))}</time>
          ${rt ? `<span class="card-reading-time">${escapeHtml(rt)}</span>` : ''}
        </p>
        <h3><a href="${href}">${escapeHtml(article.title)}</a></h3>
        ${authorName ? `<p class="card-byline">By ${escapeHtml(authorName)}</p>` : ''}
        ${summary ? `<p>${escapeHtml(summary)}</p>` : ''}
        <div class="card-foot">
          <span class="card-stats">
            ${likes > 0 ? `<span class="card-likes">&#128077; ${likes}</span>` : ''}
            <span class="card-views">&#128065; ${escapeHtml(formatViews(views))}</span>
          </span>
          <a class="text-link" href="${href}">Read article →</a>
        </div>
      </div>
    </article>`;
}

/** Consistent empty / error block for any API-driven region. */
export function messageStateMarkup({ title, message, actionHref, actionLabel, icon = '\uD83D\uDD0D' }) {
  return `
    <div class="empty-state">
      <span class="empty-state-icon" aria-hidden="true">${icon}</span>
      <h3>${escapeHtml(title)}</h3>
      ${message ? `<p>${escapeHtml(message)}</p>` : ''}
      ${actionHref ? `<a class="button button-secondary" href="${escapeHtml(actionHref)}">${escapeHtml(actionLabel || 'Continue')}</a>` : ''}
    </div>`;
}

/**
 * Placeholder grid shown while a card listing is loading, so the page keeps its
 * finished shape (skeleton) rather than collapsing to a spinner. Count matches
 * the rendered grid's typical density; without images the media strip stays
 * out (same rule real cards follow).
 */
export function skeletonCardsMarkup({ count = 6, withImage = true } = {}) {
  const card = `
    <article class="skeleton-card" aria-hidden="true">
      ${withImage ? '<div class="skeleton skeleton-media"></div>' : ''}
      <div class="article-card-body">
        <div class="skeleton skeleton-line skeleton-line-1"></div>
        <div class="skeleton skeleton-line skeleton-line-title skeleton-line-2"></div>
        <div class="skeleton skeleton-line skeleton-line-3"></div>
        <div class="skeleton skeleton-line skeleton-line-4"></div>
      </div>
    </article>`;
  return `<div class="article-grid">${card.repeat(count)}</div>`;
}

/*
 * Assistant replies — a deliberately small markdown subset.
 *
 * The model answers in prose with fenced code, inline backticks and emphasis,
 * so rendering the raw string leaves the code answers unreadable. This handles
 * exactly the constructs the assistant is asked to produce: fenced code,
 * inline code, bold, italic, links and lists. It keeps the module's rule —
 * escape first, then re-admit only the tags built here — so a reply can never
 * inject markup, and it adds no dependency.
 */

const ASSISTANT_LINK_RE = /\[([^\]\n]+)\]\(([^)\s]+)\)/g;

/** Escapes a line, then renders its inline code, links and emphasis. */
function assistantInline(text) {
  const codeSpans = [];
  // Code spans come out first so emphasis inside them is left untouched.
  let output = escapeHtml(text).replace(/`([^`\n]+)`/g, (_, code) => {
    codeSpans.push(`<code>${code}</code>`);
    return `\u0000${codeSpans.length - 1}\u0000`;
  });

  output = output.replace(ASSISTANT_LINK_RE, (whole, label, url) => {
    const href = safeUrl(url);
    // An unusable link stays as plain text rather than becoming a dead anchor.
    return href
      ? `<a href="${escapeHtml(href)}" target="_blank" rel="noopener noreferrer nofollow">${label}</a>`
      : whole;
  });
  output = output.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');
  // A single `*` only opens emphasis at a word boundary and for non-space
  // content, so "2 * 3 * 4" and bullet markers are left alone.
  output = output.replace(/(^|[\s([{“"'])\*([^\s*][^*\n]*?)\*(?!\*)/g, '$1<em>$2</em>');

  return output.replace(/\u0000(\d+)\u0000/g, (_, index) => codeSpans[Number(index)]);
}

/** Renders the non-code lines of a reply into paragraphs and lists. */
function assistantProse(text) {
  const blocks = [];
  let paragraph = [];
  let list = null;

  const flushParagraph = () => {
    if (!paragraph.length) return;
    blocks.push(`<p>${paragraph.map(assistantInline).join('<br />')}</p>`);
    paragraph = [];
  };
  const flushList = () => {
    if (!list) return;
    const tag = list.ordered ? 'ol' : 'ul';
    blocks.push(`<${tag}>${list.items.map((item) => `<li>${assistantInline(item)}</li>`).join('')}</${tag}>`);
    list = null;
  };

  for (const raw of text.split('\n')) {
    const line = raw.trimEnd();
    if (!line.trim()) {
      flushParagraph();
      flushList();
      continue;
    }

    const bullet = /^\s*[-*+]\s+(.*)$/.exec(line);
    const numbered = /^\s*\d+[.)]\s+(.*)$/.exec(line);
    if (bullet || numbered) {
      flushParagraph();
      const ordered = Boolean(numbered);
      if (list && list.ordered !== ordered) flushList();
      if (!list) list = { ordered, items: [] };
      list.items.push((bullet || numbered)[1]);
      continue;
    }

    flushList();
    const heading = /^\s{0,3}#{1,6}\s+(.*)$/.exec(line);
    // A heading becomes a bold paragraph: a chat reply has no document
    // outline, so real heading levels would only mislead a screen reader.
    paragraph.push(heading ? `**${heading[1].replaceAll('*', '')}**` : line);
  }

  flushParagraph();
  flushList();
  return blocks.join('');
}

/** Renders a fenced code block; the language and the code are both escaped. */
function assistantCode(code, language) {
  // A fence with nothing in it is a rendering artefact — typically an unclosed
  // fence at the end of a reply — and an empty dark box looks broken.
  if (code.trim() === '') return '';

  const label = language ? ` class="language-${escapeHtml(language)}"` : '';
  return `<pre><code${label}>${escapeHtml(code)}</code></pre>`;
}

/**
 * Turns one assistant reply into safe HTML. Fenced code is preserved verbatim;
 * everything between the fences is escaped and lightly marked up.
 */
export function renderAssistantMarkup(value = '') {
  const lines = String(value ?? '').replaceAll('\r\n', '\n').split('\n');
  const output = [];
  let prose = [];

  const flushProse = () => {
    if (!prose.length) return;
    output.push(assistantProse(prose.join('\n')));
    prose = [];
  };

  for (let index = 0; index < lines.length; index += 1) {
    const fence = /^\s*```(.*)$/.exec(lines[index]);
    if (!fence) {
      prose.push(lines[index]);
      continue;
    }

    flushProse();
    const language = fence[1].trim();
    const code = [];
    index += 1;
    while (index < lines.length && !/^\s*```\s*$/.test(lines[index])) {
      code.push(lines[index]);
      index += 1;
    }
    // An unterminated fence still renders as a block, so three stray backticks
    // never leak into the prose.
    output.push(assistantCode(code.join('\n'), language));
  }

  flushProse();
  return output.join('');
}