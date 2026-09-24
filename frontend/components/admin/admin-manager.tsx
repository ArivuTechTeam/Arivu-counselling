"use client";

import { useEffect, useState } from "react";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { PageHeader } from "@/components/ui/page-header";
import { EmptyState } from "@/components/ui/empty-state";
import { SkeletonList } from "@/components/ui/skeleton";
import {
  AlertTriangle,
  Eye,
  EyeOff,
  Sparkles,
  Trash,
  X,
} from "@/components/ui/icons";
import {
  TemporaryCredentials,
  TemporaryCredentialsDialog,
} from "@/components/admin/temporary-credentials-dialog";
import {
  InstitutionAdmin,
  createAdmin,
  deleteAdmin,
  resetAdminTemporaryPassword,
} from "@/lib/api";
import { usePlatformAdmins, usePlatformTenants } from "@/lib/staff-queries";
import {
  generateTemporaryPassword,
  validTemporaryPassword,
} from "@/lib/temporary-password";
import { institutionLoginUrl } from "@/lib/institution-portal";

const ADMIN_DRAFT_STORAGE_KEY = "super-admin-admin-draft";

export function AdminManager({ embedded = false }: { embedded?: boolean }) {
  const { data: tenants = [], error: tenantsError } = usePlatformTenants();
  const {
    data: admins = null,
    error: adminsError,
    mutate: refreshAdmins,
  } = usePlatformAdmins();
  const [form, setForm] = useState({
    full_name: "",
    email: "",
    password: "",
    tenant_id: "",
  });
  const [formHydrated, setFormHydrated] = useState(false);
  const [busy, setBusy] = useState(false);
  const [removing, setRemoving] = useState<string | null>(null);
  const [confirmTarget, setConfirmTarget] = useState<InstitutionAdmin | null>(null);
  const [resetTarget, setResetTarget] = useState<InstitutionAdmin | null>(null);
  const [resetPassword, setResetPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [credentials, setCredentials] = useState<TemporaryCredentials | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const selectedTenant = form.tenant_id || tenants[0]?.id || "";
  const directoryError = error ?? tenantsError?.message ?? adminsError?.message ?? null;

  useEffect(() => {
    try {
      const saved = window.sessionStorage.getItem(ADMIN_DRAFT_STORAGE_KEY);
      if (saved) {
        const parsed = JSON.parse(saved) as Record<string, unknown>;
        setForm((current) => ({
          ...current,
          tenant_id: typeof parsed.tenant_id === "string" ? parsed.tenant_id : "",
        }));
      }
    } catch {
      // Keep the blank form when the saved draft is invalid or unavailable.
    } finally {
      setFormHydrated(true);
    }
  }, []);

  useEffect(() => {
    if (!formHydrated) return;
    try {
      window.sessionStorage.setItem(
        ADMIN_DRAFT_STORAGE_KEY,
        JSON.stringify({
          tenant_id: form.tenant_id,
        }),
      );
    } catch {
      // The form still works if browser storage is unavailable.
    }
  }, [form.tenant_id, formHydrated]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setNotice(null);
    if (!form.full_name || !form.email || !form.password || !selectedTenant) {
      setError("Please fill in all fields.");
      return;
    }
    if (!validTemporaryPassword(form.password)) {
      setError(
        "Temporary password must have at least 12 characters with uppercase, lowercase, and a number.",
      );
      return;
    }
    setBusy(true);
    try {
      await createAdmin({ ...form, tenant_id: selectedTenant });
      const institution = tenants.find((tenant) => tenant.id === selectedTenant);
      setNotice(`Admin ${form.email} created — they can sign in now.`);
      setCredentials({
        email: form.email,
        password: form.password,
        institution: institution?.name ?? "Institution",
        loginUrl: institution?.subdomain
          ? institutionLoginUrl(institution.subdomain, window.location.origin)
          : undefined,
      });
      setForm((current) => ({
        full_name: "",
        email: "",
        password: "",
        tenant_id: current.tenant_id,
      }));
      await refreshAdmins();
    } catch (e2) {
      setError(e2 instanceof Error ? e2.message : "Could not create admin");
    } finally {
      setBusy(false);
    }
  }

  function openReset(admin: InstitutionAdmin) {
    setResetTarget(admin);
    setResetPassword(generateTemporaryPassword());
    setShowPassword(false);
    setError(null);
    setNotice(null);
  }

  async function confirmReset() {
    if (!resetTarget || !validTemporaryPassword(resetPassword)) return;
    setResetting(true);
    setError(null);
    try {
      await resetAdminTemporaryPassword(resetTarget.id, resetPassword);
      setCredentials({
        email: resetTarget.email ?? "",
        password: resetPassword,
        institution: resetTarget.institution,
        loginUrl: resetTarget.subdomain
          ? institutionLoginUrl(resetTarget.subdomain, window.location.origin)
          : undefined,
      });
      setNotice(
        `Temporary login reset for ${resetTarget.email ?? resetTarget.full_name}.`,
      );
      setResetTarget(null);
      setResetPassword("");
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Could not reset administrator login.",
      );
    } finally {
      setResetting(false);
    }
  }

  async function confirmRemove() {
    const a = confirmTarget;
    if (!a) return;
    setConfirmTarget(null);
    setRemoving(a.id);
    setError(null);
    setNotice(null);
    try {
      await deleteAdmin(a.id);
      setNotice(`Removed ${a.email ?? a.full_name}.`);
      await refreshAdmins();
    } catch (e2) {
      setError(e2 instanceof Error ? e2.message : "Could not remove admin");
    } finally {
      setRemoving(null);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      {!embedded && (
        <PageHeader
          title="Institution admins"
          description="Create and manage admins (principals) for each institution."
        />
      )}

      <Card className="animate-rise">
        <CardHeader>
          <CardTitle>Add an institution admin</CardTitle>
          <CardDescription>
            They can manage their institution&apos;s users, courses and analytics.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={submit} className="flex flex-col gap-4">
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <label className="flex flex-col gap-1.5 text-sm font-medium">
                Full name
                <Input
                  value={form.full_name}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, full_name: e.target.value }))
                  }
                  placeholder="e.g. Priya Menon"
                />
              </label>
              <label className="flex flex-col gap-1.5 text-sm font-medium">
                Institution
                <select
                  className="h-10 rounded-md border border-input bg-background px-3 text-sm shadow-sm focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
                  value={selectedTenant}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, tenant_id: e.target.value }))
                  }
                >
                  {tenants.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex flex-col gap-1.5 text-sm font-medium">
                Email
                <Input
                  type="email"
                  value={form.email}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, email: e.target.value }))
                  }
                  placeholder="admin@institute.com"
                />
              </label>
              <label className="flex flex-col gap-1.5 text-sm font-medium">
                Temporary password
                <div className="flex gap-2">
                  <Input
                    type={showPassword ? "text" : "password"}
                    autoComplete="new-password"
                    value={form.password}
                    onChange={(e) =>
                      setForm((f) => ({ ...f, password: e.target.value }))
                    }
                    placeholder="Share this with them"
                  />
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => {
                      setForm((current) => ({
                        ...current,
                        password: generateTemporaryPassword(),
                      }));
                      setShowPassword(true);
                    }}
                  >
                    <Sparkles size={15} className="mr-1.5" />
                    Generate
                  </Button>
                </div>
              </label>
            </div>
            {directoryError && (
              <div className="flex items-start gap-2 rounded-lg border border-destructive/20 bg-destructive/5 px-3 py-2 text-sm text-destructive">
                <AlertTriangle size={16} className="mt-0.5 shrink-0" />
                <span>{directoryError}</span>
              </div>
            )}
            {notice && (
              <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
                {notice}
              </div>
            )}
            <div>
              <Button type="submit" disabled={busy}>
                {busy ? "Creating…" : "Create admin"}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>

      <Card className="animate-rise" style={{ animationDelay: "80ms" }}>
        <CardHeader>
          <CardTitle>Existing admins</CardTitle>
          <CardDescription>Institution admins across the platform.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          {admins === null ? (
            <SkeletonList />
          ) : admins.length === 0 ? (
            <EmptyState message="No institution admins yet." />
          ) : (
            admins.map((a) => (
              <div
                key={a.id}
                className="flex items-center justify-between gap-4 rounded-lg border bg-card p-4 text-sm"
              >
                <div className="min-w-0">
                  <p className="truncate font-medium text-foreground">
                    {a.full_name ?? "—"}
                  </p>
                  <p className="text-xs text-muted-foreground">{a.email}</p>
                </div>
                <div className="flex shrink-0 items-center gap-3">
                  <div className="max-w-64 text-right">
                    <span className="rounded-full bg-brand-50 px-2 py-0.5 text-xs font-medium text-brand-700">
                      {a.institution}
                    </span>
                    <p
                      className="mt-1 truncate text-xs text-muted-foreground"
                      title={a.courses.join(", ")}
                    >
                      {a.course_count > 0
                        ? `${a.course_count} course${a.course_count === 1 ? "" : "s"}: ${a.courses.join(", ")}`
                        : "No courses assigned"}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => openReset(a)}
                    className="inline-flex items-center gap-1 text-xs font-medium text-primary transition-colors hover:underline"
                  >
                    <Sparkles size={13} />
                    Reset &amp; copy
                  </button>
                  <button
                    onClick={() => setConfirmTarget(a)}
                    disabled={removing === a.id}
                    className="inline-flex items-center gap-1 text-xs font-medium text-red-600 transition-colors hover:underline disabled:opacity-50"
                  >
                    <Trash size={13} />
                    {removing === a.id ? "Removing…" : "Remove"}
                  </button>
                </div>
              </div>
            ))
          )}
        </CardContent>
      </Card>

      {confirmTarget && (
        <Dialog
          onClose={() => setConfirmTarget(null)}
          ariaLabelledBy="remove-admin-title"
          contentClassName="w-full max-w-md rounded-2xl border bg-card p-6 shadow-xl"
        >
            <div className="flex items-start justify-between gap-4">
              <div className="flex items-center gap-3">
                <span className="flex h-10 w-10 items-center justify-center rounded-full bg-destructive/10 text-destructive">
                  <Trash size={18} />
                </span>
                <h2
                  id="remove-admin-title"
                  className="text-base font-semibold text-foreground"
                >
                  Remove admin
                </h2>
              </div>
              <button
                onClick={() => setConfirmTarget(null)}
                className="rounded-md p-1 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                aria-label="Close"
              >
                <X size={18} />
              </button>
            </div>
            <p className="mt-4 text-sm text-muted-foreground">
              Remove{" "}
              <span className="font-medium text-foreground">
                {confirmTarget.full_name ?? confirmTarget.email}
              </span>
              ? They lose access to {confirmTarget.institution} immediately.
            </p>
            <div className="mt-6 flex justify-end gap-3">
              <Button variant="outline" onClick={() => setConfirmTarget(null)}>
                Cancel
              </Button>
              <button
                onClick={confirmRemove}
                className="inline-flex items-center gap-1.5 rounded-md bg-destructive px-4 py-2 text-sm font-medium text-destructive-foreground shadow-sm transition-colors hover:bg-destructive/90"
              >
                <Trash size={15} />
                Remove
              </button>
            </div>
        </Dialog>
      )}

      {resetTarget && (
        <Dialog
          onClose={() => !resetting && setResetTarget(null)}
          ariaLabelledBy="reset-admin-title"
          contentClassName="w-full max-w-lg rounded-2xl border bg-card p-6 shadow-xl"
        >
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 id="reset-admin-title" className="text-lg font-semibold">
                Reset administrator login
              </h2>
              <p className="mt-1 text-sm text-muted-foreground">
                This replaces the current password for {resetTarget.email}. They
                must change it after signing in.
              </p>
            </div>
            <button
              type="button"
              onClick={() => setResetTarget(null)}
              disabled={resetting}
              aria-label="Close"
              className="rounded-md p-1 text-muted-foreground hover:bg-accent hover:text-foreground disabled:opacity-50"
            >
              <X size={18} />
            </button>
          </div>

          <label className="mt-5 flex flex-col gap-1.5 text-sm font-medium">
            New temporary password
            <div className="flex gap-2">
              <div className="relative min-w-0 flex-1">
                <Input
                  type={showPassword ? "text" : "password"}
                  autoComplete="new-password"
                  value={resetPassword}
                  onChange={(event) => setResetPassword(event.target.value)}
                  className="pr-10"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((current) => !current)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 rounded-md p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
                  aria-label={showPassword ? "Hide password" : "Show password"}
                >
                  {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
              <Button
                type="button"
                variant="outline"
                onClick={() => {
                  setResetPassword(generateTemporaryPassword());
                  setShowPassword(true);
                }}
              >
                <Sparkles size={15} className="mr-1.5" />
                Generate
              </Button>
            </div>
          </label>
          <p className="mt-2 text-xs text-muted-foreground">
            The previous password will stop working immediately.
          </p>

          <div className="mt-6 flex justify-end gap-3">
            <Button
              type="button"
              variant="outline"
              onClick={() => setResetTarget(null)}
              disabled={resetting}
            >
              Cancel
            </Button>
            <Button
              type="button"
              onClick={confirmReset}
              disabled={resetting || !validTemporaryPassword(resetPassword)}
            >
              {resetting ? "Resetting…" : "Reset and show credentials"}
            </Button>
          </div>
        </Dialog>
      )}

      {credentials && (
        <TemporaryCredentialsDialog
          credentials={credentials}
          onClose={() => setCredentials(null)}
        />
      )}
    </div>
  );
}
