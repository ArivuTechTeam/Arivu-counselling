"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { ChangePasswordModal } from "@/components/change-password-modal";
import { DevAccountSwitcher } from "@/components/dev-account-switcher";
import { ThemeToggle } from "@/components/theme-provider";
import { createClient } from "@/lib/supabase";

type NavItem = { label: string; href?: string; soon?: boolean };

// Role-based sidebar. Items with `href` are real (built). Items with `soon`
// are Phase 2/3 — shown as disabled "Soon" so the UI looks complete without
// pretending the feature works.
const NAV: Record<string, NavItem[]> = {
  teacher: [
    { label: "Class overview", href: "/dashboard/teacher" },
    { label: "Subjects", href: "/dashboard/teacher/subjects" },
    { label: "Generate quiz", href: "/dashboard/teacher/generate" },
    { label: "Review queue", href: "/dashboard/teacher/review" },
    { label: "Class monitor", href: "/dashboard/teacher/class-monitor" },
  ],
  institution_admin: [
    { label: "Overview", href: "/dashboard/institution-admin" },
    { label: "Users", href: "/dashboard/institution-admin/users" },
    { label: "Courses & subjects", href: "/dashboard/institution-admin/courses" },
    { label: "Quizzes", href: "/dashboard/institution-admin/quizzes" },
    { label: "Analytics", href: "/dashboard/institution-admin/analytics" },
  ],
  super_admin: [
    { label: "Overview", href: "/dashboard/super-admin" },
    { label: "Institutions", href: "/dashboard/super-admin/institutions" },
    { label: "Question Quality", href: "/dashboard/super-admin/ai-monitoring" },
  ],
  student: [
    { label: "Dashboard", href: "/dashboard/student" },
    { label: "Subjects", href: "/dashboard/student/subjects" },
    { label: "Smart Quiz", href: "/dashboard/student/smart-quiz" },
    { label: "Revision", href: "/dashboard/student/revision" },
    { label: "Daily Challenge", href: "/dashboard/student/daily" },
    { label: "Challenge a Friend", href: "/dashboard/student/challenge" },
    { label: "Exam Simulator", href: "/dashboard/student/exam" },
    { label: "Leaderboard", href: "/dashboard/student/leaderboard" },
    { label: "Test history", href: "/dashboard/student/history" },
  ],
};

export function DashboardShell({
  role,
  email,
  mustChangePassword = false,
  children,
}: {
  role: string | null;
  email: string;
  mustChangePassword?: boolean;
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const [menuOpen, setMenuOpen] = useState(false);
  const [pwOpen, setPwOpen] = useState(false);
  const [pwDone, setPwDone] = useState(false);
  const initial = (email?.[0] ?? "?").toUpperCase();

  // First-login security prompt: admin-created accounts still hold a temp
  // password the admin set — nudge them to replace it.
  useEffect(() => {
    if (mustChangePassword) setPwOpen(true);
  }, [mustChangePassword]);

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
    <div className="flex h-screen overflow-hidden bg-background">
      {/* Sidebar — the ArivuPro green gradient rail (fixed; never scrolls) */}
      <aside className="hidden w-64 shrink-0 flex-col overflow-y-auto bg-gradient-to-b from-[#2E8857] to-[#245a41] p-4 text-white md:flex">
        <div className="mb-6 flex w-full items-center justify-between gap-2 rounded-xl bg-white px-3 py-2.5 shadow-sm">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src="/arivu-logo.png"
            alt="ArivuPro Academy"
            className="h-[26px] w-auto shrink-0"
          />
          <span className="flex shrink-0 flex-col items-end leading-none">
            <span className="text-[13px] font-extrabold tracking-tight text-[#2E8857]">
              Quiz
            </span>
            <span className="mt-0.5 text-[8px] font-bold uppercase tracking-[0.16em] text-[#245a41]/70">
              Platform
            </span>
          </span>
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
      </aside>

      {/* Main column */}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-10 flex h-16 items-center justify-between border-b bg-card px-6">
          <h1 className="text-lg font-semibold">{title}</h1>

          <div className="flex items-center gap-3">
            <ThemeToggle />
            {/* Dev-only account switcher — stripped from production builds */}
            <DevAccountSwitcher currentEmail={email} />

            {/* Account avatar + dropdown (sign out lives here) */}
            <div className="relative">
            <button
              onClick={() => setMenuOpen((o) => !o)}
              className="flex items-center gap-2 rounded-full py-1 pl-1 pr-2 transition-colors hover:bg-accent"
              aria-label="Account menu"
            >
              <span className="flex h-8 w-8 items-center justify-center rounded-full bg-primary text-sm font-semibold text-primary-foreground">
                {initial}
              </span>
              <span className="hidden max-w-[180px] truncate text-sm text-muted-foreground sm:inline">
                {email}
              </span>
            </button>

            {menuOpen && (
              <>
                {/* click-away backdrop */}
                <div
                  className="fixed inset-0 z-20"
                  onClick={() => setMenuOpen(false)}
                />
                <div className="absolute right-0 top-full z-30 mt-2 w-60 overflow-hidden rounded-lg border bg-card shadow-lg">
                  <div className="border-b px-4 py-3">
                    <div className="truncate text-sm font-medium">{email}</div>
                    <div className="text-xs capitalize text-muted-foreground">
                      {role ? role.replace("_", " ") : ""}
                    </div>
                  </div>
                  <button
                    onClick={() => {
                      setMenuOpen(false);
                      setPwOpen(true);
                    }}
                    className="w-full border-b px-4 py-2.5 text-left text-sm font-medium text-foreground hover:bg-accent"
                  >
                    Change password
                  </button>
                  <button
                    onClick={signOut}
                    className="w-full px-4 py-2.5 text-left text-sm font-medium text-destructive hover:bg-accent"
                  >
                    Sign out
                  </button>
                </div>
              </>
            )}
            </div>
          </div>
        </header>
        <main className="flex-1 overflow-auto p-6">{children}</main>
      </div>

      <ChangePasswordModal
        open={pwOpen}
        forced={mustChangePassword && !pwDone}
        onClose={() => setPwOpen(false)}
        onDone={() => {
          setPwDone(true);
          setPwOpen(false);
        }}
      />
    </div>
  );
}
