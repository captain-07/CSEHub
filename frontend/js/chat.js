/**
 * Article learning assistant (RAG chat).
 *
 * The drawer is opened from the article page and is authenticated: the backend
 * scopes a conversation to (user, article), so an anonymous visitor is sent to
 * sign in first. Every failure mode is surfaced honestly — the backend answers
 * 503/502 when the AI provider is unreachable and never fabricates a reply.
 */

import { apiFetch, apiStream, readServerEvents, ApiError, friendlyError } from './api.js';
import { initAuth, getAuthState } from './auth-state.js';
import { escapeHtml, renderAssistantMarkup } from './renderer.js';

let activeArticleSlug = null;
let activeArticleTitle = '';
let activeArticleCategory = '';
let busy = false;
/** Element to hand focus back to when the drawer closes. */
let previouslyFocused = null;

export async function openChatForArticle(slug, title, options = {}) {
  const isSameArticle = activeArticleSlug === slug;
  const drawerAlreadyOpen = document.querySelector('#chat-drawer')?.classList.contains('open');

  activeArticleSlug = slug;
  activeArticleTitle = title;
  activeArticleCategory = typeof options === 'object' && options.category ? options.category : '';

  const question = typeof options === 'string' ? options : (options.question || '');
  const autoSend = typeof options === 'object' && Boolean(options.autoSend);

  await initAuth();
  if (!getAuthState().user) {
    // The assistant is authenticated-only, so send the visitor to sign in and
    // return them to this exact article afterwards.
    const here = `${window.location.pathname}${window.location.search}`;
    window.location.href = `login.html?redirect=${encodeURIComponent(here)}`;
    return;
  }

  // Moved focus came here (e.g. the AI CTA button); close() sends it back.
  if (!document.activeElement?.classList?.contains('selection-ai-btn')) {
    previouslyFocused = document.activeElement;
  }

  ensureChatElementsCreated();
  setArticleTitle(title);
  setDrawerOpen(true);

  if (!isSameArticle || !drawerAlreadyOpen) {
    await loadConversationHistory();
  }

  if (question) {
    const input = document.querySelector('#chat-input');
    if (input) {
      input.value = question;
      if (autoSend) {
        await handleSendMessage();
      } else {
        input.focus();
      }
    }
  }
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
  // Freeze the page behind the overlay, so a touch scroll moves the
  // conversation rather than the article under it.
  document.body.classList.toggle('chat-open', isOpen);
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
    if (previouslyFocused && typeof previouslyFocused.focus === 'function' && !previouslyFocused.hidden) {
      previouslyFocused.focus();
    } else {
      document.querySelector('#ask-ai-cta-btn')?.focus();
    }
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

function bindChatCodeBlocks(root) {
  root.querySelectorAll('.chat-copy-code-btn').forEach((button) => {
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
        console.error('Failed to copy chat code to clipboard', err);
        button.textContent = 'Press Ctrl+C';
        clearTimeout(button._copyTimeout);
        button._copyTimeout = setTimeout(() => {
          button.textContent = original;
        }, 2000);
      }
    });
  });

  const hljs = globalThis.hljs;
  if (!hljs || typeof hljs.highlightElement !== 'function') return;

  root.querySelectorAll('.chat-code-block pre code').forEach((el) => {
    const requested = (el.className.match(/language-([\w+#-]+)/) || [])[1];
    if (!requested) return;
    if (typeof hljs.getLanguage === 'function' && !hljs.getLanguage(requested)) return;
    try {
      hljs.highlightElement(el);
    } catch {
      // Keep plain code on parse error
    }
  });
}

function getContextualSuggestions(category = '') {
  const cat = String(category || '').toLowerCase();
  if (cat.includes('algorithm') || cat.includes('dsa') || cat.includes('data structure') || cat.includes('tree') || cat.includes('graph')) {
    return [
      { label: '💡 Core intuition', question: 'Explain the core intuition of this topic simply' },
      { label: '⏱️ Complexity & edge cases', question: 'What are the time/space complexities and common edge cases?' },
      { label: '🧪 Step-by-step trace', question: 'Can you walk through a step-by-step trace on a sample input?' },
      { label: '💻 Alternative approaches', question: 'What are common alternative approaches and their trade-offs?' },
    ];
  }
  if (cat.includes('system') || cat.includes('database') || cat.includes('network') || cat.includes('os') || cat.includes('distribut')) {
    return [
      { label: '💡 Core intuition', question: 'Explain the core intuition of this topic simply' },
      { label: '⚖️ Architectural trade-offs', question: 'What are the key architectural trade-offs and bottleneck risks?' },
      { label: '🛡️ Failure recovery', question: 'How does this handle failures, partitions, or node crashes?' },
      { label: '💻 Practical example', question: 'Can you give a real-world production or industry example?' },
    ];
  }
  return [
    { label: '💡 Core intuition', question: 'Explain the core intuition of this topic simply' },
    { label: '⏱️ Complexity breakdown', question: 'What are the time and space complexity trade-offs?' },
    { label: '🧪 Quiz me', question: 'Quiz me on this concept with 2 practice questions' },
    { label: '💻 Practical code example', question: 'Can you give a practical code example?' },
  ];
}

function bindSuggestionChips(root) {
  root.querySelectorAll('.chat-suggestion-chip').forEach((button) => {
    button.addEventListener('click', async () => {
      const question = button.dataset.question;
      if (!question || busy) return;
      const input = document.querySelector('#chat-input');
      if (input) {
        input.value = question;
        await handleSendMessage();
      }
    });
  });
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

  if (role === 'assistant') {
    bindChatCodeBlocks(bubble);
  }

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

/**
 * An assistant bubble that grows as the reply arrives.
 *
 * The text stays plain while it streams: re-rendering markdown on every token
 * would flicker, and a half-arrived fenced code block would be re-parsed on
 * each pass. The finished text is handed to the shared renderer once, so the
 * reply that lands is the same markup a stored reply produces.
 */
function beginStreamingReply() {
  const container = document.querySelector('#chat-messages');
  if (!container) return null;

  const bubble = document.createElement('div');
  bubble.className = 'chat-message assistant chat-message-streaming';
  bubble.innerHTML = '<div class="chat-stream-text"></div>';
  container.appendChild(bubble);
  scrollToBottom();
  return bubble;
}

function updateStreamingReply(bubble, text) {
  const body = bubble?.querySelector('.chat-stream-text');
  if (!body) return;
  // textContent, not innerHTML: the model's words are text, never markup.
  body.textContent = text;
  scrollToBottom();
}

function finishStreamingReply(bubble, text) {
  const body = bubble?.querySelector('.chat-stream-text');
  if (!body) return;
  bubble.classList.remove('chat-message-streaming');
  body.innerHTML = renderAssistantMarkup(text);
  bindChatCodeBlocks(bubble);
  scrollToBottom();
}

async function loadConversationHistory() {
  const container = document.querySelector('#chat-messages');
  if (!container) return;

  container.innerHTML = '<div class="loading"><span class="loading-spinner"></span>Loading conversation…</div>';

  try {
    const history = await apiFetch(`/articles/${encodeURIComponent(activeArticleSlug)}/conversation/`);
    container.innerHTML = '';

    if (!history?.messages?.length) {
      const suggestions = getContextualSuggestions(activeArticleCategory);
      container.innerHTML = `
        <div class="chat-message assistant">
          <div>
            <p>Ask me about <strong>${escapeHtml(activeArticleTitle)}</strong> — I can explain a concept,
            walk through a code block, or give you another example. I answer from this article where
            it covers the point, and say so when I am giving a general explanation instead.</p>
          </div>
        </div>
        <div class="chat-suggestions" aria-label="Suggested questions">
          <p class="chat-suggestions-title">Suggested questions</p>
          <div class="chat-suggestions-list">
            ${suggestions.map((item) => `
              <button type="button" class="chat-suggestion-chip" data-question="${escapeHtml(item.question)}">${escapeHtml(item.label)}</button>
            `).join('')}
          </div>
        </div>`;
      bindSuggestionChips(container);
      return;
    }

    history.messages.forEach((message) => appendMessage(message.role, message.content));
  } catch (error) {
    console.error('Failed to load chat history:', error);
    container.innerHTML = '';
    appendMessage('error', `Could not load the conversation: ${friendlyError(error)}`);
  }
}

/** Maps a backend failure onto wording that tells the user what to do next. */
function chatErrorMessage(error) {
  if (!(error instanceof ApiError)) return friendlyError(error);
  if (error.status === 401) return 'Your session has expired. Sign in again to keep asking questions.';
  if (error.status === 403) return 'You do not have access to the assistant on this article.';
  if (error.status === 404) return 'This article is no longer available.';
  if (error.status === 429) return 'You have reached the assistant\'s question limit. Please try again later.';
  if (error.status === 503) return 'The assistant is not configured or is temporarily unavailable. Please try again shortly.';
  if (error.status === 502) return 'The assistant hit an unexpected error. Please try again.';
  return friendlyError(error);
}

async function handleSendMessage() {
  const input = document.querySelector('#chat-input');
  const sendBtn = document.querySelector('#chat-send-btn');
  if (!input || !sendBtn || busy) return;

  const question = input.value.trim();
  if (!question || !activeArticleSlug) return;

  busy = true;
  document.querySelector('.chat-suggestions')?.remove();
  appendMessage('user', question);
  input.value = '';
  input.disabled = true;
  sendBtn.disabled = true;
  sendBtn.setAttribute('aria-busy', 'true');
  showTypingIndicator();

  // The reply bubble is created only once the server answers, so a refused
  // request leaves no empty bubble behind it.
  let reply = null;
  let received = '';

  try {
    const response = await apiStream(`/articles/${encodeURIComponent(activeArticleSlug)}/ask/stream/`, {
      method: 'POST',
      body: { question },
    });

    hideTypingIndicator();
    reply = beginStreamingReply();

    let failure = null;
    for await (const event of readServerEvents(response)) {
      if (event.type === 'delta' && typeof event.text === 'string') {
        received += event.text;
        updateStreamingReply(reply, received);
      } else if (event.type === 'error') {
        // The reply had already started, so the server could not change its
        // status. The failure travels in the stream instead.
        failure = event;
        break;
      } else if (event.type === 'done' && Array.isArray(event.conversation?.messages)) {
        // The stored reply is authoritative — it is exactly what the history
        // endpoint will return next time this drawer opens.
        const stored = event.conversation.messages.filter((message) => message.role === 'assistant');
        const latest = stored[stored.length - 1];
        if (latest?.content) received = latest.content;
      }
    }

    if (received) {
      finishStreamingReply(reply, received);
    } else {
      reply?.remove();
    }

    if (failure) {
      const message = failure.code === 'chat_unavailable'
        ? 'The assistant is not configured or is temporarily unavailable. Please try again shortly.'
        : (failure.detail || 'The assistant was interrupted. Please ask again.');
      throw new ApiError(message, 0, failure);
    }

    if (!received) {
      appendMessage('error', 'The assistant did not return an answer. Please try rephrasing your question.');
    }
  } catch (error) {
    console.error('AI chat failed:', error);
    hideTypingIndicator();
    if (!received) {
      // Nothing arrived: the bubble would be empty, so replace it with the
      // failure rather than leaving a blank reply on screen.
      reply?.remove();
      appendMessage('error', chatErrorMessage(error));
    } else {
      // Part of the reply did arrive. Keep it — it is what the model wrote —
      // and say plainly that it stopped early.
      appendMessage('error', `The reply stopped early. ${chatErrorMessage(error)}`);
    }
  } finally {
    busy = false;
    input.disabled = false;
    sendBtn.disabled = false;
    sendBtn.removeAttribute('aria-busy');
    input.focus();
    scrollToBottom();
  }
}