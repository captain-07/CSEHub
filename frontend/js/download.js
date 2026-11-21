/**
 * The PDF edition of a paid article.
 *
 * The button only exists when the server already said `has_access`, but that is
 * presentation: `/articles/<slug>/pdf/` re-checks the purchase and answers 402
 * when it is gone (a refund can land while the page is open). Nothing is cached
 * here — the file is fetched once per press and handed straight to the
 * browser's download machinery.
 */

import { friendlyError } from './api.js';
import { getArticlePdf } from './api/articles.js';
import { showToast } from './toast.js';

// Rendering happens server-side and a long article may take a while; the
// default 20 s read timeout is not meant for building a document.
const DOWNLOAD_TIMEOUT_MS = 60_000;

/** Hand a blob to the browser as a file download. */
function saveBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.rel = 'noopener';
  // Appended because a detached anchor is not clickable in every browser;
  // hidden rather than styled, so no class needs a rule.
  anchor.hidden = true;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  // Revoking immediately cancels the download in some browsers, so hold the
  // reference until the transfer has certainly started.
  setTimeout(() => URL.revokeObjectURL(url), 30_000);
}

export function initPdfDownload(shell, article) {
  const button = shell.querySelector('#article-download');
  if (!button) return;

  const label = button.textContent;

  button.addEventListener('click', async () => {
    if (button.disabled) return;
    button.disabled = true;
    button.textContent = 'Preparing PDF…';

    try {
      const blob = await getArticlePdf(article.slug || article.id, {
        timeout: DOWNLOAD_TIMEOUT_MS,
      });
      saveBlob(blob, `${article.slug || 'article'}.pdf`);
      showToast('Your PDF is downloading.', { type: 'success' });
    } catch (error) {
      // A 402 here is meaningful: access was revoked after the page loaded, so
      // say so instead of offering a retry that cannot succeed.
      showToast(
        error?.status === 402
          ? 'This article is no longer available to download. Refresh the page to see your access.'
          : friendlyError(error),
        { type: 'error', timeout: 8000 }
      );
    } finally {
      button.disabled = false;
      button.textContent = label;
    }
  });
}
