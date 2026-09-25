"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useSWRConfig } from "swr";

import {
  TemporaryCredentials,
  TemporaryCredentialsDialog,
} from "@/components/admin/temporary-credentials-dialog";
import { CatalogSubjectPicker } from "@/components/admin/catalog-subject-picker";
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
import { AlertTriangle, BookOpen, Copy, Eye, EyeOff, Pencil, Sparkles, X } from "@/components/ui/icons";
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
import { useSessionStorageState } from "@/lib/use-session-storage-state";
import {
  institutionLoginUrl,
  normalizeInstitutionSlug,
} from "@/lib/institution-portal";
import {
  DEFAULT_INSTITUTION_COLOR,
  institutionThemeStyle,
  normalizeInstitutionColor,
} from "@/lib/institution-theme";

const field =
  "h-10 w-full rounded-md border border-input bg-background px-3 text-sm shadow-sm focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20";
const LOGO_MAX_BYTES = 1024 * 1024;

function readLogo(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(new Error("Could not read the selected logo."));
    reader.readAsDataURL(file);
  });
}

function OnboardForm({ onDone }: { onDone: () => void | Promise<void> }) {
  const { notify } = useToast();
  const [name, setName] = useSessionStorageState(
    "super-admin-onboard-name",
    "",
    (value): value is string => typeof value === "string",
  );
  const [subdomain, setSubdomain] = useSessionStorageState(
    "super-admin-onboard-subdomain",
    "",
    (value): value is string => typeof value === "string",
  );
  const [plan, setPlan] = useSessionStorageState(
    "super-admin-onboard-plan",
    "free",
    (value): value is string => typeof value === "string",
  );
  const [adminName, setAdminName] = useState("");
  const [adminEmail, setAdminEmail] = useState("");
  const [adminPassword, setAdminPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);
  const [credentials, setCredentials] = useState<TemporaryCredentials | null>(null);
  const [logo, setLogo] = useState<File | null>(null);
  const [primaryColor, setPrimaryColor] = useState(DEFAULT_INSTITUTION_COLOR);
  const [createdLoginUrl, setCreatedLoginUrl] = useState<string | null>(null);
  const [catalogPickerOpen, setCatalogPickerOpen] = useState(false);
  const [catalogSubjectIds, setCatalogSubjectIds] = useState<string[]>([]);

  function generatePassword() {
    setAdminPassword(generateTemporaryPassword());
    setShowPassword(true);
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setOk(null);
    setCreatedLoginUrl(null);
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
      if (
        logo &&
        (!["image/png", "image/jpeg"].includes(logo.type) ||
          logo.size > LOGO_MAX_BYTES)
      ) {
        throw new Error("Logo must be a PNG or JPEG image no larger than 1 MB.");
      }
      const logoData = logo ? await readLogo(logo) : undefined;
      const slug = subdomain.trim().toLowerCase();
      const loginUrl = institutionLoginUrl(slug, window.location.origin);
      await onboardInstitution({
        name: name.trim(),
        subdomain: slug,
        plan_tier: plan,
        admin_full_name: adminName.trim() || undefined,
        admin_email: adminEmail.trim() || undefined,
        admin_password: adminPassword || undefined,
        logo_data: logoData,
        logo_content_type: logo?.type,
        logo_filename: logo?.name,
        primary_color: primaryColor,
        catalog_subject_ids: catalogSubjectIds,
      });
      setOk(
        `Created "${name.trim()}"${adminEmail.trim() ? ` with admin ${adminEmail.trim()}` : ""}.`,
      );
      if (adminEmail.trim() && adminPassword) {
        setCredentials({
          email: adminEmail.trim(),
          password: adminPassword,
          institution: name.trim(),
          loginUrl,
        });
      }
      notify(`Institution "${name.trim()}" created successfully.`, "success");
      setCreatedLoginUrl(loginUrl);
      setName("");
      setSubdomain("");
      setPlan("free");
      setAdminName("");
      setAdminEmail("");
      setAdminPassword("");
      setLogo(null);
      setPrimaryColor(DEFAULT_INSTITUTION_COLOR);
      setCatalogSubjectIds([]);
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
    <>
    <Card id="onboard" className="animate-rise scroll-mt-24">
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

          <label className="flex flex-col gap-1.5 text-sm font-medium">
            Institution logo (optional)
            <input
              key={logo ? `${logo.name}-${logo.size}` : "empty-logo"}
              className={`${field} h-auto py-2`}
              type="file"
              accept="image/png,image/jpeg"
              onChange={(event) => setLogo(event.target.files?.[0] ?? null)}
            />
            <span className="text-xs font-normal text-muted-foreground">
              PNG or JPEG, up to 1 MB. It appears above this institution&apos;s login form.
            </span>
          </label>

          <fieldset className="rounded-lg border border-dashed p-4">
            <legend className="px-1 text-sm font-medium">Institution theme</legend>
            <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
              <label className="flex flex-col gap-1.5 text-sm font-medium">
                Brand color
                <input
                  type="color"
                  value={normalizeInstitutionColor(primaryColor)}
                  onChange={(event) => setPrimaryColor(event.target.value.toUpperCase())}
                  className="h-10 w-16 cursor-pointer rounded-md border border-input bg-background p-1"
                  aria-label="Choose institution brand color"
                />
              </label>
              <label className="flex min-w-0 flex-1 flex-col gap-1.5 text-sm font-medium">
                Hex value
                <input
                  className={field}
                  value={primaryColor}
                  onChange={(event) => setPrimaryColor(event.target.value.toUpperCase())}
                  onBlur={() => setPrimaryColor(normalizeInstitutionColor(primaryColor))}
                  pattern="#[0-9A-Fa-f]{6}"
                  maxLength={7}
                />
              </label>
              <div
                className="flex h-10 min-w-36 items-center justify-center rounded-md px-4 text-sm font-semibold"
                style={{
                  ...institutionThemeStyle(primaryColor),
                  background: "var(--tenant-primary)",
                  color: "var(--tenant-on-primary)",
                }}
              >
                Theme preview
              </div>
            </div>
          </fieldset>

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

          <div className="rounded-lg border border-dashed p-4">
            <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-center">
              <div>
                <p className="text-sm font-semibold text-foreground">
                  Courses, levels and subjects offered (optional)
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  Select one or several courses now. The institution admin will only see the provisioned selections and can add more later.
                </p>
                {catalogSubjectIds.length > 0 && (
                  <p className="mt-2 text-sm font-medium text-primary">
                    {catalogSubjectIds.length} subject{catalogSubjectIds.length === 1 ? "" : "s"} selected
                  </p>
                )}
              </div>
              <Button
                type="button"
                variant="outline"
                onClick={() => setCatalogPickerOpen(true)}
              >
                <BookOpen size={16} className="mr-2" />
                {catalogSubjectIds.length > 0 ? "Edit selection" : "Select offerings"}
              </Button>
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
          {createdLoginUrl && (
            <div className="rounded-lg border border-primary/20 bg-primary/5 p-3 text-sm">
              <p className="font-medium">Institution login link</p>
              <div className="mt-2 flex flex-col gap-2 sm:flex-row sm:items-center">
                <a
                  className="min-w-0 break-all text-primary hover:underline"
                  href={createdLoginUrl}
                  target="_blank"
                  rel="noreferrer"
                >
                  {createdLoginUrl}
                </a>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => navigator.clipboard.writeText(createdLoginUrl)}
                >
                  <Copy size={14} className="mr-1.5" /> Copy
                </Button>
              </div>
            </div>
          )}

          <div>
            <Button type="submit" disabled={busy}>
              {busy ? "Onboarding…" : "Onboard institution"}
            </Button>
          </div>
        </form>
      </CardContent>
      {credentials && (
        <TemporaryCredentialsDialog
          credentials={credentials}
          onClose={() => setCredentials(null)}
        />
      )}
    </Card>
    {catalogPickerOpen && (
      <CatalogSubjectPicker
        title="Select institution offerings"
        confirmLabel="Use this selection"
        initialSelected={catalogSubjectIds}
        allowEmptySelection
        onClose={() => setCatalogPickerOpen(false)}
        onSelectionComplete={(subjectIds) => {
          setCatalogSubjectIds(subjectIds);
          setCatalogPickerOpen(false);
        }}
      />
    )}
    </>
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
  const [subdomain, setSubdomain] = useState(institution.subdomain ?? "");
  const [plan, setPlan] = useState(institution.plan_tier ?? "free");
  const [isActive, setIsActive] = useState(institution.is_active);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [logo, setLogo] = useState<File | null>(null);
  const [primaryColor, setPrimaryColor] = useState(
    normalizeInstitutionColor(institution.primary_color),
  );
  const selectedLogoUrl = useMemo(
    () => (logo ? URL.createObjectURL(logo) : null),
    [logo],
  );

  useEffect(() => {
    return () => {
      if (selectedLogoUrl) URL.revokeObjectURL(selectedLogoUrl);
    };
  }, [selectedLogoUrl]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!name.trim()) {
      setError("Institution name is required.");
      return;
    }
    const normalizedSubdomain = normalizeInstitutionSlug(subdomain);
    if (!normalizedSubdomain || normalizedSubdomain.length > 63) {
      setError(
        "Access URL must use lowercase letters, numbers, and single internal hyphens only.",
      );
      return;
    }
    setBusy(true);
    setError(null);
    try {
      if (
        logo &&
        (!["image/png", "image/jpeg"].includes(logo.type) ||
          logo.size > LOGO_MAX_BYTES)
      ) {
        throw new Error("Logo must be a PNG or JPEG image no larger than 1 MB.");
      }
      const logoData = logo ? await readLogo(logo) : undefined;
      await updateInstitution(institution.id, {
        name: name.trim(),
        subdomain: normalizedSubdomain,
        plan_tier: plan as "free" | "starter" | "growth" | "enterprise",
        is_active: isActive,
        logo_data: logoData,
        logo_content_type: logo?.type,
        logo_filename: logo?.name,
        primary_color: normalizeInstitutionColor(primaryColor),
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
      contentClassName="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-2xl border bg-card p-6 shadow-xl"
    >
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 id="edit-institution-title" className="text-lg font-semibold">
            Manage institution
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            {subdomain || institution.subdomain}
          </p>
        </div>
        <button onClick={onClose} aria-label="Close" className="rounded-md p-1 hover:bg-accent">
          <X size={18} />
        </button>
      </div>
      <form onSubmit={submit} className="mt-5 flex flex-col gap-4">
        <div
          className="rounded-xl border p-4"
          style={institutionThemeStyle(primaryColor)}
        >
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Current branding
          </p>
          <div className="mt-3 flex items-center gap-4">
            <div className="flex h-16 w-24 shrink-0 items-center justify-center overflow-hidden rounded-lg border bg-white p-2">
              {selectedLogoUrl || institution.logo_url ? (
                // Existing logos use short-lived signed URLs; selected files use a local preview URL.
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={selectedLogoUrl ?? institution.logo_url ?? ""}
                  alt={`${name || institution.name} logo preview`}
                  className="max-h-full max-w-full object-contain"
                />
              ) : (
                <span className="text-xs text-muted-foreground">No logo</span>
              )}
            </div>
            <div className="min-w-0">
              <p className="truncate font-semibold">{name || institution.name}</p>
              <p className="truncate text-xs text-muted-foreground">
                {subdomain || institution.subdomain}
              </p>
              <p className="mt-1 truncate text-xs text-muted-foreground">
                {logo?.name ?? institution.logo_filename ?? (institution.logo_url ? "Existing institution logo" : "No logo uploaded")}
              </p>
            </div>
          </div>
          <div
            className="mt-3 rounded-lg px-3 py-2 text-sm font-semibold text-primary-foreground"
            style={{ background: "var(--tenant-primary)" }}
          >
            Theme preview
          </div>
        </div>
        <label className="flex flex-col gap-1.5 text-sm font-medium">
          Institution name
          <input className={field} value={name} onChange={(event) => setName(event.target.value)} />
        </label>
        <label className="flex flex-col gap-1.5 text-sm font-medium">
          Access URL slug
          <input
            className={field}
            value={subdomain}
            onChange={(event) =>
              setSubdomain(
                event.target.value
                  .toLowerCase()
                  .replace(/\s+/g, "-")
                  .replace(/[^a-z0-9-]/g, "")
                  .replace(/-+/g, "-"),
              )
            }
            pattern="[a-z0-9]+(?:-[a-z0-9]+)*"
            maxLength={63}
            required
            autoCapitalize="none"
            autoCorrect="off"
            spellCheck={false}
            aria-describedby="institution-access-url-help"
          />
          <span
            id="institution-access-url-help"
            className="text-xs font-normal text-muted-foreground"
          >
            New link: /login/{normalizeInstitutionSlug(subdomain) || "your-institution"}.
            Changing this replaces the previously shared teacher and student login link.
          </span>
        </label>
        <fieldset className="rounded-lg border p-3">
          <legend className="px-1 text-sm font-medium">Institution theme</legend>
          <div className="flex items-end gap-3">
            <label className="flex flex-col gap-1.5 text-sm font-medium">
              Brand color
              <input
                type="color"
                value={normalizeInstitutionColor(primaryColor)}
                onChange={(event) => setPrimaryColor(event.target.value.toUpperCase())}
                className="h-10 w-16 cursor-pointer rounded-md border border-input bg-background p-1"
                aria-label="Choose institution brand color"
              />
            </label>
            <label className="flex min-w-0 flex-1 flex-col gap-1.5 text-sm font-medium">
              Hex value
              <input
                className={field}
                value={primaryColor}
                onChange={(event) => setPrimaryColor(event.target.value.toUpperCase())}
                onBlur={() => setPrimaryColor(normalizeInstitutionColor(primaryColor))}
                pattern="#[0-9A-Fa-f]{6}"
                maxLength={7}
                placeholder="#2E8857"
              />
            </label>
            <Button
              type="button"
              variant="outline"
              onClick={() => setPrimaryColor(DEFAULT_INSTITUTION_COLOR)}
            >
              Reset
            </Button>
          </div>
          <p className="mt-2 text-xs text-muted-foreground">
            Applied only to this institution&apos;s portal and tenant dashboards.
          </p>
        </fieldset>
        <label className="flex flex-col gap-1.5 text-sm font-medium">
          Replace institution logo
          <input
            className={`${field} h-auto py-2`}
            type="file"
            accept="image/png,image/jpeg"
            onChange={(event) => setLogo(event.target.files?.[0] ?? null)}
          />
          <span className="text-xs font-normal text-muted-foreground">
            PNG or JPEG, up to 1 MB.
          </span>
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
        actions={
          <div className="flex items-center gap-2">
            <Link
              href="#institution-directory"
              className="rounded-lg border border-input bg-card px-3 py-2 text-sm font-medium hover:bg-accent"
            >
              View directory
            </Link>
            <Link
              href="#onboard"
              className="rounded-lg bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
            >
              Add institution
            </Link>
          </div>
        }
      />

      <OnboardForm onDone={load} />

      <Card id="institution-directory" className="animate-rise scroll-mt-24">
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
                    <th className="px-2 py-2 font-medium">Courses</th>
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
                      <td className="px-2 py-2.5">
                        <div className="font-medium text-foreground">
                          {r.course_count}
                        </div>
                        <div
                          className="max-w-48 truncate text-xs text-muted-foreground"
                          title={r.courses.join(", ")}
                        >
                          {r.courses.length > 0
                            ? r.courses.join(", ")
                            : "No courses assigned"}
                        </div>
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
                        <div className="flex items-center justify-end gap-3 whitespace-nowrap">
                          {r.subdomain && (
                            <Link
                              href={`/login/${encodeURIComponent(r.subdomain)}`}
                              target="_blank"
                              className="text-xs font-medium text-primary hover:underline"
                            >
                              Login page
                            </Link>
                          )}
                          <button
                            onClick={() => setEditing(r)}
                            className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
                          >
                            <Pencil size={13} /> Manage
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

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
