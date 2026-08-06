"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import { createClient } from "@/lib/supabase";

type NavItem = { label: string; href?: string; soon?: boolean };

// Role-based sidebar. Items with `href` are real (built). Items with `soon`
// are Phase 2/3 — shown as disabled "Soon" so the UI looks complete without
// pretending the feature works.
const NAV: Record<string, NavItem[]> = {
  teacher: [
    { label: "Dashboard", href: "/dashboard/teacher" },
    { label: "Analytics", soon: true },
  ],
  institution_admin: [
    { label: "Overview", href: "/dashboard/institution-admin" },
    { label: "Users", href: "/dashboard/institution-admin/users" },
    { label: "Courses & subjects", href: "/dashboard/institution-admin/courses" },
    { label: "Analytics", soon: true },
  ],
  super_admin: [
    { label: "Overview", href: "/dashboard/super-admin" },
    { label: "Courses & subjects", href: "/dashboard/super-admin/courses" },
    { label: "Analytics", soon: true },
  ],
  student: [
    { label: "Quizzes", href: "/dashboard/student" },
    { label: "Test history", soon: true },
    { label: "AI practice", soon: true },
    { label: "Adaptive drills", soon: true },
  ],
};

export function DashboardShell({
  role,
  email,
  children,
}: {
  role: string | null;
  email: string;
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const router = useRouter();

  const items = role ? NAV[role] ?? [] : [];
  // Pick the most specific matching nav item (longest href), so a parent like
  // "Overview" isn't highlighted while you're on a child route like "/users".
  const active = items
    .filter((i) => i.href && (pathname === i.href || pathname.startsWith(i.href + "/")))
    .sort((a, b) => (b.href?.length ?? 0) - (a.href?.length ?? 0))[0];
  const title = active?.label ?? "Dashboard";

  async function signOut() {
    const supabase = createClient();
    await supabase.auth.signOut();
    router.replace("/login");
  }

  return (
    <div className="flex min-h-screen bg-background">
      {/* Sidebar — the ArivuPro green gradient rail */}
      <aside className="hidden w-64 shrink-0 flex-col bg-gradient-to-b from-[#1a6942] to-[#15603d] p-4 text-white md:flex">
        <div className="mb-6 inline-flex w-fit rounded-xl bg-white px-3 py-2">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/arivu-logo.png" alt="ArivuPro Academy" className="h-6 w-auto" />
        </div>
        <div className="mb-2 px-2 text-[10px] font-semibold uppercase tracking-widest text-white/60">
          Workspace
        </div>
        <nav className="flex flex-col gap-1">
          {items.map((it) =>
            it.href ? (
              <Link
                key={it.label}
                href={it.href}
                className={`rounded-lg px-3 py-2 text-sm transition-colors ${
                  it.href === active?.href
                    ? "bg-white/[0.16] font-semibold shadow-glow"
                    : "text-white/85 hover:bg-white/10"
                }`}
              >
                {it.label}
              </Link>
            ) : (
              <span
                key={it.label}
                className="flex items-center justify-between rounded-lg px-3 py-2 text-sm text-white/50"
              >
                {it.label}
                <span className="rounded-full bg-white/15 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide">
                  Soon
                </span>
              </span>
            ),
          )}
        </nav>
        <button
          onClick={signOut}
          className="mt-auto rounded-lg px-3 py-2 text-left text-sm text-white/85 transition-colors hover:bg-white/10"
        >
          Sign out
        </button>
      </aside>

      {/* Main column */}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-10 flex h-16 items-center justify-between border-b bg-white px-6">
          <h1 className="text-lg font-semibold">{title}</h1>
          <div className="flex items-center gap-3 text-sm">
            <span className="text-muted-foreground">{email}</span>
            <span className="rounded-full bg-secondary px-2 py-0.5 text-xs font-medium capitalize">
              {role ? role.replace("_", " ") : ""}
            </span>
          </div>
        </header>
        <main className="flex-1 overflow-auto p-6">{children}</main>
      </div>
    </div>
  );
}
