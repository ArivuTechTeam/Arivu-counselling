import {
  createClient as createSupabaseClient,
  type SupabaseClient,
} from "@supabase/supabase-js";

import { PUBLIC_ENV } from "@/lib/public-env";

/**
 * Creates the Supabase client used by browser-only authentication and data
 * access. The public anon key remains constrained by Row Level Security.
 *
 * This app does not read Supabase sessions during server rendering: login,
 * OAuth code exchange, profile lookup, and API token forwarding all happen in
 * the browser. Cookie-backed SSR auth would therefore add no capability here.
 *
 * Auth is intentionally persisted in `sessionStorage` in every environment.
 * Unlike cookies/localStorage, sessionStorage is isolated per browser tab, so
 * signing in as a student in one tab cannot replace a teacher, institution
 * admin, or super-admin session in another. Refreshing a tab still restores
 * that tab's session normally.
 *
 * Email/password login needs no redirect. Google OAuth redirects back into
 * the same tab, where `/auth/callback` exchanges the `?code=` parameter and
 * reads its PKCE verifier from that tab's sessionStorage.
 *
 * `detectSessionInUrl` stays disabled because `/auth/callback` deliberately
 * performs the code exchange. Automatic detection would race that exchange
 * and could consume the one-time PKCE verifier first.
 */

// A browser tab has its own JS module scope and sessionStorage. Caching avoids
// duplicate GoTrue clients and auto-refresh timers within the same tab.
let cachedBrowserClient: SupabaseClient | undefined;

export function createClient() {
  if (!cachedBrowserClient) {
    cachedBrowserClient = createSupabaseClient(
      PUBLIC_ENV.supabaseUrl,
      PUBLIC_ENV.supabaseAnonKey,
      {
        auth: {
          storage: window.sessionStorage,
          persistSession: true,
          autoRefreshToken: true,
          flowType: "pkce",
          detectSessionInUrl: false,
        },
      },
    );
  }
  return cachedBrowserClient;
}
