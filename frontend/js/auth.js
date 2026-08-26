import { getSupabase } from './supabase.js';

/**
 * Signs in a user using email and password.
 */
export async function loginWithEmail(email, password) {
  const supabase = getSupabase();
  if (!supabase) throw new Error("Supabase is not initialized.");
  
  const { data, error } = await supabase.auth.signInWithPassword({
    email,
    password,
  });

  if (error) throw error;
  return data;
}

/**
 * Signs up a user using email and password.
 */
export async function signupWithEmail(email, password) {
  const supabase = getSupabase();
  if (!supabase) throw new Error("Supabase is not initialized.");

  const { data, error } = await supabase.auth.signUp({
    email,
    password,
  });

  if (error) throw error;
  return data;
}

/**
 * Initiates Google OAuth Login.
 */
export async function loginWithGoogle() {
  const supabase = getSupabase();
  if (!supabase) throw new Error("Supabase is not initialized.");

  // Dynamically calculate redirect URL to match the current subdirectory/path context
  const currentPath = window.location.pathname;
  const lastSlashIndex = currentPath.lastIndexOf('/');
  const baseDir = lastSlashIndex !== -1 ? currentPath.substring(0, lastSlashIndex) : "";
  const redirectToUrl = window.location.origin + baseDir + '/index.html';

  const { error } = await supabase.auth.signInWithOAuth({
    provider: 'google',
    options: {
      redirectTo: redirectToUrl,
    }
  });

  if (error) throw error;
}

/**
 * Signs out the current user.
 */
export async function logoutUser() {
  const supabase = getSupabase();
  if (!supabase) return;
  const { error } = await supabase.auth.signOut();
  if (error) throw error;
  
  // Clear any local storage/session storage cache if needed and reload
  window.location.href = 'index.html';
}

/**
 * Registers a callback for authentication state changes (login, logout, token refresh, etc.).
 */
export function onAuthChange(callback) {
  const supabase = getSupabase();
  if (!supabase) return () => {};
  
  const { data: { subscription } } = supabase.auth.onAuthStateChange((event, session) => {
    callback(event, session);
  });

  return () => {
    subscription.unsubscribe();
  };
}
