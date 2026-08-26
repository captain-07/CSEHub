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
  const url = `${CONFIG.API_BASE_URL.replace(/\/$/, '')}${endpoint}`;
  
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
    // 401 Unauthorized handling: Redirect to login.html if authentication is expired
    if (response.status === 401) {
      console.warn("Django backend returned 401 Unauthorized. Redirecting to login...");
      // Check if not already on login page to prevent infinite redirects
      if (!window.location.pathname.endsWith('login.html')) {
        window.location.href = 'login.html?redirect=' + encodeURIComponent(window.location.pathname + window.location.search);
        return;
      }
    }

    const errorMsg = data?.detail || data?.message || `API request failed with status ${response.status}`;
    throw new ApiError(errorMsg, response.status, data);
  }

  return data;
}
