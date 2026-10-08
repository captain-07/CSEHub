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
 * Reusable utility for sending requests to the Django REST Framework backend.
 * Automatically injects the Supabase access token (JWT) as a Bearer token if available.
 * Handles network failures, parses JSON responses, and implements consistent error routing.
 */
export async function apiFetch(endpoint, options = {}) {
  const url = buildApiUrl(endpoint);
  
  // Set up default headers
  const headers = new Headers(options.headers || {});
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
  if (options.body && typeof options.body === 'object' && !(options.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json');
    options.body = JSON.stringify(options.body);
  }

  const fetchOptions = {
    ...options,
    headers
  };

  let response;
  try {
    response = await fetch(url, fetchOptions);
  } catch (error) {
    if (error.name === 'AbortError') throw error;
    throw new ApiError("Network error. Unable to connect to CSEHub backend. Please check your connection.", 0);
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
