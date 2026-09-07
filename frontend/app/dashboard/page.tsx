"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { Brand } from "@/components/ui/brand";
import { ErrorCard } from "@/components/ui/error-card";
import { Skeleton } from "@/components/ui/skeleton";
import { createClient } from "@/lib/supabase";

// Maps each role (as stored in profiles.role) to its landing route.
const ROLE_HOME: Record<string, string> = {
  super_admin: "/dashboard/super-admin",
  institution_admin: "/dashboard/institution-admin",
  teacher: "/dashboard/teacher",
  student: "/dashboard/student",
};

/**
 * The dashboard "router". After login everyone lands here first. We:
 *   1. Confirm there is a logged-in user (else -> /login).
 *   2. Read their role from the profiles table (the source of truth).
 *   3. Redirect them to the dashboard for that role.
 */
export default function DashboardRouter() {
  const router = useRouter();
  const [error, setError] = useState<{ title: string; message: string } | null>(
    null,
  );

  useEffect(() => {
    async function route() {
      const supabase = createClient();

      const {
        data: { user },
      } = await supabase.auth.getUser();

      if (!user) {
        router.replace("/login");
        return;
      }

      // RLS lets a user read their own profile row.
      const { data: profile, error } = await supabase
        .from("profiles")
        .select("role")
        .eq("id", user.id)
        .single();

      if (error || !profile) {
        setError({
          title: "We couldn't load your profile",
          message:
            "We couldn't find a profile for your account. Please contact your administrator for help.",
        });
        return;
      }

      const home = ROLE_HOME[profile.role as string];
      if (!home) {
        setError({
          title: "Account not set up",
          message:
            "Your account hasn't been set up with a role yet. Please contact your administrator.",
        });
        return;
      }

      router.replace(home);
    }

    route();
  }, [router]);

  if (error) {
    return (
      <main className="flex min-h-screen items-center justify-center p-4">
        <div className="flex w-full max-w-md flex-col items-center gap-4">
          <ErrorCard title={error.title} message={error.message} />
          <Link
            href="/login"
            className="inline-flex items-center rounded-lg border border-input bg-card px-4 py-2 text-sm font-medium text-foreground shadow-sm transition-colors hover:bg-accent"
          >
            Back to sign in
          </Link>
        </div>
      </main>
    );
  }

  // First frame: branded loader while we resolve the user's role.
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-6 p-4">
      <Brand height={40} />
      <Skeleton className="h-2 w-40 rounded-full" />
      <p className="text-sm text-muted-foreground">Loading your dashboard…</p>
    </main>
  );
}
