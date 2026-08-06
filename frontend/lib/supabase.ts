import { createBrowserClient } from "@supabase/ssr";

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
 */
export function createClient() {
  return createBrowserClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
  );
}
