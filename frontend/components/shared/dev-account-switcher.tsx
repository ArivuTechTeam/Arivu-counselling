"use client";

import { useCallback, useState } from "react";

import { useEscapeKey } from "@/components/ui/dialog";
import { createClient } from "@/lib/supabase";

/**
 * DEV-ONLY quick account switcher.
 *
 * Lets you hop between test accounts (super admin / institution admin / teacher
 * / student) without retyping email addresses.
 *
 * Production safety: Next.js hard-codes process.env.NODE_ENV at build time. On
 * Vercel it is "production", so this component returns null. The public config
 * contains labels and emails only; passwords are always entered at runtime and
 * are never compiled into browser JavaScript.
 */
export function DevAccountSwitcher({ currentEmail }: { currentEmail: string }) {
  if (process.env.NODE_ENV === "production") return null;
  return <DevSwitcherInner currentEmail={currentEmail} />;
}

type DevAccount = {
  label: string;
  role: string;
  email: string;
};

// NEXT_PUBLIC values are browser-readable by definition. This configuration is
// deliberately limited to non-secret labels/emails; never add passwords here.
function readDevAccounts(): DevAccount[] {
  // The production branch is eliminated at build time, so local account
  // labels/emails never become part of a production browser bundle even if a
  // deployment environment accidentally defines the development variable.
  const raw =
    process.env.NODE_ENV === "production"
      ? "[]"
      : process.env.NEXT_PUBLIC_DEV_ACCOUNT_EMAILS_JSON?.trim() || "[]";
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (account): account is DevAccount =>
        !!account &&
        typeof account.label === "string" &&
        typeof account.role === "string" &&
        typeof account.email === "string",
    );
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
  const [selected, setSelected] = useState<DevAccount | null>(null);
  const [password, setPassword] = useState("");
  const close = useCallback(() => setOpen(false), []);

  useEscapeKey(open, close);

  async function switchTo() {
    if (!selected || !password) return;
    setBusy(selected.email);
    setError(null);
    const supabase = createClient();
    const { error } = await supabase.auth.signInWithPassword({
      email: selected.email,
      password,
    });
    if (error) {
      setError("Sign-in failed. Check the selected account and password.");
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
          <div className="fixed inset-0 z-20" onClick={close} />
          <div
            role="dialog"
            aria-modal="true"
            aria-label="Switch development account"
            className="absolute right-0 top-full z-30 mt-2 w-64 overflow-hidden rounded-lg border bg-card shadow-lg"
          >
            <div className="border-b bg-amber-50 px-4 py-2 text-[11px] font-semibold uppercase tracking-wide text-amber-700">
              Dev · switch account
            </div>
            {ACCOUNTS.map((acc) => {
              const current = acc.email === currentEmail;
              return (
                <button
                  key={acc.email}
                  onClick={() => {
                    if (current) {
                      setOpen(false);
                      return;
                    }
                    setSelected(acc);
                    setPassword("");
                    setError(null);
                  }}
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
            {selected && (
              <form
                className="space-y-2 border-t p-3"
                onSubmit={(event) => {
                  event.preventDefault();
                  void switchTo();
                }}
              >
                <label className="block text-xs font-medium text-foreground">
                  Password for {selected.label}
                  <input
                    className="mt-1 h-9 w-full rounded-md border bg-background px-3 text-sm outline-none focus:ring-2 focus:ring-primary/30"
                    type="password"
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    autoComplete="current-password"
                    autoFocus
                  />
                </label>
                <button
                  className="h-9 w-full rounded-md bg-primary text-sm font-medium text-primary-foreground disabled:opacity-50"
                  type="submit"
                  disabled={!password || !!busy}
                >
                  {busy ? "Switching…" : "Switch account"}
                </button>
              </form>
            )}
            {error && (
              <div className="border-t px-4 py-2 text-xs text-red-600">{error}</div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
