"use client";

import { useEffect, useState } from "react";

import { DashboardShell } from "@/components/dashboard-shell";
import { createClient } from "@/lib/supabase";

/**
 * Wraps every /dashboard/* page in the ArivuPro shell (sidebar + topbar).
 * It reads the logged-in user's role to build the right sidebar nav.
 */
export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const [role, setRole] = useState<string | null>(null);
  const [email, setEmail] = useState("");
  const [mustChangePassword, setMustChangePassword] = useState(false);

  useEffect(() => {
    const supabase = createClient();
    supabase.auth.getUser().then(async ({ data: { user } }) => {
      if (!user) return;
      setEmail(user.email ?? "");
      setMustChangePassword(Boolean(user.user_metadata?.must_change_password));
      const { data } = await supabase
        .from("profiles")
        .select("role")
        .eq("id", user.id)
        .single();
      setRole((data?.role as string) ?? null);
    });
  }, []);

  return (
    <DashboardShell
      role={role}
      email={email}
      mustChangePassword={mustChangePassword}
    >
      {children}
    </DashboardShell>
  );
}
