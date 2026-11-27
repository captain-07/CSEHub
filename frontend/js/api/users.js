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

/** Admin account list. `filters` accepts `status` (`active`/`banned`) and `search`. */
export function getUsers(filters, options) {
  return apiFetch(`/auth/users/${toQuery(filters)}`, options);
}

/** Counts for the account list's stat cards. */
export function getUserSummary(options) {
  return apiFetch('/auth/users/summary/', options);
}

/**
 * Ban an account. The reason is optional and is shown in the account list.
 *
 * The server closes the reader's open login sessions at the same time, so the
 * ban takes effect on their next request rather than when their token expires.
 */
export function banUser(id, reason = '') {
  return apiFetch(`/auth/users/${id}/ban/`, {
    method: 'POST',
    body: { reason },
  });
}

/** Restore an account's access. Sessions ended by the ban stay ended. */
export function unbanUser(id) {
  return apiFetch(`/auth/users/${id}/unban/`, { method: 'POST', body: {} });
}
