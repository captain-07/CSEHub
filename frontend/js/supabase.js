import { CONFIG } from './config.js';

let supabaseClient = null;

/**
 * Initializes and returns the Supabase client instance.
 * Assumes the @supabase/supabase-js library is loaded via a CDN script tag in the DOM.
 */
export function getSupabase() {
  if (!supabaseClient) {
    if (typeof window.supabase === 'undefined') {
      console.warn("Supabase SDK is not loaded. Make sure script CDN is present in HTML.");
      return null;
    }
    // Only initialize if we have the configuration details
    if (!CONFIG.SUPABASE_URL || CONFIG.SUPABASE_URL.includes("YOUR_SUPABASE_URL") || CONFIG.SUPABASE_ANON_KEY.includes("YOUR_SUPABASE_ANON_KEY")) {
      console.warn("Supabase URL or ANON KEY is not configured in js/config.js. Authentication will not function.");
    }
    supabaseClient = window.supabase.createClient(CONFIG.SUPABASE_URL, CONFIG.SUPABASE_ANON_KEY);
  }
  return supabaseClient;
}

/**
 * Retrieve the current logged-in user if a session is present.
 */
export async function getCurrentUser() {
  const supabase = getSupabase();
  if (!supabase) return null;
  const { data: { user } } = await supabase.auth.getUser();
  return user;
}

/**
 * Retrieve the active session token to pass to the Django backend.
 */
export async function getSessionToken() {
  const supabase = getSupabase();
  if (!supabase) return null;
  const { data: { session } } = await supabase.auth.getSession();
  return session ? session.access_token : null;
}
