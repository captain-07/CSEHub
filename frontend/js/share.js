/**
 * Share control for an article.
 *
 * One button, two paths. The Web Share API is tried first: on a phone it opens
 * the system sheet, and it is the only route into installed apps. Where it is
 * missing — or where a desktop browser exposes it without a share target — the
 * link is copied to the clipboard instead. A dismissed sheet (`AbortError`) is
 * a decision, not a failure, so it stops there rather than copying a link the
 * reader did not ask for.
 *
 * The URL is rebuilt from the slug rather than read out of `location.href`, so
 * a reader who arrived through a campaign or filter parameter still shares the
 * canonical article link.
 */

import { showToast } from './toast.js';

/**
 * Wires the header share button for `article`.
 *
 * @param {HTMLElement} shell  element to search for the control in
 * @param {object} article     the article payload from `GET /api/articles/<key>/`
 */
export function initShare(shell, article) {
  const button = shell.querySelector('#article-share');
  if (!button) return;

  const url = articleUrl(article);
  const title = article.title || document.title;
  // `excerpt` is the closest thing to a one-line pitch; leaving it out is
  // better than sending the whole title twice.
  const text = article.excerpt || undefined;

  button.addEventListener('click', async () => {
    // Called before any `await` so the click still counts as the user gesture
    // the API requires.
    if (typeof navigator.share === 'function') {
      try {
        await navigator.share({ title, text, url });
        return;
      } catch (error) {
        if (error?.name === 'AbortError') return;
        // NotAllowedError, DataError, or a browser with no share target: the
        // clipboard is the fallback that always works.
        console.error('Native share failed, falling back to the clipboard', error);
      }
    }

    await copyLink(url);
  });
}

/** The article's own URL, without whatever query parameters the reader arrived with. */
function articleUrl(article) {
  const url = new URL(window.location.href);
  url.search = '';
  url.hash = '';

  const key = article.slug || article.id;
  if (key) url.searchParams.set('slug', key);
  return url.toString();
}

async function copyLink(url) {
  try {
    await navigator.clipboard.writeText(url);
    showToast('Link copied to your clipboard.', { type: 'success' });
  } catch (error) {
    console.error('Failed to copy the share link', error);
    // The address bar still holds the page, so point at the recovery that is
    // actually available rather than offering a retry of the same failure.
    showToast('Could not copy the link. Copy it from the address bar instead.', {
      type: 'error',
      timeout: 8000,
    });
  }
}
