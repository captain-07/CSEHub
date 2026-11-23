import { apiFetch, friendlyError } from './api.js';
import { initNavbar } from './navbar.js';
import { initAuth, getAuthState, subscribeAuth, updateAuthStateProfile, refreshProfile } from './auth-state.js';
import { logoutUser } from './auth.js';
import { escapeHtml, safeUrl, formatDate } from './renderer.js';
import { showToast } from './toast.js';

let renderedProfileId = null;

function initialsOf(name = '') {
  const parts = String(name).trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return '?';
  return (parts.length === 1 ? parts[0].slice(0, 2) : parts[0][0] + parts[1][0]).toUpperCase();
}

function checkAuthAndLoadProfile() {
  const profileContainer = document.querySelector("#profile-container");
  if (!profileContainer) return;

  subscribeAuth((state) => {
    const { ready, user, profile, profileError } = state;

    if (!ready) {
      profileContainer.innerHTML = `<div class="loading"><span class="loading-spinner"></span>Verifying session & loading profile…</div>`;
      return;
    }

    if (!user) {
      // Preserve the visitor's place: back to the profile once signed in.
      window.location.replace('login.html?redirect=' + encodeURIComponent('profile.html'));
      return;
    }

    if (profileError && !profile) {
      const message = friendlyError(profileError);
      profileContainer.innerHTML = `
        <div class="alert alert-error" role="alert">
          <strong>Failed to load profile:</strong> ${escapeHtml(message)}
          <p><button class="button button-secondary" type="button" id="retry-profile-btn">Retry</button></p>
        </div>`;
      profileContainer.querySelector('#retry-profile-btn')?.addEventListener('click', async () => {
        profileContainer.innerHTML = `<div class="loading"><span class="loading-spinner"></span>Retrying…</div>`;
        try {
          await refreshProfile();
        } catch (err) {
          console.error("Retry profile failed:", err);
        }
      });
      return;
    }

    if (profile) {
      // Render profile card if it hasn't been rendered yet or if user ID / name changed
      const profileKey = `${profile.id}-${profile.username}-${profile.display_name || ''}-${profile.email}`;
      if (renderedProfileId !== profileKey) {
        renderedProfileId = profileKey;
        renderProfileCard(profile);
      }
    }
  });

  initAuth();
}

function renderProfileCard(profile) {
  const container = document.querySelector("#profile-container");
  if (!container) return;

  const avatarSrc = safeUrl(profile.avatar_url);
  const displayName = profile.display_name || profile.username || 'CSEHub Student';
  const initials = initialsOf(displayName);
  const initialsMarkup = `<div class="profile-avatar-large profile-avatar-initials" aria-hidden="true">${escapeHtml(initials)}</div>`;
  const avatarMarkup = avatarSrc
    ? `<img class="profile-avatar-large" src="${escapeHtml(avatarSrc)}" alt="" referrerpolicy="no-referrer" />`
    : initialsMarkup;

  container.innerHTML = `
    <div class="profile-card">
      <div class="profile-header">
        ${avatarMarkup}
        <div class="profile-title">
          <h1 id="header-name">${escapeHtml(profile.display_name || profile.username || "CSEHub Student")}</h1>
          <p>${escapeHtml(profile.email)}</p>
          <p class="profile-joined">${profile.is_admin ? '<span class="badge-staff">Editor</span>' : '<span class="badge-reader">Reader</span>'}</p>
        </div>
      </div>

      <div id="alert-box"></div>

      <form id="profile-form">
        <div class="form-row">
          <div class="form-group">
            <label class="form-label" for="username">Username</label>
            <input class="input" type="text" id="username" name="username" value="${escapeHtml(profile.username || '')}" required />
          </div>
          <div class="form-group">
            <label class="form-label" for="display_name">Display Name</label>
            <input class="input" type="text" id="display_name" name="display_name" value="${escapeHtml(profile.display_name || '')}" />
          </div>
        </div>

        <div class="profile-actions">
          <button class="button button-primary" type="submit" id="save-btn">Save Changes</button>
        </div>
      </form>

      <div class="profile-footer">
        <dl class="account-details">
          <div>
            <dt>Publishing rights</dt>
            <dd>${profile.is_admin ? 'Editor — can publish articles' : 'Reader — read-only access'}</dd>
          </div>
        </dl>
        <button class="button button-secondary" type="button" id="profile-logout">Sign out</button>
      </div>
    </div>

    <div class="profile-library-section" id="profile-library-section">
      <div class="loading"><span class="loading-spinner"></span>Loading your purchased lessons…</div>
    </div>
  `;

  loadPurchasedArticles(container.querySelector('#profile-library-section'));

  container.querySelector('#profile-logout')?.addEventListener('click', async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      await logoutUser();
    } catch (error) {
      console.error('Sign out failed', error);
      button.disabled = false;
    }
  });

  const form = container.querySelector("#profile-form");
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    await saveProfile(form);
  });
}

