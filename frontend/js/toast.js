/**
 * Shared toast notifications.
 *
 * The site's existing feedback patterns are inline (form alert boxes, the
 * sticky admin status, the reaction status line) and those stay — toasts are
 * for confirmation-style events that happen away from the element the user is
 * looking at, such as a successful profile save.
 *
 * The root announces via `role="status"`/`aria-live="polite"`, so screen
 * readers hear the message without focus being stolen.
 */

import { escapeHtml } from './renderer.js';

const ROOT_ID = 'toast-root';

const DEFAULT_TIMEOUT = 4200;

function ensureRoot() {
  let root = document.getElementById(ROOT_ID);
  if (!root) {
    root = document.createElement('div');
    root.id = ROOT_ID;
    root.className = 'toast-root';
    root.setAttribute('role', 'status');
    root.setAttribute('aria-live', 'polite');
    document.body.appendChild(root);
  }
  return root;
}

/**
 * Shows a toast and returns its element.
 *
 * @param {string} message  plain text (escaped here — never pass markup)
 * @param {object} [options]
 * @param {'info'|'success'|'error'} [options.type]  colours the accent edge
 * @param {number} [options.timeout]  ms before auto-dismiss; 0 stays until closed
 */
export function showToast(message, { type = 'info', timeout = DEFAULT_TIMEOUT } = {}) {
  const root = ensureRoot();

  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.innerHTML = `
    <span class="toast-message">${escapeHtml(message)}</span>
    <button class="toast-close" type="button" aria-label="Dismiss notification">&times;</button>`;
  root.appendChild(toast);

  // Leaving is a two-step removal so a fade can play first.
  const dismiss = () => {
    if (!toast.isConnected || toast.classList.contains('is-leaving')) return;
    toast.classList.add('is-leaving');
    setTimeout(() => toast.remove(), 220);
  };

  toast.querySelector('.toast-close').addEventListener('click', dismiss);
  if (timeout > 0) setTimeout(dismiss, timeout);

  return toast;
}
