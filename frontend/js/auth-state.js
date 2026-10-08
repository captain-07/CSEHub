import { getSupabase } from './supabase.js';
import { apiFetch, ApiError } from './api.js';
import { consumePostLoginRedirect } from './auth.js';

/**
 * Single source of truth for authentication state.
 *
 * status:
 *   'loading'      -> still resolving the Supabase session
 *   'anonymous'    -> no Supabase session
 *   'authenticated'-> Supabase session present
 *
 * `profile` is the authoritative backend record (`GET /api/me/`); `isAdmin` is
 * read from it and never inferred from local storage or the email address.
 */

let state = {
  ready: false,
  user: null,
  profile: null,
  profileError: null,
  status: 'loading',
};

let initialized = false;
let initialisedPromise = null;
const listeners = new Set();

function emit() {
  listeners.forEach((listener) => listener(state));
}

async function hydrate(session) {
  const user = session?.user || null;

  // Keep the previously resolved profile visible during a background refresh
  // (e.g. Supabase rotating the access token) so the UI never flashes signed out.
  state = {
    ready: state.ready,
    user,
    profile: user ? state.profile : null,
    profileError: null,
    status: user ? 'authenticated' : 'anonymous',
  };
  emit();

  if (!user) {
    state = { ...state, ready: true };
    emit();
    return state;
  }

  try {
    const profile = await apiFetch('/me/', { redirectOnUnauthorized: true });
    // A 2xx response that is not a profile object means the request succeeded but
    // told us nothing useful. Recording that as an error is what keeps a signed-in
    // visitor from being mistaken for an anonymous one.
    if (!profile || typeof profile !== 'object') {
      throw new ApiError('The server did not return a profile for this account.', 0);
    }
    state.profile = profile;
    state.profileError = null;
  } catch (error) {
    // The Supabase session exists but the backend rejected or could not serve the
    // profile. Surface it rather than pretending the user is anonymous.
    state.profileError = error;
    console.warn('Profile sync failed', error);
  }

  state.ready = true;
  emit();

  applyPendingRedirect();
  return state;
}

function applyPendingRedirect() {
  const target = consumePostLoginRedirect();
  if (!target) return;
  const current = `${window.location.pathname}${window.location.search}`;
  if (target === current) return;
  window.location.replace(target);
}

export async function initAuth() {
  if (initialized) return initialisedPromise;

  const supabase = getSupabase();
  if (!supabase) {
    // Without Supabase configured there is no session to wait for.
    state = { ready: true, user: null, profile: null, profileError: null, status: 'anonymous' };
    emit();
    return state;
  }

  initialisedPromise = (async () => {
    const { data, error } = await supabase.auth.getSession();
    if (error) console.warn('Unable to read Supabase session', error);
    await hydrate(data.session);

    supabase.auth.onAuthStateChange((event, session) => {
      if (event === 'SIGNED_OUT') {
        state = { ready: true, user: null, profile: null, profileError: null, status: 'anonymous' };
        emit();
        return;
      }
      hydrate(session);
    });

    initialized = true;
    return state;
  })();

  return initialisedPromise;
}

export const getAuthState = () => state;
export const isAdmin = () => Boolean(state.profile?.is_admin);
export const isAuthenticated = () => state.status === 'authenticated';

export function updateAuthStateProfile(newProfile) {
  state = {
    ...state,
    profile: newProfile,
    profileError: null,
  };
  emit();
}

export async function refreshProfile() {
  if (!state.user) return null;
  try {
    const profile = await apiFetch('/me/', { redirectOnUnauthorized: true });
    updateAuthStateProfile(profile);
    return profile;
  } catch (error) {
    state.profileError = error;
    emit();
    throw error;
  }
}

export function subscribeAuth(listener) {
  listeners.add(listener);
  listener(state);
  return () => listeners.delete(listener);
}