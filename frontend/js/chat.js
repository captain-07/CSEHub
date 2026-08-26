import { apiFetch, ApiError } from './api.js';
import { getCurrentUser } from './supabase.js';

let activeArticleSlug = null;
let activeArticleTitle = "";

const escapeHtml = (value = "") => String(value)
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;")
  .replaceAll("'", "&#039;");

/**
 * Opens the AI Chatbot side drawer for a specific article.
 * Automatically handles initializing HTML components, user auth checks, loading history, and sending questions.
 */
export async function openChatForArticle(slug, title) {
  activeArticleSlug = slug;
  activeArticleTitle = title;

  // 1. Check if user is authenticated first
  try {
    const user = await getCurrentUser();
    if (!user) {
      alert("Please log in to chat with the AI assistant.");
      window.location.href = `login.html?redirect=${encodeURIComponent(window.location.pathname + window.location.search)}`;
      return;
    }
  } catch (err) {
    console.error("Failed user verification for chat:", err);
    return;
  }

  // 2. Ensure DOM elements are created
  ensureChatElementsCreated();

  // 3. Update header titles
  document.querySelector("#chat-article-title").textContent = title;

  // 4. Open drawer visual state
  const drawer = document.querySelector("#chat-drawer");
  const overlay = document.querySelector("#chat-overlay");
  drawer.classList.add("open");
  overlay.classList.add("open");

  // 5. Fetch existing message history
  await loadConversationHistory();
}

function ensureChatElementsCreated() {
  if (document.querySelector("#chat-drawer")) return;

  // Create chat drawer elements
  const drawer = document.createElement("div");
  drawer.id = "chat-drawer";
  drawer.className = "chat-drawer";
  drawer.innerHTML = `
    <header class="chat-header">
      <div class="chat-header-title">
        <h2>CSEHub AI Assistant</h2>
        <p id="chat-article-title"></p>
      </div>
      <button class="chat-close-btn" id="chat-close-btn" aria-label="Close chat">✕</button>
    </header>
    <div class="chat-messages" id="chat-messages">
      <!-- Dynamically populated -->
    </div>
    <div class="chat-input-area">
      <form class="chat-form" id="chat-form">
        <input class="chat-input" id="chat-input" type="text" placeholder="Ask a question about this article..." required autocomplete="off" />
        <button class="button button-primary" id="chat-send-btn" type="submit">Send</button>
      </form>
    </div>
  `;

  const overlay = document.createElement("div");
  overlay.id = "chat-overlay";
  overlay.className = "chat-overlay";

  document.body.appendChild(overlay);
  document.body.appendChild(drawer);

  // Hook close events
  const closeBtn = drawer.querySelector("#chat-close-btn");
  const closeHandler = () => {
    drawer.classList.remove("open");
    overlay.classList.remove("open");
  };
  closeBtn.addEventListener("click", closeHandler);
  overlay.addEventListener("click", closeHandler);

  // Hook submit action
  const form = drawer.querySelector("#chat-form");
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    await handleSendMessage();
  });
}

async function loadConversationHistory() {
  const container = document.querySelector("#chat-messages");
  if (!container) return;

  container.innerHTML = `<div class="loading"><span class="loading-spinner"></span>Loading chat history…</div>`;

  try {
    const history = await apiFetch(`/articles/${activeArticleSlug}/conversation/`);
    
    // Clear loading state
    container.innerHTML = "";

    if (!history.messages || history.messages.length === 0) {
      // Welcome guide for new conversations
      container.innerHTML = `
        <div class="chat-message assistant">
          Hello! I can explain code snippets, answer questions, or dive deeper into the concepts mentioned in <strong>"${escapeHtml(activeArticleTitle)}"</strong>. What would you like to know?
        </div>
      `;
      return;
    }

    history.messages.forEach(msg => {
      appendMessageBubble(msg.role, msg.content);
    });
    scrollToBottom();
  } catch (error) {
    console.error("Failed to load chat history:", error);
    const message = error instanceof ApiError ? error.message : "Failed to load chat logs.";
    container.innerHTML = `
      <div class="chat-message assistant" style="color: var(--error);">
        <strong>Error loading history:</strong> ${escapeHtml(message)}
      </div>
    `;
  }
}

function appendMessageBubble(role, content) {
  const container = document.querySelector("#chat-messages");
  if (!container) return;

  const bubble = document.createElement("div");
  bubble.className = `chat-message ${role}`;
  bubble.innerHTML = `
    <div>${escapeHtml(content).replaceAll("\n", "<br />")}</div>
  `;
  container.appendChild(bubble);
}

function showTypingIndicator() {
  const container = document.querySelector("#chat-messages");
  if (!container) return;

  const indicator = document.createElement("div");
  indicator.id = "chat-typing";
  indicator.className = "chat-message assistant chat-loading";
  indicator.innerHTML = `
    <div class="chat-loading-dot"></div>
    <div class="chat-loading-dot"></div>
    <div class="chat-loading-dot"></div>
  `;
  container.appendChild(indicator);
  scrollToBottom();
}

function hideTypingIndicator() {
  document.querySelector("#chat-typing")?.remove();
}

function scrollToBottom() {
  const container = document.querySelector("#chat-messages");
  if (container) {
    container.scrollTop = container.scrollHeight;
  }
}

async function handleSendMessage() {
  const input = document.querySelector("#chat-input");
  const sendBtn = document.querySelector("#chat-send-btn");
  const question = input.value.trim();

  if (!question || !activeArticleSlug) return;

  // Optimistic UI update: show user bubble immediately
  appendMessageBubble("user", question);
  input.value = "";
  input.disabled = true;
  sendBtn.disabled = true;

  // Show thinking dots
  showTypingIndicator();

  try {
    const data = await apiFetch(`/articles/${activeArticleSlug}/ask/`, {
      method: "POST",
      body: { question }
    });

    hideTypingIndicator();

    // Fetch the last assistant message returned in conversation payload
    if (data.messages && data.messages.length > 0) {
      const assistantMsgs = data.messages.filter(m => m.role === 'assistant');
      const latestReply = assistantMsgs[assistantMsgs.length - 1];
      if (latestReply) {
        appendMessageBubble("assistant", latestReply.content);
      }
    }
  } catch (error) {
    console.error("AI chat failed:", error);
    hideTypingIndicator();
    
    const message = error instanceof ApiError ? error.message : "Service is temporarily unavailable.";
    appendMessageBubble("assistant", `Sorry, I ran into an error answering that: ${message}`);
  } finally {
    input.disabled = false;
    sendBtn.disabled = false;
    input.focus();
    scrollToBottom();
  }
}
