"use client";

import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { AlertTriangle, Check } from "@/components/ui/icons";
import { changePassword } from "@/lib/api";

/**
 * In-dashboard "change your password" modal. Shown forced on first login for
 * every admin-created account (super-admin → institution-admin → teacher →
 * student all get a temp password), and on demand from the account menu.
 *
 * Production-grade flow: the user proves the CURRENT password, and the NEW one
 * must pass the strong policy (≥8 chars incl. upper/lower/number, different
 * from the current one). The same rules are re-checked on the server — this
 * checklist is just live guidance.
 *
 * `forced` = shown because the account still has an admin-set temp password
 * (no Cancel; they must set a real password to continue).
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
  const [current, setCurrent] = useState("");
  const [pw, setPw] = useState("");
  const [confirm, setConfirm] = useState("");
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Live strength rules — must mirror the server (auth_account._validate_new_password).
  const rules = useMemo(
    () => [
      { label: "At least 8 characters", ok: pw.length >= 8 },
      { label: "An uppercase letter (A–Z)", ok: /[A-Z]/.test(pw) },
      { label: "A lowercase letter (a–z)", ok: /[a-z]/.test(pw) },
      { label: "A number (0–9)", ok: /[0-9]/.test(pw) },
      {
        label: "Different from your current password",
        ok: pw.length > 0 && pw !== current,
      },
    ],
    [pw, current],
  );
  const allRulesOk = rules.every((r) => r.ok);
  const matches = pw.length > 0 && pw === confirm;
  const canSubmit = current.length > 0 && allRulesOk && matches && !busy;

  if (!open) return null;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!allRulesOk) {
      setError("Your new password doesn't meet all the requirements yet.");
      return;
    }
    if (!matches) {
      setError("The two new passwords don't match.");
      return;
    }
    setBusy(true);
    try {
      await changePassword(current, pw);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not change password.");
      setBusy(false);
      return;
    }
    setBusy(false);
    setCurrent("");
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
            Current password
            <input
              className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm shadow-sm focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
              type={show ? "text" : "password"}
              value={current}
              onChange={(e) => setCurrent(e.target.value)}
              placeholder={
                forced ? "The password your admin gave you" : "Your current password"
              }
              autoFocus
              autoComplete="current-password"
            />
          </label>

          <label className="flex flex-col gap-1.5 text-sm font-medium">
            New password
            <div className="relative">
              <input
                className={fieldClass}
                type={show ? "text" : "password"}
                value={pw}
                onChange={(e) => setPw(e.target.value)}
                placeholder="Choose a strong password"
                autoComplete="new-password"
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

          {/* Live requirements checklist */}
          <ul className="flex flex-col gap-1 rounded-lg bg-muted/50 p-3">
            {rules.map((r) => (
              <li
                key={r.label}
                className={`flex items-center gap-2 text-xs transition-colors ${
                  r.ok ? "text-emerald-600" : "text-muted-foreground"
                }`}
              >
                <span
                  className={`flex h-4 w-4 shrink-0 items-center justify-center rounded-full border transition-colors ${
                    r.ok
                      ? "border-emerald-500 bg-emerald-500 text-white"
                      : "border-muted-foreground/40"
                  }`}
                >
                  {r.ok && <Check size={11} />}
                </span>
                {r.label}
              </li>
            ))}
          </ul>

          <label className="flex flex-col gap-1.5 text-sm font-medium">
            Confirm new password
            <input
              className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm shadow-sm focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
              type={show ? "text" : "password"}
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              placeholder="Enter the new password again"
              autoComplete="new-password"
            />
            {confirm.length > 0 && !matches && (
              <span className="text-xs text-destructive">
                These don&apos;t match yet.
              </span>
            )}
          </label>

          {error && (
            <div className="flex items-center gap-2 rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
              <AlertTriangle size={14} />
              <span>{error}</span>
            </div>
          )}

          <div className="mt-2 flex justify-end gap-2">
            {!forced && (
              <Button type="button" variant="outline" onClick={onClose} disabled={busy}>
                Cancel
              </Button>
            )}
            <Button type="submit" disabled={!canSubmit}>
              {busy ? "Saving…" : "Change password"}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
