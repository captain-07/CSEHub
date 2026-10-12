/**
 * Reader reactions on an article: a like/dislike pair with running counts.
 *
 * Authentication is required by the backend, so the control is only rendered
 * for signed-in readers — the same choice the assistant drawer makes, since
 * anonymous visitors cannot use it either. Hiding it outright (rather than
 * showing a disabled pair) avoids offering an action that cannot succeed.
 *
 * The widget is mounted once via `mount()` and then patched in-place: counts
 * and active state are updated directly on existing DOM nodes so buttons never
 * lose focus and no listeners need re-attaching after each reaction change.
 * An optimistic update is applied immediately on click and rolled back if the
 * network request fails.
 */

import { reactToArticle } from './api/articles.js';
import { initAuth, getAuthState, subscribeAuth } from './auth-state.js';

const REACTION_SLUG = 'article-reactions';

/** A reader's current verdict, updated as they react. */
let current = { value: null, likeCount: 0, dislikeCount: 0 };
let busy = false;

/**
 * Renders and wires the reaction control for `article`.
 *
 * @param {HTMLElement} root  element to search for the widget container in
 * @param {object} article    the article payload from `GET /api/articles/<key>/`
 */
export async function initReactions(root, article) {
  const container = root.querySelector(`#${REACTION_SLUG}`);
  if (!container) return;

  await initAuth();
  if (!getAuthState().user) {
    // Signed out: leave the container empty. The stylesheet hides an empty one,
    // so this costs nothing visually and avoids rendering dead controls.
    return;
  }

  current = {
    // `my_reaction` is null for readers who have not reacted yet.
    value: article.my_reaction ?? null,
    likeCount: Number(article.like_count) || 0,
    dislikeCount: Number(article.dislike_count) || 0,
  };

  mount(container);

  // Signing out mid-session must not leave a control that can only fail.
  subscribeAuth((state) => {
    if (state.status === 'anonymous') {
      container.innerHTML = '';
      current = { value: null, likeCount: 0, dislikeCount: 0 };
    }
  });
}

/** Builds the widget skeleton the first (and only) time. */
function mount(container) {
  container.innerHTML = `
    <p class="article-reactions-prompt">Was this helpful?</p>
    <div class="article-reactions-actions">
      ${buttonHTML('like', current.likeCount, current.value === 'like')}
      ${buttonHTML('dislike', current.dislikeCount, current.value === 'dislike')}
    </div>
    <p class="article-reactions-status" id="article-reactions-status" role="status" aria-live="polite"></p>
  `;

  container.querySelectorAll('[data-reaction]').forEach((el) => {
    el.addEventListener('click', () => handleChoice(container, el.dataset.reaction));
  });
}

function buttonHTML(value, count, active) {
  const isLike = value === 'like';
  const label = isLike ? 'Helpful' : 'Not helpful';
  const icon = isLike ? '&#128077;' : '&#128078;';
  return `
    <button
      type="button"
      class="reaction-button reaction-${value}${active ? ' is-active' : ''}"
      data-reaction="${value}"
      aria-pressed="${active ? 'true' : 'false'}"
    >
      <span class="reaction-icon" aria-hidden="true">${icon}</span>
      <span class="reaction-label">${label}</span>
      <span class="reaction-count" data-count="${value}">${count}</span>
    </button>`;
}

/**
 * Patches the existing button DOM in-place without re-rendering the whole widget.
 * Keeps focus on the button and avoids detaching / re-attaching listeners.
 *
 * @param {HTMLElement} container
 * @param {string|null} newValue   the verdict now stored (or null when cleared)
 * @param {number} likeCount
 * @param {number} dislikeCount
 */
function patch(container, newValue, likeCount, dislikeCount) {
  ['like', 'dislike'].forEach((v) => {
    const btn = container.querySelector(`[data-reaction="${v}"]`);
    if (!btn) return;

    const active = newValue === v;
    btn.classList.toggle('is-active', active);
    btn.setAttribute('aria-pressed', active ? 'true' : 'false');

    const countEl = btn.querySelector(`[data-count="${v}"]`);
    if (!countEl) return;

    const newCount = v === 'like' ? likeCount : dislikeCount;
    const oldCount = Number(countEl.textContent);

    if (newCount !== oldCount) {
      countEl.textContent = newCount;
      // Trigger the bump animation by forcing a reflow between class removals.
      countEl.classList.remove('count-bump');
      // eslint-disable-next-line no-unused-expressions
      void countEl.offsetWidth;
      countEl.classList.add('count-bump');
    }
  });
}

/**
 * Applies the reader's click with an optimistic update.
 *
 * Clicking the button that is already active withdraws the reaction. The
 * backend is asked for the state being requested rather than for a toggle, so a
 * dropped response that gets retried cannot flip the verdict back.
 */
async function handleChoice(container, choice) {
  if (busy) return;

  const desired = current.value === choice ? 'none' : choice;

  // --- Optimistic update ---
  const optimisticValue = desired === 'none' ? null : desired;
  let optimisticLike = current.likeCount;
  let optimisticDislike = current.dislikeCount;

  if (current.value === 'like') optimisticLike = Math.max(0, optimisticLike - 1);
  if (current.value === 'dislike') optimisticDislike = Math.max(0, optimisticDislike - 1);
  if (optimisticValue === 'like') optimisticLike += 1;
  if (optimisticValue === 'dislike') optimisticDislike += 1;

  patch(container, optimisticValue, optimisticLike, optimisticDislike);

  busy = true;
  setLoading(container, choice, true);
  clearStatus(container);

  try {
    const result = await reactToArticle(container.dataset.articleKey, desired);
    current = {
      value: result?.value ?? null,
      likeCount: Number(result?.like_count) || 0,
      dislikeCount: Number(result?.dislike_count) || 0,
    };
    // Reconcile with authoritative server counts (may differ from optimistic).
    patch(container, current.value, current.likeCount, current.dislikeCount);
  } catch (error) {
    console.error('Failed to record reaction', error);
    // Roll back the optimistic update.
    patch(container, current.value, current.likeCount, current.dislikeCount);
    setStatus(container, 'Your reaction could not be saved. Please try again.');
  } finally {
    busy = false;
    setLoading(container, choice, false);
  }
}

/** Marks a specific reaction button as loading and disables both during the request. */
function setLoading(container, choice, loading) {
  const btn = container.querySelector(`[data-reaction="${choice}"]`);
  if (btn) btn.classList.toggle('is-loading', loading);
  container.querySelectorAll('[data-reaction]').forEach((el) => {
    el.disabled = loading;
  });
}

function setStatus(container, message) {
  const status = container.querySelector('#article-reactions-status');
  // textContent, not innerHTML: the message is ours, but the element is the
  // wrong place to introduce an injection path.
  if (status) status.textContent = message;
}

function clearStatus(container) {
  setStatus(container, '');
}