async function saveProfile(form) {
  const saveBtn = form.querySelector("#save-btn");
  const alertBox = document.querySelector("#alert-box");
  if (!alertBox || !saveBtn) return;

  alertBox.innerHTML = ""; // Clear existing messages
  saveBtn.disabled = true;
  saveBtn.setAttribute('aria-busy', 'true');
  saveBtn.textContent = "Saving changes...";

  const payload = {
    username: form.elements.username.value.trim(),
    display_name: form.elements.display_name.value.trim()
  };

  try {
    const updatedProfile = await apiFetch("/me/", {
      method: "PATCH",
      body: payload
    });

    // Update single source of auth state truth
    updateAuthStateProfile(updatedProfile);

    // Confirmation lives in a toast rather than the inline alert box: the user
    // is reading the form, and a box above it that never dismisses just gets
    // in the way after the first save.
    alertBox.innerHTML = '';
    showToast('Profile updated successfully.', { type: 'success' });

    // Update header name display in profile card
    const headerName = document.querySelector('#header-name');
    if (headerName) {
      headerName.textContent = updatedProfile.display_name || updatedProfile.username || 'CSEHub Student';
    }

  } catch (error) {
    console.error("Profile save failed:", error);
    const message = friendlyError(error);
    // Errors stay inline in the alert box: they often need reading more than
    // once, and a toast that disappears invites a silent save they think worked.
    alertBox.innerHTML = `
      <div class="alert alert-error">
        <strong>Error updating profile:</strong> ${escapeHtml(message)}
      </div>
    `;
  } finally {
    saveBtn.disabled = false;
    saveBtn.removeAttribute('aria-busy');
    saveBtn.textContent = "Save Changes";
  }
}

async function loadPurchasedArticles(container) {
  if (!container) return;
  try {
    const purchases = await apiFetch('/payments/my-purchases/');
    if (!purchases || !purchases.length) {
      container.innerHTML = `
        <div class="purchased-empty">
          <p class="purchased-empty-title">My Purchased Lessons</p>
          <p class="purchased-empty-copy">You haven't purchased any lessons yet.</p>
          <a class="button button-secondary" href="articles.html">Browse Articles</a>
        </div>`;
      return;
    }

    container.innerHTML = `
      <section class="purchased-section">
        <div class="purchased-section-header">
          <h2 class="purchased-section-title">My Purchased Lessons</h2>
          <span class="purchased-count">${purchases.length} ${purchases.length === 1 ? 'lesson' : 'lessons'}</span>
        </div>
        <div class="purchased-grid">
          ${purchases.map((item) => `
            <article class="purchased-card">
              <div class="purchased-card-body">
                <span class="purchased-card-badge">${escapeHtml(item.category?.name || 'Lesson')}</span>
                <h3 class="purchased-card-title">
                  <a href="article.html?slug=${encodeURIComponent(item.slug || item.id)}">${escapeHtml(item.title)}</a>
                </h3>
                ${item.excerpt ? `<p class="purchased-card-excerpt">${escapeHtml(item.excerpt)}</p>` : ''}
                <div class="purchased-card-footer">
                  <span class="purchased-card-date">Purchased ${escapeHtml(formatDate(item.purchased_at))}</span>
                  <div class="purchased-card-actions">
                    <a class="button button-secondary button-sm" href="article.html?slug=${encodeURIComponent(item.slug || item.id)}">Read</a>
                    <button class="button button-secondary button-sm" type="button" data-download-slug="${escapeHtml(item.slug || item.id)}">Download PDF</button>
                  </div>
                </div>
              </div>
            </article>
          `).join('')}
        </div>
      </section>`;

    container.querySelectorAll('[data-download-slug]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const slug = btn.dataset.downloadSlug;
        const originalText = btn.textContent;
        btn.disabled = true;
        btn.textContent = 'Preparing PDF…';
        try {
          const blob = await apiFetch(`/articles/${encodeURIComponent(slug)}/pdf/`, {
            responseType: 'blob',
            timeout: 60000,
          });
          const url = URL.createObjectURL(blob);
          const a = document.createElement('a');
          a.href = url;
          a.download = `${slug}.pdf`;
          a.hidden = true;
          document.body.appendChild(a);
          a.click();
          a.remove();
          setTimeout(() => URL.revokeObjectURL(url), 30000);
          showToast('PDF downloaded successfully.', { type: 'success' });
        } catch (err) {
          showToast(friendlyError(err), { type: 'error' });
        } finally {
          btn.disabled = false;
          btn.textContent = originalText;
        }
      });
    });
  } catch (error) {
    console.warn('Could not load purchases', error);
    container.innerHTML = '';
  }
}

document.addEventListener("DOMContentLoaded", () => {
  initNavbar();
  checkAuthAndLoadProfile();
});
