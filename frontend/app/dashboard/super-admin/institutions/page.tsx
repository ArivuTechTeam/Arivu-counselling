"use client";

import { useState } from "react";
import Link from "next/link";
import { useSWRConfig } from "swr";

import { AdminManager } from "@/components/admin/admin-manager";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { ErrorCard } from "@/components/ui/error-card";
import { EmptyState } from "@/components/ui/empty-state";
import { SkeletonList } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import { AlertTriangle, Eye, EyeOff, Pencil, Sparkles, X } from "@/components/ui/icons";
import {
  InstitutionRow,
  onboardInstitution,
  updateInstitution,
} from "@/lib/api";
import { STAFF_QUERY_KEYS, usePlatformOverview } from "@/lib/staff-queries";
import {
  generateTemporaryPassword,
  validTemporaryPassword,
} from "@/lib/temporary-password";

const field =
  "h-10 w-full rounded-md border border-input bg-background px-3 text-sm shadow-sm focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20";

function OnboardForm({ onDone }: { onDone: () => void | Promise<void> }) {
  const { notify } = useToast();
  const [name, setName] = useState("");
  const [subdomain, setSubdomain] = useState("");
  const [plan, setPlan] = useState("free");
  const [adminName, setAdminName] = useState("");
  const [adminEmail, setAdminEmail] = useState("");
  const [adminPassword, setAdminPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);

  function generatePassword() {
    setAdminPassword(generateTemporaryPassword());
    setShowPassword(true);
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setOk(null);
    if (!name.trim() || !subdomain.trim()) {
      const message = "Institution name and subdomain are required.";
      setError(message);
      notify(message, "error");
      return;
    }
    if (adminPassword && !validTemporaryPassword(adminPassword)) {
      const message =
        "Temporary password must have at least 12 characters with uppercase, lowercase, and a number.";
      setError(message);
      notify(message, "error");
      return;
    }
    setBusy(true);
    try {
      await onboardInstitution({
        name: name.trim(),
        subdomain: subdomain.trim().toLowerCase(),
        plan_tier: plan,
        admin_full_name: adminName.trim() || undefined,
        admin_email: adminEmail.trim() || undefined,
        admin_password: adminPassword || undefined,
      });
      setOk(
        `Created "${name.trim()}"${adminEmail.trim() ? ` with admin ${adminEmail.trim()}` : ""}.`,
      );
      notify(`Institution "${name.trim()}" created successfully.`, "success");
      setName("");
      setSubdomain("");
      setAdminName("");
      setAdminEmail("");
      setAdminPassword("");
      await onDone();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Could not onboard institution.";
      setError(message);
      notify(message, "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="animate-rise">
      <CardHeader>
        <CardTitle>Onboard an institution</CardTitle>
        <CardDescription>
          Create a new tenant and, optionally, its first institution admin.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={submit} className="flex flex-col gap-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <label className="flex flex-col gap-1.5 text-sm font-medium">
              Institution name
              <input
                className={field}
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Bright Future Academy"
              />
            </label>
            <label className="flex flex-col gap-1.5 text-sm font-medium">
              Subdomain
              <input
                className={field}
                value={subdomain}
                onChange={(e) =>
                  setSubdomain(
                    e.target.value
                      .toLowerCase()
                      .replace(/\s+/g, "-")
                      .replace(/[^a-z0-9-]/g, "")
                      .replace(/-+/g, "-"),
                  )
                }
                placeholder="brightfuture"
              />
              <span className="text-xs font-normal text-muted-foreground">
                Spaces are converted to hyphens.
              </span>
            </label>
            <label className="flex flex-col gap-1.5 text-sm font-medium">
              Plan
              <select className={field} value={plan} onChange={(e) => setPlan(e.target.value)}>
                <option value="free">Free</option>
                <option value="starter">Starter</option>
                <option value="growth">Growth</option>
                <option value="enterprise">Enterprise</option>
              </select>
            </label>
          </div>

          <div className="rounded-lg border border-dashed p-4">
            <p className="mb-3 text-sm font-medium text-muted-foreground">
              First institution admin (optional)
            </p>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
              <label className="flex flex-col gap-1.5 text-sm font-medium">
                Full name
                <input
                  className={field}
                  value={adminName}
                  onChange={(e) => setAdminName(e.target.value)}
                  placeholder="Principal name"
                />
              </label>
              <label className="flex flex-col gap-1.5 text-sm font-medium">
                Email
                <input
                  className={field}
                  type="email"
                  value={adminEmail}
                  onChange={(e) => setAdminEmail(e.target.value)}
                  placeholder="admin@institution.com"
                />
              </label>
              <div className="flex flex-col gap-1.5 text-sm font-medium">
                Temporary password
                <div className="flex gap-2">
                  <div className="relative min-w-0 flex-1">
                    <input
                      className={`${field} pr-10`}
                      type={showPassword ? "text" : "password"}
                      autoComplete="new-password"
                      value={adminPassword}
                      onChange={(e) => setAdminPassword(e.target.value)}
                      placeholder="Share securely"
                    />
                    <button
                      type="button"
                      onClick={() => setShowPassword((v) => !v)}
                      className="absolute right-2 top-1/2 -translate-y-1/2 rounded-md p-1 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                      aria-label={showPassword ? "Hide password" : "Show password"}
                    >
                      {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                    </button>
                  </div>
                  <Button type="button" variant="outline" onClick={generatePassword}>
                    <Sparkles size={15} className="mr-1.5" />
                    Generate
                  </Button>
                </div>
              </div>
            </div>
            <p className="mt-2 text-xs text-muted-foreground">
              Use at least 12 characters with uppercase, lowercase, and a number.
            </p>
          </div>

          {error && (
            <div className="flex items-start gap-2 rounded-lg border border-destructive/20 bg-destructive/5 px-3 py-2 text-sm text-destructive">
              <AlertTriangle size={16} className="mt-0.5 shrink-0" />
              <span>{error}</span>
            </div>
          )}
          {ok && (
            <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
              {ok}
            </div>
          )}

          <div>
            <Button type="submit" disabled={busy}>
              {busy ? "Onboarding…" : "Onboard institution"}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

function EditInstitutionDialog({
  institution,
  onClose,
  onSaved,
}: {
  institution: InstitutionRow;
  onClose: () => void;
  onSaved: () => void | Promise<void>;
}) {
  const [name, setName] = useState(institution.name);
  const [plan, setPlan] = useState(institution.plan_tier ?? "free");
  const [isActive, setIsActive] = useState(institution.is_active);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!name.trim()) {
      setError("Institution name is required.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await updateInstitution(institution.id, {
        name: name.trim(),
        plan_tier: plan as "free" | "starter" | "growth" | "enterprise",
        is_active: isActive,
      });
      await onSaved();
      onClose();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not update institution.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      onClose={onClose}
      ariaLabelledBy="edit-institution-title"
      contentClassName="w-full max-w-lg rounded-2xl border bg-card p-6 shadow-xl"
    >
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 id="edit-institution-title" className="text-lg font-semibold">
            Manage institution
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">{institution.subdomain}</p>
        </div>
        <button onClick={onClose} aria-label="Close" className="rounded-md p-1 hover:bg-accent">
          <X size={18} />
        </button>
      </div>
      <form onSubmit={submit} className="mt-5 flex flex-col gap-4">
        <label className="flex flex-col gap-1.5 text-sm font-medium">
          Institution name
          <input className={field} value={name} onChange={(event) => setName(event.target.value)} />
        </label>
        <label className="flex flex-col gap-1.5 text-sm font-medium">
          Plan
          <select className={field} value={plan} onChange={(event) => setPlan(event.target.value)}>
            <option value="free">Free</option>
            <option value="starter">Starter</option>
            <option value="growth">Growth</option>
            <option value="enterprise">Enterprise</option>
          </select>
        </label>
        <label className="flex items-start gap-3 rounded-lg border p-3 text-sm">
          <input
            type="checkbox"
            checked={isActive}
            onChange={(event) => setIsActive(event.target.checked)}
            className="mt-0.5 h-4 w-4 accent-primary"
          />
          <span>
            <strong className="block font-medium">Institution active</strong>
            <span className="text-muted-foreground">
              Turn this off to suspend the institution without deleting its data.
            </span>
          </span>
        </label>
        {error && (
          <div className="rounded-lg border border-destructive/20 bg-destructive/5 px-3 py-2 text-sm text-destructive">
            {error}
          </div>
        )}
        <div className="flex justify-end gap-3">
          <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
          <Button type="submit" disabled={busy}>{busy ? "Saving…" : "Save changes"}</Button>
        </div>
      </form>
    </Dialog>
  );
}

export default function InstitutionsPage() {
  const { mutate: mutateCache } = useSWRConfig();
  const { data, error, mutate } = usePlatformOverview();
  const [editing, setEditing] = useState<InstitutionRow | null>(null);
  const rows = data?.institutions_table ?? null;
  const load = async () => {
    await Promise.all([
      mutate(),
      mutateCache(STAFF_QUERY_KEYS.platformTenants),
      mutateCache(STAFF_QUERY_KEYS.platformAdmins),
    ]);
  };

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Institutions"
        description="Onboard and monitor every institution on the platform."
      />

      <OnboardForm onDone={load} />

      <Card className="animate-rise">
        <CardHeader>
          <CardTitle>All institutions</CardTitle>
          <CardDescription>
            {rows === null ? "Loading…" : `${rows.length} on the platform.`}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {error ? (
            <ErrorCard message={error.message} onRetry={load} />
          ) : rows === null ? (
            <SkeletonList />
          ) : rows.length === 0 ? (
            <EmptyState
              title="No institutions yet"
              message="Use the form above to onboard your first institution."
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-xs uppercase tracking-wide text-muted-foreground">
                    <th className="px-2 py-2 font-medium">Institution</th>
                    <th className="px-2 py-2 text-right font-medium">Admins</th>
                    <th className="px-2 py-2 text-right font-medium">Teachers</th>
                    <th className="px-2 py-2 text-right font-medium">Students</th>
                    <th className="px-2 py-2 text-right font-medium">Quiz sets</th>
                    <th className="px-2 py-2 text-right font-medium">Plan</th>
                    <th className="px-2 py-2 text-right font-medium">Status</th>
                    <th className="px-2 py-2 text-right font-medium">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.id} className="border-b last:border-0 hover:bg-accent">
                      <td className="px-2 py-2.5">
                        <Link href={`/dashboard/super-admin/institutions/${r.id}`} className="font-medium text-primary hover:underline">
                          {r.name} →
                        </Link>
                        <div className="text-xs text-muted-foreground">{r.subdomain}</div>
                      </td>
                      <td className="px-2 py-2.5 text-right text-muted-foreground">{r.admins}</td>
                      <td className="px-2 py-2.5 text-right text-muted-foreground">{r.teachers}</td>
                      <td className="px-2 py-2.5 text-right text-muted-foreground">{r.students}</td>
                      <td className="px-2 py-2.5 text-right text-muted-foreground">{r.quiz_sets}</td>
                      <td className="px-2 py-2.5 text-right">
                        <span className="rounded-full bg-muted px-2 py-0.5 text-xs font-medium capitalize text-muted-foreground">
                          {r.plan_tier ?? "free"}
                        </span>
                      </td>
                      <td className="px-2 py-2.5 text-right">
                        <span
                          className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                            r.is_active
                              ? "bg-emerald-100 text-emerald-700"
                              : "bg-muted text-muted-foreground"
                          }`}
                        >
                          {r.is_active ? "active" : "inactive"}
                        </span>
                      </td>
                      <td className="px-2 py-2.5 text-right">
                        <button
                          onClick={() => setEditing(r)}
                          className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
                        >
                          <Pencil size={13} /> Manage
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Manage institution admins */}
      <AdminManager embedded />

      {editing && (
        <EditInstitutionDialog
          institution={editing}
          onClose={() => setEditing(null)}
          onSaved={load}
        />
      )}
    </div>
  );
}
