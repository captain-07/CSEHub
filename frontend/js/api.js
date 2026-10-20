import { CONFIG } from './config.js';
import { getSessionToken } from './supabase.js';

export class ApiError extends Error {
  constructor(message, status, details) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.details = details;
  }
}

/**
 * How long a request may hang before it is abandoned.
 *
 * Nothing used to bound a request, so a stalled connection left every page
 * spinning forever. Twenty seconds is longer than any normal API call here and
 * short enough that the reader gets a retry before giving up. Image uploads
 * pass their own, larger limit.
 */
const DEFAULT_TIMEOUT_MS = 20_000;

/**
 * Reusable utility for sending requests to the Django REST Framework backend.
 * Automatically injects the Supabase access token (JWT) as a Bearer token if available.
 * Handles network failures, parses JSON responses, and implements consistent error routing.
 */
export async function apiFetch(endpoint, options = {}) {
  const url = buildApiUrl(endpoint);
  const { timeout = DEFAULT_TIMEOUT_MS, ...request } = options;

  // Set up default headers
  const headers = new Headers(request.headers || {});
  if (!headers.has('Accept')) {
    headers.set('Accept', 'application/json');
  }

  // Retrieve Supabase JWT token and append to request if found
  try {
    const token = await getSessionToken();
    if (token) {
      headers.set('Authorization', `Bearer ${token}`);
    }
  } catch (err) {
    console.error("Failed to retrieve Supabase session token:", err);
  }

  // Automatically add Content-Type for JSON payloads
  if (request.body && typeof request.body === 'object' && !(request.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json');
    request.body = JSON.stringify(request.body);
  }

  // The controller is local because no caller supplies a signal today; if one
  // ever does, the two have to be merged rather than the caller's dropped.
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);

  let response;
  try {
    response = await fetch(url, { ...request, headers, signal: controller.signal });
  } catch (error) {
    if (error.name === 'AbortError') {
      // Only this timeout can abort, so this is never a caller's cancellation.
      throw new ApiError(
        `The server did not respond in time (${Math.round(timeout / 1000)}s). Check your connection and try again.`,
        0
      );
    }
    throw new ApiError("Unable to reach the CSEHub API. Check your connection and try again.", 0);
  } finally {
    clearTimeout(timer);
  }

  const contentType = response.headers.get("content-type") || "";
  let data = null;
  if (contentType.includes("application/json")) {
    data = await response.json();
  }

  if (!response.ok) {
    // 401 means the Supabase token was missing or expired. Send the visitor to
    // the sign-in page carrying their current location so they land back here.
    //
    // Navigation is *not* a substitute for returning a result: callers below
    // would read `undefined` as an empty payload and conclude the account has
    // no profile, which is indistinguishable from a signed-out visitor. So the
    // redirect happens and the 401 is still thrown, carrying the server's own
    // reason ("credentials were not provided" vs "invalid or expired token").
    if (response.status === 401 && options.redirectOnUnauthorized) {
      const here = window.location.pathname + window.location.search;
      // Tolerates clean URLs, where the path is "/articles" rather than "/articles.html".
      if (!/(^|\/)login(\.html)?$/.test(window.location.pathname)) {
        console.warn('CSEHub API returned 401 — redirecting to sign in.');
        window.location.href = `login.html?redirect=${encodeURIComponent(here)}`;
      }
    }

    // Surface DRF field errors (e.g. {"title": ["This field is required."]})
    // instead of a generic status message.
    const fieldError = data && typeof data === 'object' && !Array.isArray(data)
      ? Object.entries(data).find(([key, value]) => key !== 'detail' && typeof value === 'object' && value !== null)
      : null;

    const errorMsg = fieldError
      ? `${Array.isArray(fieldError[1]) ? fieldError[1][0] : fieldError[1]}`
      : data?.detail || data?.message || `API request failed with status ${response.status}`;

    throw new ApiError(errorMsg, response.status, data);
  }

  return data;
}

function buildApiUrl(endpoint) {
  if (/^https?:\/\//i.test(endpoint)) return endpoint;
  if (!CONFIG.API_BASE_URL) {
    throw new ApiError("The frontend API URL has not been configured.", 0);
  }
  let base = CONFIG.API_BASE_URL.replace(/\/$/, '');
  if (base.endsWith('/api')) base = base.slice(0, -4);
  const path = endpoint.startsWith('/') ? endpoint : `/${endpoint}`;
  const apiBase = base.endsWith('/api') ? base : `${base}/api`;
  // DRF's pagination can return /api/... paths; never append /api twice.
  return path === '/api' || path.startsWith('/api/') ? `${base}${path}` : `${apiBase}${path}`;
}

/**
 * Turns any thrown value into one sentence a reader can act on.
 *
 * Shared rather than re-implemented per page: the same failure should read the
 * same whether it happened in the library, on the article page or in the admin
 * panel, and a raw "API request failed with status 500" leaks the transport
 * instead of saying what to do. DRF's field errors win when present, because
 * they name the actual problem ("This field is required.").
 */
export function friendlyError(error) {
  if (error instanceof ApiError) {
    if (error.status === 401) return error.message || 'Your session has expired. Sign in again to continue.';
    if (error.status === 403) return 'You are not authorised to perform that action.';
    if (error.status === 404) return 'That item could not be found. It may have been removed.';
    if (error.status === 0) return error.message || 'Cannot reach the CSEHub API. Check your connection.';
    if (error.status >= 500) return 'The CSEHub server had a problem. Please try again in a moment.';

    const details = error.details;
    if (details && typeof details === 'object') {
      const first = Object.entries(details).find(([key]) => key !== 'detail');
      if (first) return `${Array.isArray(first[1]) ? first[1][0] : first[1]}`;
    }
    return error.message;
  }
  return error?.message || 'Something went wrong.';
}
