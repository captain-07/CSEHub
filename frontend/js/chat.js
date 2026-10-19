/**
 * Article learning assistant (RAG chat).
 *
 * The drawer is opened from the article page and is authenticated: the backend
 * scopes a conversation to (user, article), so an anonymous visitor is sent to
 * sign in first. Every failure mode is surfaced honestly — the backend answers
 * 503/502 when the AI provider is unreachable and never fabricates a reply.
 */

import { apiFetch, ApiError } from './api.js';
import { initAuth, getAuthState } from './auth-state.js';
import { escapeHtml, renderAssistantMarkup } from './renderer.js';

let activeArticleSlug = null;
let activeArticleTitle = '';
let busy = false;
/** Element to hand focus back to when the drawer closes. */
let previouslyFocused = null;

export async function openChatForArticle(slug, title) {
  activeArticleSlug = slug;
  activeArticleTitle = title;

  await initAuth();
  if (!getAuthState().user) {
    // The assistant is authenticated-only, so send the visitor to sign in and
    // return them to this exact article afterwards.
    const here = `${window.location.pathname}${window.location.search}`;
    window.location.href = `login.html?redirect=${encodeURIComponent(here)}`;
    return;
  }

  // Moved focus came here (e.g. the AI CTA button); close() sends it back.
  previouslyFocused = document.activeElement;

  ensureChatElementsCreated();
  setArticleTitle(title);
  setDrawerOpen(true);

  await loadConversationHistory();
}

function setArticleTitle(title) {
  const el = document.querySelector('#chat-article-title');
  if (el) el.textContent = title;
}

function setDrawerOpen(isOpen) {
  const drawer = document.querySelector('#chat-drawer');
  const overlay = document.querySelector('#chat-overlay');
  drawer?.classList.toggle('open', isOpen);
  overlay?.classList.toggle('open', isOpen);
  // Closed means off-screen *and* inert: without this the drawer stays in the
  // tab order and the accessibility tree, so Tab lands on an invisible Close
  // button and the article behind it is hidden from a screen reader.
  if (drawer) drawer.inert = !isOpen;
  if (isOpen) {
    // Move focus into the drawer so keyboard and screen-reader users are not
    // left behind on the article.
    document.querySelector('#chat-input')?.focus();
  } else {
    // Focus restore: the control that opened the drawer regains the keyboard,
    // so Tab continues from where the reader left the page.
    previouslyFocused?.focus?.();
    previouslyFocused = null;
  }
}

function ensureChatElementsCreated() {
  if (document.querySelector('#chat-drawer')) return;

  const drawer = document.createElement('div');
  drawer.id = 'chat-drawer';
  drawer.className = 'chat-drawer';
  drawer.setAttribute('role', 'dialog');
  drawer.setAttribute('aria-modal', 'true');
  drawer.setAttribute('aria-labelledby', 'chat-article-title');
  // Created closed, so it starts out of the tab order too.
  drawer.inert = true;
  drawer.innerHTML = `
    <header class="chat-header">
      <div class="chat-header-title">
        <h2>Learning assistant</h2>
        <p id="chat-article-title"></p>
      </div>
      <button class="chat-close-btn" id="chat-close-btn" aria-label="Close assistant">✕</button>
    </header>
    <div class="chat-messages" id="chat-messages" role="log" aria-live="polite"></div>
    <div class="chat-input-area">
      <form class="chat-form" id="chat-form">
        <label class="sr-only" for="chat-input">Ask a question about this article</label>
        <input class="chat-input" id="chat-input" type="text"
               placeholder="Ask a question about this article…"
               maxlength="1000" required autocomplete="off" />
        <button class="button button-primary" id="chat-send-btn" type="submit">Send</button>
      </form>
      <p class="chat-hint">Answers come from this article first, then general knowledge.</p>
    </div>
  `;

  const overlay = document.createElement('div');
  overlay.id = 'chat-overlay';
  overlay.className = 'chat-overlay';

  document.body.appendChild(overlay);
  document.body.appendChild(drawer);

  const close = () => setDrawerOpen(false);
  drawer.querySelector('#chat-close-btn').addEventListener('click', close);
  overlay.addEventListener('click', close);
  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape' || !drawer.classList.contains('open')) return;
    close();
  });

  // Focus containment: with a modal drawer open, Tab must not wander into the
  // article behind it. Cycles between the first and last focusable elements.
  drawer.addEventListener('keydown', (event) => {
    if (event.key !== 'Tab') return;
    const focusable = [...drawer.querySelectorAll(
      'button, input, [href], select, textarea, [tabindex]:not([tabindex="-1"])'
    )].filter((el) => !el.disabled && el.offsetParent !== null);
    if (!focusable.length) return;

    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });

  drawer.querySelector('#chat-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    await handleSendMessage();
  });
}

