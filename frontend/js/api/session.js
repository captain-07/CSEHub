import { apiFetch } from '../api.js';

function toQuery(params = {}) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      query.set(key, value);
    }
  });
  const serialized = query.toString();
  return serialized ? `?${serialized}` : '';
}

/**
 * Announces the current Supabase session and refreshes its heartbeat.
 *
 * The backend reads `session_id` from the verified token, so no identifier is
 * sent from here. The call is idempotent: the first one records the login and
 * every later one only moves `last_seen_at`.
 */
export function pingSession() {
  return apiFetch('/auth/session/', { method: 'POST', body: {} });
}

/**
 * Closes the current session.
 *
 * Must run *before* `supabase.auth.signOut()`: once the local session is gone
 * there is no bearer token, and the endpoint would answer 401. A tab that is
 * simply closed cannot call this at all — the active-window cutoff covers it.
 */
export function endSession() {
  // A sign-out must not wait on a sleeping backend before it can clear the
  // local session, so this is bounded much tighter than an ordinary request.
  // If it misses, the active-window cutoff still closes the row.
  return apiFetch('/auth/session/logout/', { method: 'POST', body: {}, timeout: 5000 });
}

/** Admin login log. `filters` accepts `status` (`active`/`ended`) and `search`. */
export function getSessions(filters, options) {
  return apiFetch(`/auth/sessions/${toQuery(filters)}`, options);
}

/** Counts for the login log's stat cards. */
export function getSessionSummary(options) {
  return apiFetch('/auth/sessions/summary/', options);
}
