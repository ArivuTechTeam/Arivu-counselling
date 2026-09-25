"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import useSWR from "swr";

import { ChangePasswordForm } from "@/components/shared/change-password-form";
import { useDashboardIdentity } from "@/components/shared/dashboard-identity-context";
import { SupportInboxPanel } from "@/components/shared/support-inbox-panel";
import { StudentContactPanel } from "@/components/student/student-contact-panel";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { ErrorCard } from "@/components/ui/error-card";
import {
  AlertTriangle,
  BookOpen,
  Building2,
  Check,
  ShieldCheck,
  Trash,
} from "@/components/ui/icons";
import { Skeleton } from "@/components/ui/skeleton";
import { deleteOwnAccount, getAccountSettings } from "@/lib/api";
import { clearDashboardBootstrap } from "@/lib/dashboard-bootstrap";
import { institutionLoginPath } from "@/lib/institution-portal";
import { createClient } from "@/lib/supabase";

const ROLE_LABELS: Record<string, string> = {
  super_admin: "Super administrator",
  institution_admin: "Institution administrator",
  teacher: "Teacher",
  student: "Student",
};

export function AccountSettingsPage() {
  const router = useRouter();
  const { email, institution, canChangePassword } = useDashboardIdentity();
  const { data, error, mutate } = useSWR("account-settings", getAccountSettings);
  const [passwordChanged, setPasswordChanged] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteConfirmation, setDeleteConfirmation] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  async function deleteAccount() {
    if (deleteConfirmation !== "DELETE") return;
    setDeleting(true);
    setDeleteError(null);
    try {
      await deleteOwnAccount();
    } catch (caught) {
      setDeleteError(
        caught instanceof Error
          ? caught.message
          : "Account deletion could not be completed. Please try again.",
      );
      setDeleting(false);
      return;
    }
    try {
      await createClient().auth.signOut({ scope: "local" });
    } finally {
      clearDashboardBootstrap();
      router.replace(
        `${institutionLoginPath(institution?.subdomain ?? "")}?reason=account-deleted`,
      );
    }
  }

  if (error) {
    return (
      <ErrorCard
        title="We couldn't load your settings"
        message={error instanceof Error ? error.message : "Please try again."}
        onRetry={() => void mutate()}
      />
    );
  }

  if (!data) {
    return (
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-5" aria-busy="true">
        <Skeleton className="h-20 rounded-xl" />
        <Skeleton className="h-60 rounded-xl" />
        <Skeleton className="h-72 rounded-xl" />
      </div>
    );
  }

  const roleLabel = ROLE_LABELS[data.role] ?? data.role;
  const displayEmail = data.email ?? email;
  const academicLabel = data.role === "teacher" ? "Teaching assignments" : "Academic profile";

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
      <header>
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-primary">
          Account
        </p>
        <h1 className="mt-1 text-2xl font-bold text-foreground">Profile & settings</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Review your account details, academic access, and security controls.
        </p>
      </header>

      <Card>
        <CardHeader>
          <CardTitle className="text-xl">Profile</CardTitle>
          <CardDescription>Your identity and institution membership.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          <ProfileField label="Full name" value={data.full_name || "Not provided"} />
          <ProfileField label="Email address" value={displayEmail || "Not available"} />
          <ProfileField label="Role" value={roleLabel} />
          <ProfileField
            label="Sign-in method"
            value={canChangePassword ? "Email and password" : "Google or external provider"}
          />
          {institution && (
            <div className="flex gap-3 rounded-xl border bg-muted/20 p-4 sm:col-span-2">
              <span className="flex h-12 w-12 shrink-0 items-center justify-center overflow-hidden rounded-xl bg-background text-primary shadow-sm">
                {institution.logo_url ? (
                  // This is a short-lived signed URL from the private logo bucket.
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={institution.logo_url}
                    alt={`${institution.name} logo`}
                    className="h-full w-full object-contain p-1"
                  />
                ) : (
                  <Building2 size={24} />
                )}
              </span>
              <div className="min-w-0">
                <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Institution
                </p>
                <p className="mt-1 font-semibold text-foreground">{institution.name}</p>
                <Link
                  href={institutionLoginPath(institution.subdomain)}
                  className="mt-1 inline-block text-sm font-medium text-primary hover:underline"
                >
                  Open institution sign-in page
                </Link>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {(data.role === "student" || data.role === "teacher") && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-xl">
              <BookOpen size={20} className="text-primary" />
              {academicLabel}
            </CardTitle>
            <CardDescription>
              {data.role === "student"
                ? "Your course and level determine the subjects and quizzes available to you."
                : "These subjects are assigned by your institution administrator."}
            </CardDescription>
          </CardHeader>
          <CardContent>
            {data.academic_access.length === 0 ? (
              <div className="rounded-xl border border-dashed p-5 text-sm text-muted-foreground">
                {data.role === "student"
                  ? "No course or level is assigned yet. Contact your institution administrator."
                  : "No teaching subjects are assigned yet. Contact your institution administrator."}
              </div>
            ) : (
              <div className="grid gap-4 md:grid-cols-2">
                {data.academic_access.map((access, index) => (
                  <div
                    key={`${access.course}-${access.level ?? "all"}-${index}`}
                    className="rounded-xl border bg-muted/15 p-4"
                  >
                    <dl className="grid gap-3">
                      <div>
                        <dt className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                          Course
                        </dt>
                        <dd className="mt-1 font-semibold text-foreground">{access.course}</dd>
                      </div>
                      <div>
                        <dt className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                          Level
                        </dt>
                        <dd className="mt-1 text-sm text-foreground">
                          {access.level ?? "Not assigned"}
                        </dd>
                      </div>
                    </dl>
                    <div className="mt-4 border-t pt-3">
                      <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                        Subjects
                      </p>
                      {access.subjects.length > 0 ? (
                        <div className="mt-2 flex flex-wrap gap-2">
                          {access.subjects.map((subject) => (
                            <span
                              key={subject}
                              className="rounded-full bg-primary/10 px-2.5 py-1 text-xs font-medium text-primary"
                            >
                              {subject}
                            </span>
                          ))}
                        </div>
                      ) : (
                        <p className="mt-2 text-sm text-muted-foreground">No subjects available.</p>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {data.role === "student" && <StudentContactPanel institution={institution} />}
      {(data.role === "institution_admin" || data.role === "super_admin") && (
        <SupportInboxPanel role={data.role} institution={institution} />
      )}

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-xl">
            <ShieldCheck size={20} className="text-primary" />
            Security
          </CardTitle>
          <CardDescription>Manage how you sign in to this account.</CardDescription>
        </CardHeader>
        <CardContent>
          {canChangePassword ? (
            <div className="max-w-xl">
              {passwordChanged && (
                <div
                  className="mb-4 flex items-center gap-2 rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-800"
                  role="status"
                >
                  <Check size={15} />
                  Your password has been changed.
                </div>
              )}
              <ChangePasswordForm onDone={() => setPasswordChanged(true)} />
            </div>
          ) : (
            <div className="rounded-xl border bg-muted/20 p-4 text-sm text-muted-foreground">
              This account uses Google or another external sign-in provider. Manage its password with that provider.
            </div>
          )}
        </CardContent>
      </Card>

      <Card className="border-destructive/35">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-xl text-destructive">
            <AlertTriangle size={20} />
            Danger zone
          </CardTitle>
          <CardDescription>
            Account deletion is permanent and cannot be undone.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <p className="max-w-2xl text-sm text-muted-foreground">
            Delete your login, profile, assignments or enrolments, attempts, answers,
            bookmarks, revision state, and personal activity. Institution-owned teaching
            content is retained without your identity.
          </p>
          <Button
            type="button"
            variant="destructive"
            className="shrink-0"
            onClick={() => {
              setDeleteConfirmation("");
              setDeleteError(null);
              setDeleteOpen(true);
            }}
          >
            <Trash size={15} className="mr-1.5" />
            Delete account
          </Button>
        </CardContent>
      </Card>

      {deleteOpen && (
        <Dialog
          onClose={() => {
            if (!deleting) setDeleteOpen(false);
          }}
          closeOnBackdrop={!deleting}
          ariaLabelledBy="delete-account-title"
          contentClassName="w-full max-w-md rounded-2xl border border-border bg-card p-6 shadow-2xl"
        >
          <h2 id="delete-account-title" className="text-lg font-bold text-foreground">
            Permanently delete account
          </h2>
          <p className="mt-2 text-sm text-muted-foreground">
            This permanently removes your personal account data. Type DELETE to confirm.
          </p>
          <label className="mt-5 flex flex-col gap-2 text-sm font-medium text-foreground">
            Confirmation
            <input
              value={deleteConfirmation}
              onChange={(event) => setDeleteConfirmation(event.target.value)}
              disabled={deleting}
              autoComplete="off"
              className="h-10 rounded-lg border border-input bg-background px-3 outline-none focus:ring-2 focus:ring-ring disabled:opacity-50"
              placeholder="Type DELETE"
            />
          </label>
          {deleteError && (
            <p className="mt-3 text-sm text-destructive" role="alert">
              {deleteError}
            </p>
          )}
          <div className="mt-6 flex justify-end gap-2">
            <Button
              type="button"
              variant="outline"
              disabled={deleting}
              onClick={() => setDeleteOpen(false)}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant="destructive"
              disabled={deleting || deleteConfirmation !== "DELETE"}
              onClick={() => void deleteAccount()}
            >
              {deleting ? "Deleting…" : "Delete permanently"}
            </Button>
          </div>
        </Dialog>
      )}
    </div>
  );
}

function ProfileField({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border bg-muted/15 p-4">
      <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      <p className="mt-1 break-words font-medium text-foreground">{value}</p>
    </div>
  );
}
