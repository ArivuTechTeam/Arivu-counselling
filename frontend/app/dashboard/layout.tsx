"use client";

import { useEffect, useMemo, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { SWRConfig } from "swr";

import { DashboardShell } from "@/components/shared/dashboard-shell";
import { Brand } from "@/components/ui/brand";
import { Skeleton } from "@/components/ui/skeleton";
import { ToastProvider } from "@/components/ui/toast";
import { createClient } from "@/lib/supabase";
import { safeDashboardNext } from "@/lib/safe-next";

const HOME_BY_ROLE: Record<string, string> = {
  super_admin: "/dashboard/super-admin",
  institution_admin: "/dashboard/institution-admin",
  teacher: "/dashboard/teacher",
  student: "/dashboard/student",
};

/**
 * Wraps every /dashboard/* page in the ArivuPro shell (sidebar + topbar).
 * It reads the logged-in user's role to build the right sidebar nav.
 */
export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const [role, setRole] = useState<string | null>(null);
  const [email, setEmail] = useState("");
  const [mustChangePassword, setMustChangePassword] = useState(false);
  const [canChangePassword, setCanChangePassword] = useState(false);
  const cacheProvider = useMemo(() => () => new Map(), []);
  // `ready` gates the shell so we never flash a blank sidebar / "?" avatar
  // before the role resolves.
  const [ready, setReady] = useState(false);

  // Resolve the logged-in user's role once per dashboard mount. The browser
  // session is restored locally, then the RLS-protected profile row remains the
  // authoritative source for role-based navigation.
  useEffect(() => {
    let cancelled = false;
    const supabase = createClient();
    // The session lives in this tab's sessionStorage. Reading it here avoids a
    // blocking Auth-server round trip on every fresh dashboard mount. This is
    // only a UI bootstrap: the profile lookup below is still protected by RLS,
    // and every FastAPI endpoint independently verifies the bearer token and
    // authoritative role before returning data.
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
      setMustChangePassword(Boolean(user.user_metadata?.must_change_password));
      const providers = user.app_metadata?.providers;
      setCanChangePassword(
        Boolean(
          user.identities?.some((identity) => identity.provider === "email") ||
            (Array.isArray(providers) && providers.includes("email")) ||
            user.app_metadata?.provider === "email",
        ),
      );
      const { data } = await supabase
        .from("profiles")
        .select("role")
        .eq("id", user.id)
        .single();
      if (cancelled) return;
      if (!data) {
        // Logged in but no readable profile — return to sign in rather than
        // leaving the user on an indefinite dashboard loader.
        router.replace("/login");
        return;
      }
      const resolvedRole = (data.role as string) ?? "";
      if (!HOME_BY_ROLE[resolvedRole]) {
        router.replace("/login");
        return;
      }
      setRole(resolvedRole);
      setReady(true);
    });
    return () => {
      cancelled = true;
    };
    // Deliberately runs once per mount — role doesn't change mid-session.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Cheap, local-only guard: keeps the URL in sync with the resolved role
  // (e.g. a student who navigates to a teacher route gets sent home) on every
  // navigation, without any network calls.
  const allowedHome = role ? HOME_BY_ROLE[role] : undefined;
  const pathValid =
    !!allowedHome &&
    (pathname === "/dashboard" ||
      pathname === allowedHome ||
      pathname.startsWith(`${allowedHome}/`));

  useEffect(() => {
    if (ready && allowedHome && pathname === "/dashboard") {
      router.replace(allowedHome);
    } else if (ready && allowedHome && !pathValid) {
      router.replace(allowedHome);
    }
  }, [ready, allowedHome, pathValid, pathname, router]);

  if (!ready || !pathValid || pathname === "/dashboard") {
    return (
      <main className="flex min-h-screen flex-col items-center justify-center gap-6 p-4">
        <Brand height={40} />
        <Skeleton className="h-2 w-40 rounded-full" />
        <p className="text-sm text-muted-foreground">Loading your dashboard…</p>
      </main>
    );
  }

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
        <DashboardShell
          role={role}
          email={email}
          mustChangePassword={mustChangePassword}
          canChangePassword={canChangePassword}
        >
          {children}
        </DashboardShell>
      </ToastProvider>
    </SWRConfig>
  );
}
