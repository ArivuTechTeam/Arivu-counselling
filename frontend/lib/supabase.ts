import { createBrowserClient } from "@supabase/ssr";
import { createClient as createSupabaseClient } from "@supabase/supabase-js";

/**
 * Creates a Supabase client for use in the BROWSER (inside "use client"
 * components). It reads the public URL + anon key from NEXT_PUBLIC_ env vars.
 *
 * We export a factory function (rather than a single shared instance) because
 * that is the pattern @supabase/ssr is designed around: it internally reuses
 * the same underlying client per browser context, and calling it where you
 * need it keeps each component's data-fetching self-contained.
 *
 * The anon key respects Row Level Security, so anything this client can read
 * or write is already constrained to the logged-in user's tenant + role.
 *
 * DEV/TEST ONLY — session storage differs from production:
 * `createBrowserClient` always persists the session in cookies (it forces its
 * own cookie-based storage internally; passing a different `auth.storage`
 * option to it is silently ignored). Cookies are shared by every tab of the
 * same browser, which is exactly what real users want — sign in once, stay
 * signed in in every tab. But it also means logging in as a teacher in one
 * tab and a student in another overwrites the same cookie, so both tabs
 * eventually collapse onto whichever login happened most recently — this is
 * the session-collision bug. This app never reads the session on the server
 * (no middleware.ts, no createServerClient). Email/password sign-in doesn't
 * need a redirect at all, and Google sign-in (a real OAuth redirect flow) is
 * handled entirely client-side: `/auth/callback` exchanges the `?code=`
 * param itself via `exchangeCodeForSession`, so the cookie-vs-tab-session
 * split below doesn't need to special-case it. For local testing, we
 * use the plain `@supabase/supabase-js` client instead and point it at
 * `sessionStorage`, which the browser keeps separate per tab — so each tab
 * can hold its own logged-in test account. Production keeps the normal
 * cookie-based client untouched, so real users keep the "logged in
 * everywhere" behavior they expect.
 *
 * We can't gate this on `NODE_ENV !== "production"` alone: the local Docker
 * Compose setup (docker-compose.yml) builds the frontend the same way a real
 * prod deploy would, so `NODE_ENV` is `"production"` there too even though
 * it's only used for local testing. `NEXT_PUBLIC_DEV_SESSION_STORAGE` is the
 * explicit signal instead — set only in docker-compose.yml, never in the
 * real Vercel prod env.
 *
 * `detectSessionInUrl` is disabled below in both branches. It defaults to
 * true in a browser, which makes GoTrue auto-detect a `?code=` param and
 * exchange it in the background as soon as a client is constructed. Since
 * `/auth/callback` also exchanges that same code manually
 * (`exchangeCodeForSession`), the two would race for the same PKCE code
 * verifier — whichever runs second fails with "PKCE code verifier not found
 * in storage". Disabling auto-detection makes `/auth/callback` the sole,
 * deliberate exchanger.
 */
const useSessionStorage =
  process.env.NODE_ENV !== "production" ||
  process.env.NEXT_PUBLIC_DEV_SESSION_STORAGE === "true";

// Cached like createBrowserClient below caches its own instance. A browser
// tab has its own JS module scope (separate from every other tab), so this
// stays exactly as tab-isolated as the sessionStorage it reads/writes —
// caching it just avoids re-constructing a whole GoTrueClient (auto-refresh
// timers, storage parsing, etc.) on every single API call.
let cachedDevClient: ReturnType<typeof createSupabaseClient> | undefined;

export function createClient() {
  if (useSessionStorage) {
    if (!cachedDevClient) {
      cachedDevClient = createSupabaseClient(
        process.env.NEXT_PUBLIC_SUPABASE_URL!,
        process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
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
    return cachedDevClient;
  }
  return createBrowserClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      auth: {
        detectSessionInUrl: false,
      },
    },
  );
}