function scrollToBottom() {
  const container = document.querySelector('#chat-messages');
  if (container) container.scrollTop = container.scrollHeight;
}

function appendMessage(role, content) {
  const container = document.querySelector('#chat-messages');
  if (!container) return;

  const bubble = document.createElement('div');
  bubble.className = `chat-message ${role}`;
  // The assistant answers in light markdown (fenced code, inline code,
  // emphasis, lists); renderAssistantMarkup escapes first and re-admits only
  // the tags it builds. Questions and error copy stay plain escaped text.
  bubble.innerHTML = role === 'assistant'
    ? `<div>${renderAssistantMarkup(content)}</div>`
    : `<div>${escapeHtml(content).replaceAll('\n', '<br />')}</div>`;
  container.appendChild(bubble);
  scrollToBottom();
}

function showTypingIndicator() {
  const container = document.querySelector('#chat-messages');
  if (!container) return;

  const indicator = document.createElement('div');
  indicator.id = 'chat-typing';
  indicator.className = 'chat-message chat-loading';
  indicator.setAttribute('role', 'status');
  indicator.innerHTML = `
    <span class="chat-loading-dot"></span>
    <span class="chat-loading-dot"></span>
    <span class="chat-loading-dot"></span>
    <span class="sr-only">The assistant is thinking…</span>`;
  container.appendChild(indicator);
  scrollToBottom();
}

function hideTypingIndicator() {
  document.querySelector('#chat-typing')?.remove();
}

async function loadConversationHistory() {
  const container = document.querySelector('#chat-messages');
  if (!container) return;

  container.innerHTML = '<div class="loading"><span class="loading-spinner"></span>Loading conversation…</div>';

  try {
    const history = await apiFetch(`/articles/${encodeURIComponent(activeArticleSlug)}/conversation/`);
    container.innerHTML = '';

    if (!history?.messages?.length) {
      container.innerHTML = `
        <div class="chat-message assistant">
          Ask me about <strong>${escapeHtml(activeArticleTitle)}</strong> — I can explain a concept,
          walk through a code block, or give you another example. I answer from this article where
          it covers the point, and say so when I am giving a general explanation instead.
        </div>`;
      return;
    }

    history.messages.forEach((message) => appendMessage(message.role, message.content));
  } catch (error) {
    console.error('Failed to load chat history:', error);
    const message = error instanceof ApiError
      ? error.message
      : 'The conversation history could not be loaded.';
    container.innerHTML = '';
    appendMessage('error', `Could not load the conversation: ${message}`);
  }
}

/** Maps a backend failure onto wording that tells the user what to do next. */
function chatErrorMessage(error) {
  if (!(error instanceof ApiError)) return 'Something went wrong. Please try again.';
  if (error.status === 401) return 'Your session has expired. Sign in again to keep asking questions.';
  if (error.status === 403) return 'You do not have access to the assistant on this article.';
  if (error.status === 404) return 'This article is no longer available.';
  if (error.status === 503) return 'The assistant is not configured or is temporarily unavailable. Please try again shortly.';
  if (error.status === 502) return 'The assistant hit an unexpected error. Please try again.';
  if (error.status === 0) return 'Network error — check your connection and try again.';
  return error.message;
}

async function handleSendMessage() {
  const input = document.querySelector('#chat-input');
  const sendBtn = document.querySelector('#chat-send-btn');
  if (!input || !sendBtn || busy) return;

  const question = input.value.trim();
  if (!question || !activeArticleSlug) return;

  busy = true;
  appendMessage('user', question);
  input.value = '';
  input.disabled = true;
  sendBtn.disabled = true;
  showTypingIndicator();

  try {
    const data = await apiFetch(`/articles/${encodeURIComponent(activeArticleSlug)}/ask/`, {
      method: 'POST',
      body: { question },
    });

    hideTypingIndicator();

    // The endpoint returns the whole conversation, so the last assistant message
    // is the new answer.
    const replies = (data?.messages || []).filter((message) => message.role === 'assistant');
    const latest = replies[replies.length - 1];
    appendMessage('assistant', latest?.content || 'The assistant did not return an answer. Please try rephrasing your question.');
  } catch (error) {
    console.error('AI chat failed:', error);
    hideTypingIndicator();
    // The question bubble stays visible; the failure is shown as a distinct,
    // clearly non-answer bubble rather than being hidden.
    appendMessage('error', chatErrorMessage(error));
  } finally {
    busy = false;
    input.disabled = false;
    sendBtn.disabled = false;
    input.focus();
    scrollToBottom();
  }
}