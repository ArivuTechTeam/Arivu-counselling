"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { DashboardShell } from "@/components/shared/dashboard-shell";
import { Brand } from "@/components/ui/brand";
import { Skeleton } from "@/components/ui/skeleton";
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
  const router = useRouter();
  const [role, setRole] = useState<string | null>(null);
  const [email, setEmail] = useState("");
  const [mustChangePassword, setMustChangePassword] = useState(false);
  // `ready` gates the shell so we never flash a blank sidebar / "?" avatar
  // before the role resolves.
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const supabase = createClient();
    supabase.auth.getUser().then(async ({ data: { user } }) => {
      if (!user) {
        // No session — send them to sign in rather than rendering an empty shell.
        router.replace("/login");
        return;
      }
      setEmail(user.email ?? "");
      setMustChangePassword(Boolean(user.user_metadata?.must_change_password));
      const { data } = await supabase
        .from("profiles")
        .select("role")
        .eq("id", user.id)
        .single();
      if (!data) {
        // Logged in but no profile — the dashboard router handles this case.
        router.replace("/login");
        return;
      }
      setRole((data.role as string) ?? null);
      setReady(true);
    });
  }, [router]);

  if (!ready) {
    return (
      <main className="flex min-h-screen flex-col items-center justify-center gap-6 p-4">
        <Brand height={40} />
        <Skeleton className="h-2 w-40 rounded-full" />
        <p className="text-sm text-muted-foreground">Loading your workspace…</p>
      </main>
    );
  }

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
