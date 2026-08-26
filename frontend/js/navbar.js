import { getSupabase, getCurrentUser } from './supabase.js';
import { logoutUser, onAuthChange } from './auth.js';
import { apiFetch } from './api.js';

/**
 * Injects and initializes the shared navigation bar into any element with the class `site-header`.
 * Observes authentication changes and updates link visibility, avatar, and user names dynamically.
 */
export function initNavbar() {
  const header = document.querySelector('.site-header');
  if (!header) return;

  // Render the base skeleton
  header.innerHTML = `
    <div class="container">
      <a class="brand" href="index.html" aria-label="CSEHub home">
        <span class="brand-mark">&lt;/&gt;</span>CSEHub
      </a>
      <button class="mobile-nav-toggle" aria-label="Toggle navigation" aria-expanded="false">☰</button>
      <nav aria-label="Primary navigation">
        <ul class="nav-menu" id="nav-menu">
          <!-- Populated dynamically -->
        </ul>
      </nav>
    </div>
  `;

  const menu = header.querySelector('#nav-menu');
  const toggle = header.querySelector('.mobile-nav-toggle');

  // Toggle mobile navigation menu
  toggle.addEventListener('click', () => {
    const expanded = toggle.getAttribute('aria-expanded') === 'true';
    toggle.setAttribute('aria-expanded', !expanded);
    toggle.textContent = expanded ? '☰' : '✕';
    menu.classList.toggle('active');
  });

  // Track authentication changes to update navigation
  onAuthChange(async (event, session) => {
    await updateNavbarLinks(menu, session?.user || null);
  });

  // Initial update
  getCurrentUser().then(user => {
    updateNavbarLinks(menu, user);
  });
}

async function updateNavbarLinks(menu, user) {
  const currentPath = window.location.pathname;
  const isIndexActive = currentPath.endsWith('index.html') || currentPath === '/' || currentPath.endsWith('/');
  const isArticlesActive = currentPath.includes('articles.html') || currentPath.includes('article.html');
  const isProfileActive = currentPath.includes('profile.html');
  const isLoginActive = currentPath.includes('login.html');

  if (!user) {
    // Guest User Links
    menu.innerHTML = `
      <li><a class="nav-link ${isIndexActive ? 'active' : ''}" href="index.html">Home</a></li>
      <li><a class="nav-link ${isArticlesActive ? 'active' : ''}" href="articles.html">Articles</a></li>
      <li><a class="nav-link ${isLoginActive ? 'active' : ''}" href="login.html">Login</a></li>
    `;
  } else {
    // Authenticated User Links
    let displayName = user.email.split('@')[0];
    let avatarUrl = "https://www.gravatar.com/avatar/00000000000000000000000000000000?d=mp&f=y"; // Default avatar placeholder
    
    // Attempt to fetch profile details from backend
    try {
      const djangoProfile = await apiFetch('/me/');
      if (djangoProfile) {
        displayName = djangoProfile.display_name || djangoProfile.username || displayName;
        if (djangoProfile.avatar_url) {
          avatarUrl = djangoProfile.avatar_url;
        }
      }
    } catch (e) {
      console.warn("Could not sync profile metadata from Django API:", e);
      // Use metadata from Supabase user info if Django fails
      if (user.user_metadata) {
        displayName = user.user_metadata.full_name || user.user_metadata.name || displayName;
        avatarUrl = user.user_metadata.avatar_url || avatarUrl;
      }
    }

    menu.innerHTML = `
      <li><a class="nav-link ${isIndexActive ? 'active' : ''}" href="index.html">Home</a></li>
      <li><a class="nav-link ${isArticlesActive ? 'active' : ''}" href="articles.html">Articles</a></li>
      <li>
        <a class="nav-link ${isProfileActive ? 'active' : ''} user-profile-badge" href="profile.html">
          <img class="user-avatar" src="${escapeHtml(avatarUrl)}" alt="${escapeHtml(displayName)}'s avatar" />
          <span>${escapeHtml(displayName)}</span>
        </a>
      </li>
      <li><a class="nav-link" href="#" id="logout-link">Logout</a></li>
    `;

    // Hook up logout listener
    const logoutBtn = menu.querySelector('#logout-link');
    if (logoutBtn) {
      logoutBtn.addEventListener('click', async (e) => {
        e.preventDefault();
        try {
          await logoutUser();
        } catch (error) {
          console.error("Logout failed:", error);
        }
      });
    }
  }
}

function escapeHtml(value = "") {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
