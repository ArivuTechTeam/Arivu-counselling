"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { AdminManager } from "@/components/admin/admin-manager";
import { Button } from "@/components/ui/button";
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
import { AlertTriangle, Eye, EyeOff } from "@/components/ui/icons";
import {
  InstitutionRow,
  getPlatformOverview,
  onboardInstitution,
} from "@/lib/api";

const field =
  "h-10 w-full rounded-md border border-input bg-background px-3 text-sm shadow-sm focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20";

function OnboardForm({ onDone }: { onDone: () => void }) {
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

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setOk(null);
    if (!name.trim() || !subdomain.trim()) {
      setError("Institution name and subdomain are required.");
      return;
    }
    setBusy(true);
    try {
      const res = await onboardInstitution({
        name: name.trim(),
        subdomain: subdomain.trim().toLowerCase(),
        plan_tier: plan,
        admin_full_name: adminName.trim() || undefined,
        admin_email: adminEmail.trim() || undefined,
        admin_password: adminPassword || undefined,
      });
      setOk(
        `Created "${res.name}"${res.admin ? ` with admin ${res.admin.email}` : ""}.`,
      );
      setName("");
      setSubdomain("");
      setAdminName("");
      setAdminEmail("");
      setAdminPassword("");
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not onboard institution.");
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
                onChange={(e) => setSubdomain(e.target.value)}
                placeholder="brightfuture"
              />
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
              <label className="flex flex-col gap-1.5 text-sm font-medium">
                Temporary password
                <div className="relative">
                  <input
                    className={`${field} pr-10`}
                    type={showPassword ? "text" : "password"}
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
              </label>
            </div>
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

export default function InstitutionsPage() {
  const [rows, setRows] = useState<InstitutionRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  function load() {
    setError(null);
    getPlatformOverview()
      .then((d) => setRows(d.institutions_table))
      .catch((e) => setError(e.message));
  }
  useEffect(load, []);

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
            <ErrorCard message={error} onRetry={load} />
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
    </div>
  );
}
