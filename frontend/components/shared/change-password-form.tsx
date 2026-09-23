"use client";

import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { AlertTriangle, Check } from "@/components/ui/icons";
import { changePassword } from "@/lib/api";

export function ChangePasswordForm({
  forced = false,
  onDone,
  onCancel,
}: {
  forced?: boolean;
  onDone: () => void;
  onCancel?: () => void;
}) {
  const [current, setCurrent] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const rules = useMemo(
    () => [
      { label: "At least 8 characters", ok: password.length >= 8 },
      { label: "An uppercase letter (A–Z)", ok: /[A-Z]/.test(password) },
      { label: "A lowercase letter (a–z)", ok: /[a-z]/.test(password) },
      { label: "A number (0–9)", ok: /[0-9]/.test(password) },
      {
        label: "Different from your current password",
        ok: password.length > 0 && password !== current,
      },
    ],
    [password, current],
  );
  const allRulesOk = rules.every((rule) => rule.ok);
  const matches = password.length > 0 && password === confirm;
  const canSubmit = current.length > 0 && allRulesOk && matches && !busy;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
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
      await changePassword(current, password);
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "Could not change password.",
      );
      setBusy(false);
      return;
    }
    setBusy(false);
    setCurrent("");
    setPassword("");
    setConfirm("");
    onDone();
  }

  const fieldClass =
    "h-10 w-full rounded-md border border-input bg-background px-3 text-sm shadow-sm focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20";

  return (
    <form onSubmit={submit} className="flex flex-col gap-3">
      <label className="flex flex-col gap-1.5 text-sm font-medium">
        Current password
        <input
          className={fieldClass}
          type={show ? "text" : "password"}
          value={current}
          onChange={(event) => setCurrent(event.target.value)}
          placeholder={
            forced ? "The password your admin gave you" : "Your current password"
          }
          autoFocus={forced}
          autoComplete="current-password"
        />
      </label>

      <label className="flex flex-col gap-1.5 text-sm font-medium">
        New password
        <div className="relative">
          <input
            className={`${fieldClass} pr-16`}
            type={show ? "text" : "password"}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            placeholder="Choose a strong password"
            autoComplete="new-password"
          />
          <button
            type="button"
            onClick={() => setShow((visible) => !visible)}
            className="absolute right-2 top-1/2 -translate-y-1/2 text-xs font-medium text-muted-foreground hover:text-primary"
          >
            {show ? "Hide" : "Show"}
          </button>
        </div>
      </label>

      <ul className="flex flex-col gap-1 rounded-lg bg-muted/50 p-3">
        {rules.map((rule) => (
          <li
            key={rule.label}
            className={`flex items-center gap-2 text-xs transition-colors ${
              rule.ok ? "text-emerald-600" : "text-muted-foreground"
            }`}
          >
            <span
              className={`flex h-4 w-4 shrink-0 items-center justify-center rounded-full border transition-colors ${
                rule.ok
                  ? "border-emerald-500 bg-emerald-500 text-white"
                  : "border-muted-foreground/40"
              }`}
            >
              {rule.ok && <Check size={11} />}
            </span>
            {rule.label}
          </li>
        ))}
      </ul>

      <label className="flex flex-col gap-1.5 text-sm font-medium">
        Confirm new password
        <input
          className={fieldClass}
          type={show ? "text" : "password"}
          value={confirm}
          onChange={(event) => setConfirm(event.target.value)}
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
        <div
          className="flex items-center gap-2 rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive"
          role="alert"
        >
          <AlertTriangle size={14} />
          <span>{error}</span>
        </div>
      )}

      <div className="mt-2 flex justify-end gap-2">
        {onCancel && (
          <Button type="button" variant="outline" onClick={onCancel} disabled={busy}>
            Cancel
          </Button>
        )}
        <Button type="submit" disabled={!canSubmit}>
          {busy ? "Saving…" : forced ? "Set new password" : "Change password"}
        </Button>
      </div>
    </form>
  );
}
