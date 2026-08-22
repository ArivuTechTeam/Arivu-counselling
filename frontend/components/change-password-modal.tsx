"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { createClient } from "@/lib/supabase";

/**
 * In-dashboard "change your password" modal. The user is already logged in, so
 * we set the new password directly (no email round-trip) and clear the
 * `must_change_password` flag in the same call.
 *
 * `forced` = shown because the account still has an admin-set temp password.
 */
export function ChangePasswordModal({
  open,
  forced,
  onClose,
  onDone,
}: {
  open: boolean;
  forced: boolean;
  onClose: () => void;
  onDone: () => void;
}) {
  const [pw, setPw] = useState("");
  const [confirm, setConfirm] = useState("");
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!open) return null;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (pw.length < 8) {
      setError("Use at least 8 characters.");
      return;
    }
    if (pw !== confirm) {
      setError("The two passwords don't match.");
      return;
    }
    setBusy(true);
    const supabase = createClient();
    const { error: err } = await supabase.auth.updateUser({
      password: pw,
      data: { must_change_password: false },
    });
    setBusy(false);
    if (err) {
      setError(err.message);
      return;
    }
    setPw("");
    setConfirm("");
    onDone();
  }

  const fieldClass =
    "h-10 w-full rounded-md border border-input bg-background px-3 pr-16 text-sm shadow-sm focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="animate-rise w-full max-w-md rounded-2xl bg-card p-6 shadow-xl">
        <h2 className="text-lg font-semibold text-foreground">
          {forced ? "Set a new password" : "Change your password"}
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          {forced
            ? "For your security, please replace the temporary password your administrator set for you."
            : "Choose a new password for your account."}
        </p>

        <form onSubmit={submit} className="mt-4 flex flex-col gap-3">
          <label className="flex flex-col gap-1.5 text-sm font-medium">
            New password
            <div className="relative">
              <input
                className={fieldClass}
                type={show ? "text" : "password"}
                value={pw}
                onChange={(e) => setPw(e.target.value)}
                placeholder="At least 8 characters"
                autoFocus
              />
              <button
                type="button"
                onClick={() => setShow((s) => !s)}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-xs font-medium text-muted-foreground hover:text-primary"
              >
                {show ? "Hide" : "Show"}
              </button>
            </div>
          </label>

          <label className="flex flex-col gap-1.5 text-sm font-medium">
            Confirm new password
            <input
              className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm shadow-sm focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
              type={show ? "text" : "password"}
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              placeholder="Re-type the password"
            />
          </label>

          {error && <p className="text-sm text-red-600">{error}</p>}

          <div className="mt-2 flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={onClose} disabled={busy}>
              {forced ? "Later" : "Cancel"}
            </Button>
            <Button type="submit" disabled={busy}>
              {busy ? "Saving…" : "Set password"}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
