"use client";

import { useEffect, useMemo, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { SWRConfig } from "swr";

import { DashboardShell } from "@/components/shared/dashboard-shell";
import { DashboardIdentityProvider } from "@/components/shared/dashboard-identity-context";
import { ExamShell } from "@/components/student/exam-shell";
import { ErrorCard } from "@/components/ui/error-card";
import { Skeleton } from "@/components/ui/skeleton";
import { ToastProvider } from "@/components/ui/toast";
import { getDashboardProfile, type DashboardProfile } from "@/lib/api";
import { createClient } from "@/lib/supabase";
import { safeDashboardNext } from "@/lib/safe-next";
import { isStudentExamPath } from "@/lib/student-exam";
import {
  clearDashboardBootstrap,
  dashboardContentState,
  HOME_BY_ROLE,
  isDashboardRole,
  type DashboardRole,
} from "@/lib/dashboard-bootstrap";

/**
 * Verify every dashboard role and tenant before rendering its page. Active
 * student attempts use a focused shell; other pages keep the full dashboard.
 */
export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const [role, setRole] = useState<DashboardRole | null>(null);
  const [email, setEmail] = useState("");
  const [institution, setInstitution] = useState<
    DashboardProfile["institution"]
  >(null);
  const [mustChangePassword, setMustChangePassword] = useState(false);
  const [canChangePassword, setCanChangePassword] = useState(false);
  const [features, setFeatures] = useState<DashboardProfile["features"]>({
    faculty_jobs: false,
    quiz_reuse: false,
    batches: false,
    scoring_policies: false,
    commerce_pack: false,
    figure_attach: false,
  });
  const [handwrittenEvaluationEnabled, setHandwrittenEvaluationEnabled] =
    useState(false);
  const [bootstrapError, setBootstrapError] = useState<string | null>(null);
  const [bootstrapAttempt, setBootstrapAttempt] = useState(0);
  const [sessionAvailable, setSessionAvailable] = useState(false);
  const cacheProvider = useMemo(() => () => new Map(), []);
  // `ready` gates role-specific page content until the backend verifies the
  // current role and tenant. A cached role must never make a page ready.
  const [ready, setReady] = useState(false);

  // Resolve the logged-in user's role once per dashboard mount. The browser
  // session is restored locally, then the authenticated backend loads the
  // authoritative profile and tenant identity for role-based navigation.
  useEffect(() => {
    let cancelled = false;
    setBootstrapError(null);
    setReady(false);
    setRole(null);
    const supabase = createClient();
    // The session lives in this tab's sessionStorage. Reading it here avoids a
    // blocking Auth-server round trip on every fresh dashboard mount. This is
    // only a UI bootstrap: the profile endpoint below verifies the bearer token
    // and loads the authoritative role and tenant before returning data.
    supabase.auth.getSession().then(async ({ data: { session } }) => {
      const user = session?.user;
      if (cancelled) return;
      if (!user) {
        // No session — send them to sign in rather than rendering an empty shell.
        const destination = safeDashboardNext(
          `${pathname}${window.location.search}`,
        );
        const next = destination === "/dashboard"
          ? ""
          : `?next=${encodeURIComponent(destination)}`;
        router.replace(`/login${next}`);
        return;
      }
      setEmail(user.email ?? "");
      setSessionAvailable(true);
      const providers = user.app_metadata?.providers;
      setCanChangePassword(
        Boolean(
          user.identities?.some((identity) => identity.provider === "email") ||
            (Array.isArray(providers) && providers.includes("email")) ||
            user.app_metadata?.provider === "email",
        ),
      );
      let data;
      try {
        data = await getDashboardProfile();
      } catch {
        if (!cancelled) {
          setBootstrapError(
            "We couldn't load your account profile. Check your connection and try again.",
          );
        }
        return;
      }
      if (cancelled) return;
      if (!data || !isDashboardRole(data.role)) {
        // Logged in but no readable profile — return to sign in rather than
        // leaving the user on an indefinite dashboard loader.
        clearDashboardBootstrap();
        await supabase.auth.signOut({ scope: "local" });
        router.replace("/login?reason=profile-unavailable");
        return;
      }
      const resolvedRole = data.role;
      const passwordChangeRequired = Boolean(data.must_change_password);
      setRole(resolvedRole);
      setMustChangePassword(passwordChangeRequired);
      setInstitution(data.institution);
      setFeatures(data.features);
      setHandwrittenEvaluationEnabled(data.handwritten_evaluation_enabled);
      setReady(true);
    });
    return () => {
      cancelled = true;
    };
    // A retry remounts only this bootstrap operation.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bootstrapAttempt]);

  // Cheap, local-only guard: keeps the URL in sync with the resolved role
  // (e.g. a student who navigates to a teacher route gets sent home) on every
  // navigation, without any network calls.
  const allowedHome = role ? HOME_BY_ROLE[role] : undefined;
  const pathValid =
    !!allowedHome &&
    (pathname === "/dashboard" ||
      pathname === allowedHome ||
      pathname.startsWith(`${allowedHome}/`));
  const contentState = dashboardContentState(
    ready,
    bootstrapError,
    pathValid,
    pathname,
  );

  useEffect(() => {
    if (ready && allowedHome && pathname === "/dashboard") {
      router.replace(allowedHome);
    } else if (ready && allowedHome && !pathValid) {
      router.replace(allowedHome);
    }
  }, [ready, allowedHome, pathValid, pathname, router]);

  // Keep tenant context visible while preserving the existing role-based route
  // tree. Authorization continues to use the authenticated profile above.
  useEffect(() => {
    if (!ready || role === "super_admin" || !institution?.subdomain) return;
    const url = new URL(window.location.href);
    if (url.searchParams.get("institution") === institution.subdomain) return;
    url.searchParams.set("institution", institution.subdomain);
    router.replace(`${url.pathname}${url.search}${url.hash}`, { scroll: false });
  }, [institution?.subdomain, pathname, ready, role, router]);

  if (!sessionAvailable) {
    return (
      <main className="flex min-h-screen flex-col items-center justify-center gap-6 p-4">
        <Skeleton className="h-2 w-40 rounded-full" />
        <p className="text-sm text-muted-foreground">Loading your dashboard…</p>
      </main>
    );
  }

  const content = contentState === "error" ? (
    <div className="mx-auto flex min-h-[60vh] max-w-md items-center">
      <ErrorCard
        title="We couldn't open your dashboard"
        message={bootstrapError ?? "Please try again."}
        onRetry={() => setBootstrapAttempt((attempt) => attempt + 1)}
        className="w-full"
      />
    </div>
  ) : contentState === "content" ? (
    children
  ) : (
    <div
      className="mx-auto flex min-h-[60vh] w-full max-w-5xl flex-col gap-6"
      aria-label="Loading dashboard"
      aria-busy="true"
    >
      <Skeleton className="h-32 w-full rounded-2xl" />
      <div className="grid gap-4 sm:grid-cols-3">
        <Skeleton className="h-24 rounded-xl" />
        <Skeleton className="h-24 rounded-xl" />
        <Skeleton className="h-24 rounded-xl" />
      </div>
      <Skeleton className="h-64 w-full rounded-xl" />
      <span className="sr-only">Loading your dashboard…</span>
    </div>
  );

  return (
    <SWRConfig
      value={{
        provider: cacheProvider,
        dedupingInterval: 60_000,
        revalidateOnFocus: false,
        keepPreviousData: true,
      }}
    >
      <ToastProvider>
        <DashboardIdentityProvider
          role={role}
          email={email}
          institution={institution}
          canChangePassword={canChangePassword}
          features={features}
          handwrittenEvaluationEnabled={handwrittenEvaluationEnabled}
        >
          {isStudentExamPath(pathname) && !mustChangePassword ? (
            <ExamShell institution={institution}>{content}</ExamShell>
          ) : (
            <DashboardShell
              role={role}
              email={email}
              institution={institution}
              mustChangePassword={mustChangePassword}
            >
              {content}
            </DashboardShell>
          )}
        </DashboardIdentityProvider>
      </ToastProvider>
    </SWRConfig>
  );
}
