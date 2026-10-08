import { getSupabase } from './supabase.js';

// Only same-origin, first-party pages may be used as a post-login destination.
// Anything absolute, protocol-relative ("//evil.com"), or otherwise unexpected is
// rejected so the parameter can never be used as an open redirect.
const ALLOWED_REDIRECT_PAGES = [
  'index.html',
  'articles.html',
  'article.html',
  'profile.html',
  'admin.html',
  'login.html',
];

const PENDING_REDIRECT_KEY = 'csehub:post-login-redirect';

/**
 * Normalises a post-login destination to a safe relative URL, or returns null.
 */
export function sanitizeRedirect(candidate) {
  if (!candidate || typeof candidate !== 'string') return null;

  // Decode defensively; a doubly-encoded value must not slip through.
  let value = candidate;
  for (let i = 0; i < 2; i += 1) {
    try {
      const decoded = decodeURIComponent(value);
      if (decoded === value) break;
      value = decoded;
    } catch {
      return null;
    }
  }

  if (value.startsWith('//') || value.includes('\\') || /^[a-z]+:/i.test(value)) return null;
  if (/[\r\n]/.test(value)) return null;

  const pathWithQuery = value.startsWith('/') ? value : '/' + value;
  const [path] = pathWithQuery.split('#');
  const page = path.split('?')[0].replace(/^\//, '');
  if (!ALLOWED_REDIRECT_PAGES.includes(page)) return null;

  return pathWithQuery;
}

export function rememberPostLoginRedirect(candidate) {
  const safe = sanitizeRedirect(candidate);
  if (safe) {
    try {
      sessionStorage.setItem(PENDING_REDIRECT_KEY, safe);
    } catch {
      /* storage unavailable (private mode) — navigation simply falls back to home */
    }
  }
  return safe;
}

export function consumePostLoginRedirect() {
  try {
    const stored = sessionStorage.getItem(PENDING_REDIRECT_KEY);
    sessionStorage.removeItem(PENDING_REDIRECT_KEY);
    return sanitizeRedirect(stored);
  } catch {
    return null;
  }
}

/**
 * Starts the Google OAuth flow.
 *
 * Supabase only returns the browser to a URL present in its redirect allow-list,
 * so the OAuth callback always lands on the home page and the originally
 * requested destination is carried across the round trip in sessionStorage.
 */
export async function loginWithGoogle({ redirectTo } = {}) {
  const supabase = getSupabase();
  if (!supabase) throw new Error("Supabase is not initialized.");

  rememberPostLoginRedirect(redirectTo);

  const callbackUrl = `${window.location.origin}${window.location.pathname.replace(/[^/]*$/, '')}index.html`;

  const { error } = await supabase.auth.signInWithOAuth({
    provider: 'google',
    options: {
      redirectTo: callbackUrl,
      scopes: 'openid email profile',
    },
  });

  if (error) throw error;
}

export async function logoutUser() {
  const supabase = getSupabase();
  if (!supabase) return;
  const { error } = await supabase.auth.signOut();
  if (error) throw error;

  try {
    sessionStorage.removeItem(PENDING_REDIRECT_KEY);
  } catch {
    /* ignore */
  }

  window.location.href = 'index.html';
}