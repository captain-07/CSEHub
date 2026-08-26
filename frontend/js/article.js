import { getArticle } from './api/articles.js';
import { ApiError } from './api.js';
import { initNavbar } from './navbar.js';
import { openChatForArticle } from './chat.js';

const escapeHtml = (value = "") => String(value)
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;")
  .replaceAll("'", "&#039;");

function formatDate(value) {
  return new Intl.DateTimeFormat("en", { day: "numeric", month: "short", year: "numeric" }).format(new Date(value));
}

function tagsMarkup(tags = []) {
  return tags.map((tag) => `<a class="tag" href="articles.html?tag=${encodeURIComponent(tag.slug)}">${escapeHtml(tag.name)}</a>`).join("");
}

function renderContent(content = "") {
  // Simple markdown-to-HTML parser for safe rendering
  return escapeHtml(content)
    .split(/\n{2,}/)
    .map((block) => {
      if (block.startsWith("## ")) {
        return `<h2>${block.slice(3)}</h2>`;
      }
      if (block.startsWith("# ")) {
        return `<h1>${block.slice(2)}</h1>`;
      }
      return `<p>${block.replace(/`([^`]+)`/g, "<code>$1</code>").replaceAll("\n", "<br />")}</p>`;
    })
    .join("");
}

async function initArticle() {
  const query = new URLSearchParams(location.search);
  const articleId = query.get("id");
  const shell = document.querySelector("#article-shell");

  if (!articleId) {
    if (shell) {
      shell.innerHTML = `
        <div class="empty-state">
          <h2>Article Not Found</h2>
          <p>No valid article ID was provided in the URL.</p>
          <a class="button button-primary" href="articles.html">Browse Articles</a>
        </div>
      `;
    }
    return;
  }

  try {
    if (shell) {
      shell.innerHTML = `<div class="loading"><span class="loading-spinner"></span>Loading article…</div>`;
    }

    const article = await getArticle(articleId);

    const snippetsMarkup = article.code_snippets?.map((snippet) => `
      <section class="snippet">
        <div>
          <span>${escapeHtml(snippet.language)}</span>
          <button class="copy-button" type="button" data-code="${encodeURIComponent(snippet.code)}">Copy code</button>
        </div>
        <pre><code>${escapeHtml(snippet.code)}</code></pre>
      </section>
    `).join("") || "";

    if (shell) {
      shell.innerHTML = `
        <article>
          <header class="article-header">
            <div class="card-meta">
              ${article.category ? `<a href="articles.html?category=${encodeURIComponent(article.category.slug)}">${escapeHtml(article.category.name)}</a>` : "General"}
              <span>·</span>
              <time datetime="${article.created_at}">${formatDate(article.created_at)}</time>
            </div>
            <h1>${escapeHtml(article.title)}</h1>
            <div class="tag-list">${tagsMarkup(article.tags)}</div>
            ${article.author_email ? `<p class="byline">Published by ${escapeHtml(article.author_email)}</p>` : ""}
          </header>
          
          <div class="article-content">
            ${renderContent(article.content)}
          </div>
          
          ${snippetsMarkup}

          <!-- Ask AI Section -->
          <section class="article-ai-cta">
            <div class="article-ai-cta-content">
              <h3>Have questions about this article?</h3>
              <p>Ask our AI-powered learning assistant for explanations, alternative code examples, or conceptual breakdowns.</p>
            </div>
            <button class="button button-primary" id="ask-ai-cta-btn" type="button">Ask AI Assistant</button>
          </section>
        </article>
      `;

      // Copy buttons handler
      document.querySelectorAll(".copy-button").forEach((button) => {
        button.addEventListener("click", async () => {
          try {
            await navigator.clipboard.writeText(decodeURIComponent(button.dataset.code));
            button.textContent = "Copied!";
            button.style.borderColor = "var(--success)";
            setTimeout(() => {
              button.textContent = "Copy code";
              button.style.borderColor = "#506157";
            }, 2000);
          } catch (err) {
            console.error("Failed to copy code to clipboard", err);
          }
        });
      });

      // Ask AI button trigger
      const askAiBtn = document.querySelector("#ask-ai-cta-btn");
      if (askAiBtn) {
        askAiBtn.addEventListener("click", () => {
          // Open Chat drawer using article slug
          openChatForArticle(article.slug, article.title);
        });
      }
    }
  } catch (error) {
    console.error("Failed to fetch article details:", error);
    if (shell) {
      const message = error instanceof ApiError ? error.message : "We couldn't retrieve the article content.";
      shell.innerHTML = `
        <div class="empty-state" role="alert">
          <h2>Failed to load article</h2>
          <p>${escapeHtml(message)}</p>
          <a class="button button-secondary" href="articles.html">Back to Articles</a>
        </div>
      `;
    }
  }
}

document.addEventListener("DOMContentLoaded", () => {
  initNavbar();
  initArticle();
});
