export const CONFIG = {
  // Configure these in a small, deployment-specific script before modules load.
  // The Supabase publishable key is public by design; server secrets never belong here.
  API_BASE_URL: window.CSEHUB_API_BASE_URL || "",
  SUPABASE_URL: window.CSEHUB_SUPABASE_URL || "",
  SUPABASE_ANON_KEY: window.CSEHUB_SUPABASE_ANON_KEY || ""
};
