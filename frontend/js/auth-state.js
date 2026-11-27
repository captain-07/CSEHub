import { getSupabase } from './supabase.js';
import { apiFetch, ApiError } from './api.js';
import { consumePostLoginRedirect } from './auth.js';
import { pingSession } from './api/session.js';

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

let initialisedPromise = null;
const listeners = new Set();

function emit() {
  listeners.forEach((listener) => listener(state));
}

/* ------------------------------------------------------- login session log */

/**
 * The admin panel's login log is only as truthful as this heartbeat.
 *
 * A session row is created on the first ping after sign-in and refreshed while
 * the page is open. Ten minutes keeps a 30-minute active window alive through
 * two missed beats, which is what a throttled background tab can cost; the
 * backend treats anything older than that window as ended because a closed tab
 * has no way to say goodbye.
 */
const HEARTBEAT_MS = 10 * 60 * 1000;
const PING_THROTTLE_MS = 60 * 1000;
let heartbeatTimer = null;
let lastPingAt = 0;

async function pingLoginSession() {
  if (!state.user) return;
  const now = Date.now();
  // Every page load pings once; rapid auth events (a token refresh, a second
  // profile sync) must not turn into a request each.
  if (now - lastPingAt < PING_THROTTLE_MS) return;
  lastPingAt = now;

  try {
    await pingSession();
  } catch (error) {
    // Tracking is a side feature. A failed ping must never make a signed-in
    // reader look signed out or block the page that is loading.
    console.warn('Login session tracking failed', error);
  }
}

function startHeartbeat() {
  if (heartbeatTimer) return;
  heartbeatTimer = setInterval(pingLoginSession, HEARTBEAT_MS);
}

function stopHeartbeat() {
  if (heartbeatTimer) clearInterval(heartbeatTimer);
  heartbeatTimer = null;
}

if (typeof document !== 'undefined') {
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') pingLoginSession();
  });
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

  // Fire-and-forget: the page does not wait on a log write.
  pingLoginSession();

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
  // Guard on the *promise*, not on a resolved flag: a second caller arriving
  // while the first session lookup is still in flight would otherwise start a
  // second `onAuthStateChange` subscription and hydrate the profile twice. The
  // article page now awaits this to decide whether its paywall offers a
  // "Sign in" link or a "Buy" button, so that race is reachable.
  if (initialisedPromise) return initialisedPromise;

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
    startHeartbeat();

    supabase.auth.onAuthStateChange((event, session) => {
      if (event === 'SIGNED_OUT') {
        stopHeartbeat();
        lastPingAt = 0;
        state = { ready: true, user: null, profile: null, profileError: null, status: 'anonymous' };
        emit();
        return;
      }
      // A fresh sign-in must be recorded even if this tab pinged a moment ago
      // for a different session, and a sign-out followed by a sign-in in the
      // same tab has to restart the heartbeat that SIGNED_OUT stopped.
      if (event === 'SIGNED_IN') {
        lastPingAt = 0;
        startHeartbeat();
      }
      hydrate(session);
    });

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