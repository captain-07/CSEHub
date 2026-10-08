import { apiFetch, ApiError } from './api.js';
import { initNavbar } from './navbar.js';
import { initAuth, getAuthState, subscribeAuth, updateAuthStateProfile, refreshProfile } from './auth-state.js';
import { logoutUser } from './auth.js';
import { escapeHtml, safeUrl } from './renderer.js';

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
      const message = profileError instanceof ApiError ? profileError.message : (profileError.message || 'Something went wrong while fetching your profile details.');
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
      // Render profile card if it hasn't been rendered yet or if user ID changed
      const profileKey = `${profile.id}-${profile.username}-${profile.email}`;
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
  const badgeMarkup = `<div class="profile-avatar-large profile-avatar-initials" id="avatar-preview" aria-hidden="true">${escapeHtml(initials)}</div>`;
  const avatarMarkup = avatarSrc
    ? `<img class="profile-avatar-large" id="avatar-preview" src="${escapeHtml(avatarSrc)}" alt="" referrerpolicy="no-referrer" />`
    : badgeMarkup;

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
            <input class="input" type="text" id="display_name" name="display_name" value="${escapeHtml(profile.display_name || '')}" required />
          </div>
        </div>

        <div class="form-group">
          <label class="form-label" for="avatar_url">Avatar URL</label>
          <input class="input" type="url" id="avatar_url" name="avatar_url" value="${escapeHtml(profile.avatar_url || '')}" placeholder="https://example.com/avatar.jpg" />
          <span class="field-hint">Leave blank to use your initials.</span>
        </div>

        <div class="profile-actions">
          <button class="button button-primary" type="submit" id="save-btn">Save Changes</button>
        </div>
      </form>

      <div class="profile-footer">
        <dl class="account-details">
          <div>
            <dt>Signed in as</dt>
            <dd>${escapeHtml(profile.email)}</dd>
          </div>
          <div>
            <dt>Publishing rights</dt>
            <dd>${profile.is_admin ? 'Editor — can publish articles' : 'Reader — read-only access'}</dd>
          </div>
        </dl>
        <button class="button button-secondary" type="button" id="profile-logout">Sign out</button>
      </div>
    </div>
  `;

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

  const avatarInput = container.querySelector("#avatar_url");

  avatarInput.addEventListener("input", () => {
    const preview = container.querySelector("#avatar-preview");
    if (!preview) return;

    const url = safeUrl(avatarInput.value.trim());
    if (url) {
      if (preview.tagName === 'IMG') {
        preview.src = url;
        return;
      }
      const img = document.createElement('img');
      img.className = 'profile-avatar-large';
      img.id = 'avatar-preview';
      img.alt = '';
      img.referrerPolicy = 'no-referrer';
      img.src = url;
      preview.replaceWith(img);
      return;
    }

    if (preview.tagName !== 'IMG') return;
    const template = document.createElement('template');
    template.innerHTML = badgeMarkup;
    preview.replaceWith(template.content.firstElementChild);
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
  saveBtn.textContent = "Saving changes...";

  const payload = {
    username: form.elements.username.value.trim(),
    display_name: form.elements.display_name.value.trim(),
    avatar_url: form.elements.avatar_url.value.trim()
  };

  try {
    const updatedProfile = await apiFetch("/me/", {
      method: "PATCH",
      body: payload
    });

    // Update single source of auth state truth
    updateAuthStateProfile(updatedProfile);

    // Success response
    alertBox.innerHTML = `
      <div class="alert alert-success">
        Profile updated successfully!
      </div>
    `;

    // Update header name display in profile card
    const headerName = document.querySelector('#header-name');
    if (headerName) {
      headerName.textContent = updatedProfile.display_name || updatedProfile.username || 'CSEHub Student';
    }

  } catch (error) {
    console.error("Profile save failed:", error);
    const message = error instanceof ApiError ? error.message : "Failed to update profile settings.";
    alertBox.innerHTML = `
      <div class="alert alert-error">
        <strong>Error updating profile:</strong> ${escapeHtml(message)}
      </div>
    `;
  } finally {
    saveBtn.disabled = false;
    saveBtn.textContent = "Save Changes";
  }
}

document.addEventListener("DOMContentLoaded", () => {
  initNavbar();
  checkAuthAndLoadProfile();
});
