import { logoutUser } from './auth.js';
import { initAuth, subscribeAuth } from './auth-state.js';
import { escapeHtml, safeUrl } from './renderer.js';

/**
 * Injects the shared navigation bar into any `.site-header` element and keeps it
 * in sync with authentication state.
 *
 * The Admin link is rendered only when the backend profile reports
 * `is_admin`. That is a UX affordance only — `admin.js` re-checks the same
 * value, and the API independently enforces `IsAdminUser`.
 */

/** Works whether or not the host serves clean URLs (`/articles` vs `/articles.html`). */
function currentPage() {
  const path = window.location.pathname;
  const file = path.split('/').filter(Boolean).pop() || 'index.html';
  return file.replace(/\.html$/, '') || 'index';
}

function initials(name = '') {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return '?';
  return (parts.length === 1 ? parts[0].slice(0, 2) : parts[0][0] + parts[1][0]).toUpperCase();
}

function avatarMarkup(avatarUrl, name) {
  const url = safeUrl(avatarUrl);
  if (url) {
    return `<img class="user-avatar" src="${escapeHtml(url)}" alt="" referrerpolicy="no-referrer" />`;
  }
  return `<span class="user-avatar user-avatar-initials" aria-hidden="true">${escapeHtml(initials(name))}</span>`;
}

function searchFormMarkup() {
  return `
    <li class="nav-search">
      <form role="search" action="articles.html" method="get" class="nav-search-form">
        <label class="sr-only" for="nav-search-input">Search articles</label>
        <input
          class="nav-search-input"
          id="nav-search-input"
          type="search"
          name="search"
          placeholder="Search articles…"
          autocomplete="off"
        />
      </form>
    </li>`;
}

export function initNavbar() {
  const header = document.querySelector('.site-header');
  if (!header) return;

  header.innerHTML = `
    <div class="container">
      <a class="brand" href="index.html" aria-label="CSEHub home">
        <span class="brand-mark" aria-hidden="true">&lt;/&gt;</span>CSEHub
      </a>
      <button class="mobile-nav-toggle" type="button" aria-label="Toggle navigation" aria-expanded="false" aria-controls="nav-menu">☰</button>
      <nav aria-label="Primary navigation">
        <ul class="nav-menu" id="nav-menu"></ul>
      </nav>
    </div>`;

  const menu = header.querySelector('#nav-menu');
  const toggle = header.querySelector('.mobile-nav-toggle');

  toggle.addEventListener('click', () => {
    const expanded = toggle.getAttribute('aria-expanded') === 'true';
    toggle.setAttribute('aria-expanded', String(!expanded));
    toggle.textContent = expanded ? '☰' : '✕';
    menu.classList.toggle('active');
  });

  // Close the mobile menu after following a link inside it.
  menu.addEventListener('click', (event) => {
    if (event.target.closest('a')) {
      menu.classList.remove('active');
      toggle.setAttribute('aria-expanded', 'false');
      toggle.textContent = '☰';
    }
  });

  subscribeAuth((state) => renderMenu(menu, state));
  initAuth();
}

function renderMenu(menu, state) {
  const { ready, user, profile } = state;
  const page = currentPage();
  const active = (name) => (page === name ? ' active' : '');

  const primaryLinks = `
    <li><a class="nav-link${active('articles')}" href="articles.html">Articles</a></li>
    <li><a class="nav-link${active('categories')}" href="categories.html">Categories</a></li>
    ${searchFormMarkup()}`;

  if (!ready) {
    menu.innerHTML = `${primaryLinks}<li class="nav-link nav-loading">Loading account…</li>`;
    return;
  }

  if (!user) {
    // Google is the only sign-in method the site offers, so the link says so
    // rather than implying a password form that does not exist.
    menu.innerHTML = `
      ${primaryLinks}
      <li><a class="button button-primary nav-signin${active('login')}" href="login.html">Sign in with Google</a></li>`;
    return;
  }

  const displayName = profile?.display_name || profile?.username || user.email?.split('@')[0] || 'Student';
  const avatar = avatarMarkup(profile?.avatar_url || user.user_metadata?.avatar_url, displayName);

  menu.innerHTML = `
    ${primaryLinks}
    ${profile?.is_admin ? `<li><a class="nav-link${active('admin')}" href="admin.html">Admin</a></li>` : ''}
    <li>
      <a class="nav-link user-profile-badge${active('profile')}" href="profile.html" title="${escapeHtml(displayName)}">
        ${avatar}
        <span class="user-name">${escapeHtml(displayName)}</span>
      </a>
    </li>
    <li><button class="nav-link nav-logout" type="button" id="logout-link">Logout</button></li>`;

  const logoutBtn = menu.querySelector('#logout-link');
  if (logoutBtn) {
    logoutBtn.addEventListener('click', async (event) => {
      event.preventDefault();
      logoutBtn.disabled = true;
      try {
        await logoutUser();
      } catch (error) {
        console.error('Logout failed', error);
        logoutBtn.disabled = false;
      }
    });
  }
}