import { initNavbar } from './navbar.js';
import { initAuth, getAuthState, subscribeAuth } from './auth-state.js';
import { loginWithGoogle, sanitizeRedirect } from './auth.js';
import { escapeHtml } from './renderer.js';

const googleBtn = document.querySelector('#google-btn');
const alertBox = document.querySelector('#alert-box');

function showError(message) {
  alertBox.innerHTML = `<div class="alert alert-error" role="alert">${message}</div>`;
}

function showInfo(message) {
  alertBox.innerHTML = `<div class="alert" role="status">${escapeHtml(message)}</div>`;
}

function clearAlert() {
  alertBox.innerHTML = '';
}

/** Already signed in? Go where they were heading instead of showing the button. */
function redirectIfSignedIn() {
  const { user, ready } = getAuthState();
  if (!ready || !user) return false;

  // `sanitizeRedirect` is the single validation for a post-login destination.
  // A local regex was previously used here that accepted only a bare filename,
  // so `/article.html?slug=hash-tables` — the exact shape api.js and chat.js
  // produce — was rejected and the reader landed on the home page instead.
  //
  // The OAuth callback does not come back here: Supabase returns to index.html
  // and `auth-state.js` replays the pending destination from sessionStorage.
  const params = new URLSearchParams(window.location.search);
  const target = sanitizeRedirect(params.get('redirect'));
  window.location.replace(target || 'index.html');
  return true;
}

document.addEventListener('DOMContentLoaded', async () => {
  initNavbar();

  await initAuth();
  subscribeAuth(() => {
    if (!redirectIfSignedIn() && googleBtn) googleBtn.hidden = false;
  });
  if (!redirectIfSignedIn() && googleBtn) googleBtn.hidden = false;

  googleBtn?.addEventListener('click', async () => {
    clearAlert();

    // Google rejects a login attempt when the document is not in focus
    // (Supabase opens the popup/redirect itself).
    if (document.visibilityState !== 'visible') {
      showInfo('Returning to this tab to continue sign-in…');
    }

    // Capture innerHTML (not textContent) so the Google logo survives a retry.
    const originalMarkup = googleBtn.innerHTML;
    googleBtn.disabled = true;
    googleBtn.innerHTML = 'Redirecting to Google…';

    try {
      const params = new URLSearchParams(window.location.search);
      await loginWithGoogle({ redirectTo: params.get('redirect') });
    } catch (error) {
      console.error('Google sign-in failed', error);
      showError(`<strong>Google sign-in failed.</strong> ${escapeHtml(error.message || 'Please try again.')}`);
      googleBtn.disabled = false;
      googleBtn.innerHTML = originalMarkup;
    }
  });
});