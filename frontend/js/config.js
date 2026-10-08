// Public runtime configuration for the CSEHub static client.
//
// The Supabase *publishable* key (sb_publishable_...) is public by design — it is
// meant to ship in browser code and is protected by Row Level Security.  The
// service-role key and the JWT secret must NEVER appear here.
//
// Defaults target the deployed Render backend.  Override any value by defining
// the matching global before this module loads (useful for local development):
//   window.CSEHUB_API_BASE_URL = "http://127.0.0.1:8000";

const DEPLOYED_API_BASE_URL = "https://csehub-ezdl.onrender.com";
const DEPLOYED_SUPABASE_URL = "https://jaihvxmogxxirkynllua.supabase.co";
const DEPLOYED_SUPABASE_ANON_KEY = "sb_publishable_4tZpmv-fCvK8eLwZfcDKDQ_e9TtqSzv";

// Local development opt-in: when the page is served from a localhost port and a
// global override is absent, talk to the local Django dev server instead.
const isLocalhost = /^(localhost|127\.0\.0\.1|\[::1\])$/.test(window.location.hostname);

export const CONFIG = {
  API_BASE_URL:
    window.CSEHUB_API_BASE_URL ||
    (isLocalhost ? "http://127.0.0.1:8000" : DEPLOYED_API_BASE_URL),
  SUPABASE_URL: window.CSEHUB_SUPABASE_URL || DEPLOYED_SUPABASE_URL,
  SUPABASE_ANON_KEY:
    window.CSEHUB_SUPABASE_ANON_KEY || DEPLOYED_SUPABASE_ANON_KEY,
};