"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

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
  const [message, setMessage] = useState("Loading your dashboard…");

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
        setMessage(
          "We couldn't find a profile for your account. Please contact your administrator.",
        );
        return;
      }

      const home = ROLE_HOME[profile.role as string];
      if (!home) {
        setMessage(`Unrecognized role: ${profile.role}`);
        return;
      }

      router.replace(home);
    }

    route();
  }, [router]);

  return (
    <main className="flex min-h-screen items-center justify-center p-4">
      <p className="text-sm text-muted-foreground">{message}</p>
    </main>
  );
}
