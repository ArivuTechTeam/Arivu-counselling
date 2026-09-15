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
import { AlertTriangle, Trash, X } from "@/components/ui/icons";
import {
  InstitutionAdmin,
  TenantOption,
  createAdmin,
  deleteAdmin,
  listAdmins,
  listTenants,
} from "@/lib/api";

export function AdminManager({ embedded = false }: { embedded?: boolean }) {
  const [tenants, setTenants] = useState<TenantOption[]>([]);
  const [admins, setAdmins] = useState<InstitutionAdmin[] | null>(null);
  const [form, setForm] = useState({
    full_name: "",
    email: "",
    password: "",
    tenant_id: "",
  });
  const [busy, setBusy] = useState(false);
  const [removing, setRemoving] = useState<string | null>(null);
  const [confirmTarget, setConfirmTarget] = useState<InstitutionAdmin | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  function refresh() {
    setError(null);
    listAdmins()
      .then(setAdmins)
      .catch((e) => setError(e.message));
  }

  useEffect(() => {
    listTenants()
      .then((t) => {
        setTenants(t);
        setForm((f) => ({ ...f, tenant_id: t[0]?.id ?? "" }));
      })
      .catch((e) => setError(e.message));
    refresh();
  }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setNotice(null);
    if (!form.full_name || !form.email || !form.password || !form.tenant_id) {
      setError("Please fill in all fields.");
      return;
    }
    setBusy(true);
    try {
      await createAdmin(form);
      setNotice(`Admin ${form.email} created — they can sign in now.`);
      setForm((f) => ({ full_name: "", email: "", password: "", tenant_id: f.tenant_id }));
      refresh();
    } catch (e2) {
      setError(e2 instanceof Error ? e2.message : "Could not create admin");
    } finally {
      setBusy(false);
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
      refresh();
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
                  value={form.tenant_id}
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
                <Input
                  type="text"
                  value={form.password}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, password: e.target.value }))
                  }
                  placeholder="Share this with them"
                />
              </label>
            </div>
            {error && (
              <div className="flex items-start gap-2 rounded-lg border border-destructive/20 bg-destructive/5 px-3 py-2 text-sm text-destructive">
                <AlertTriangle size={16} className="mt-0.5 shrink-0" />
                <span>{error}</span>
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
                  <span className="rounded-full bg-brand-50 px-2 py-0.5 text-xs font-medium text-brand-700">
                    {a.institution}
                  </span>
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
    </div>
  );
}
