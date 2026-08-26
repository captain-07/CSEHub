import { getCurrentUser } from './supabase.js';
import { apiFetch, ApiError } from './api.js';
import { initNavbar } from './navbar.js';

const escapeHtml = (value = "") => String(value)
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;")
  .replaceAll("'", "&#039;");

async function checkAuthAndLoadProfile() {
  const profileContainer = document.querySelector("#profile-container");
  
  try {
    if (profileContainer) {
      profileContainer.innerHTML = `<div class="loading"><span class="loading-spinner"></span>Verifying session & loading profile…</div>`;
    }

    const user = await getCurrentUser();
    
    if (!user) {
      // Not logged in: redirect to login page
      console.warn("Unauthenticated user accessing profile page. Redirecting to login.html...");
      window.location.href = `login.html?redirect=profile.html`;
      return;
    }

    // Load actual user profile data from Django API
    const profile = await apiFetch("/me/");
    renderProfileCard(profile);
  } catch (error) {
    console.error("Error loading user profile:", error);
    if (profileContainer) {
      const message = error instanceof ApiError ? error.message : "Something went wrong while fetching your profile details.";
      profileContainer.innerHTML = `
        <div class="alert alert-error">
          <strong>Failed to load profile:</strong> ${escapeHtml(message)}
          <br><br>
          <button class="button button-secondary" onclick="window.location.reload()">Retry</button>
        </div>
      `;
    }
  }
}

function renderProfileCard(profile) {
  const container = document.querySelector("#profile-container");
  if (!container) return;

  const defaultAvatar = "https://www.gravatar.com/avatar/00000000000000000000000000000000?d=mp&f=y";
  const avatarSrc = profile.avatar_url || defaultAvatar;

  container.innerHTML = `
    <div class="profile-card">
      <div class="profile-header">
        <img class="profile-avatar-large" id="avatar-preview" src="${escapeHtml(avatarSrc)}" alt="Profile avatar" />
        <div class="profile-title">
          <h1 id="header-name">${escapeHtml(profile.display_name || profile.username || "CSEHub Student")}</h1>
          <p>${escapeHtml(profile.email)}</p>
          ${profile.is_staff ? `<span class="badge-staff">Staff / Admin</span>` : ''}
        </div>
      </div>

      <div id="alert-box"></div>

      <form id="profile-form">
        <div class="form-row">
          <div class="form-group">
            <label class="form-label" for="username">Username</label>
            <input class="form-control" type="text" id="username" name="username" value="${escapeHtml(profile.username || '')}" required />
          </div>
          <div class="form-group">
            <label class="form-label" for="display_name">Display Name</label>
            <input class="form-control" type="text" id="display_name" name="display_name" value="${escapeHtml(profile.display_name || '')}" required />
          </div>
        </div>

        <div class="form-group">
          <label class="form-label" for="avatar_url">Avatar URL</label>
          <input class="form-control" type="url" id="avatar_url" name="avatar_url" value="${escapeHtml(profile.avatar_url || '')}" placeholder="https://example.com/avatar.jpg" />
        </div>

        <div class="profile-actions">
          <button class="button button-primary" type="submit" id="save-btn">Save Changes</button>
        </div>
      </form>
    </div>
  `;

  // Real-time avatar preview sync
  const avatarInput = container.querySelector("#avatar_url");
  const avatarPreview = container.querySelector("#avatar-preview");
  avatarInput.addEventListener("input", () => {
    const val = avatarInput.value.trim();
    avatarPreview.src = val || defaultAvatar;
  });

  // Setup form submission handler
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

    // Success response
    alertBox.innerHTML = `
      <div class="alert alert-success">
        Profile updated successfully!
      </div>
    `;

    // Update displayed names
    document.querySelector("#header-name").textContent = escapeHtml(updatedProfile.display_name || updatedProfile.username || "CSEHub Student");
    
    // Refresh navbar to display updated avatar and name immediately
    initNavbar();

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
