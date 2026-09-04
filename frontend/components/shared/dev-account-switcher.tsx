"use client";

import { useState } from "react";

import { createClient } from "@/lib/supabase";

/**
 * DEV-ONLY quick account switcher.
 *
 * Lets you hop between test accounts (super admin / institution admin / teacher
 * / student) without logging out and retyping credentials.
 *
 * Production safety: Next.js hard-codes process.env.NODE_ENV at build time. On
 * Vercel it is "production", so this component returns null and the minifier
 * drops the inner component + the test credentials from the deployed bundle.
 * These are throwaway TEST accounts only — never put a real user's password here.
 */
export function DevAccountSwitcher({ currentEmail }: { currentEmail: string }) {
  if (process.env.NODE_ENV === "production") return null;
  return <DevSwitcherInner currentEmail={currentEmail} />;
}

type DevAccount = {
  label: string;
  role: string;
  email: string;
  password: string;
};

// Populate NEXT_PUBLIC_DEV_ACCOUNTS_JSON in .env.local (gitignored) to use this
// switcher locally — see frontend/.env.local.example. Never commit real
// credentials here; this array must stay empty in the checked-in source.
function readDevAccounts(): DevAccount[] {
  const raw = process.env.NEXT_PUBLIC_DEV_ACCOUNTS_JSON;
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

const ACCOUNTS: DevAccount[] = readDevAccounts();

function BeakerIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 3h6" />
      <path d="M10 3v6.5L5 18a2 2 0 0 0 1.7 3h10.6A2 2 0 0 0 19 18l-5-8.5V3" />
      <path d="M7.5 14h9" />
    </svg>
  );
}

function DevSwitcherInner({ currentEmail }: { currentEmail: string }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function switchTo(acc: DevAccount) {
    if (acc.email === currentEmail) {
      setOpen(false);
      return;
    }
    setBusy(acc.email);
    setError(null);
    const supabase = createClient();
    await supabase.auth.signOut();
    const { error } = await supabase.auth.signInWithPassword({
      email: acc.email,
      password: acc.password,
    });
    if (error) {
      setError(error.message);
      setBusy(null);
      return;
    }
    // Full reload so the shared dashboard layout re-reads the new session and
    // rebuilds the sidebar for the newly selected role.
    window.location.assign("/dashboard");
  }

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1.5 rounded-full border border-amber-300 bg-amber-50 px-2.5 py-1 text-xs font-semibold text-amber-700 transition-colors hover:bg-amber-100"
        title="Dev-only account switcher (hidden in production)"
      >
        <BeakerIcon />
        Dev
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-20" onClick={() => setOpen(false)} />
          <div className="absolute right-0 top-full z-30 mt-2 w-64 overflow-hidden rounded-lg border bg-card shadow-lg">
            <div className="border-b bg-amber-50 px-4 py-2 text-[11px] font-semibold uppercase tracking-wide text-amber-700">
              Dev · switch account
            </div>
            {ACCOUNTS.map((acc) => {
              const current = acc.email === currentEmail;
              return (
                <button
                  key={acc.email}
                  onClick={() => switchTo(acc)}
                  disabled={!!busy}
                  className={`flex w-full items-center justify-between gap-2 px-4 py-2.5 text-left transition-colors hover:bg-accent disabled:opacity-60 ${
                    current ? "bg-primary/5" : ""
                  }`}
                >
                  <div className="min-w-0">
                    <div className="text-sm font-medium text-foreground">
                      {acc.label}
                    </div>
                    <div className="truncate text-xs text-muted-foreground">
                      {acc.email}
                    </div>
                  </div>
                  {busy === acc.email ? (
                    <span className="shrink-0 text-xs text-muted-foreground">
                      switching…
                    </span>
                  ) : current ? (
                    <span className="shrink-0 text-xs font-medium text-primary">
                      current
                    </span>
                  ) : null}
                </button>
              );
            })}
            {error && (
              <div className="border-t px-4 py-2 text-xs text-red-600">{error}</div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
