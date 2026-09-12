"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { ChangePasswordModal } from "@/components/shared/change-password-modal";
import { DevAccountSwitcher } from "@/components/shared/dev-account-switcher";
import { ThemeToggle } from "@/components/shared/theme-provider";
import {
  BarChart3,
  BookOpen,
  Building2,
  ChevronDown,
  Clock,
  FileText,
  LayoutDashboard,
  Menu,
  Plus,
  RefreshCw,
  Search,
  Sparkles,
  Trophy,
  UserCheck,
  Users,
  X,
  Zap,
} from "@/components/ui/icons";
import { deleteOwnAccount } from "@/lib/api";
import { createClient } from "@/lib/supabase";

type IconComponent = (p: { size?: number; className?: string }) => React.JSX.Element;

// `section` groups items under a header in the sidebar (presentation only —
// it doesn't affect which items a role can see).
type NavItem = {
  label: string;
  href?: string;
  soon?: boolean;
  section?: string;
  icon: IconComponent;
};

// Role-based sidebar. Items with `href` are real (built). Items with `soon`
// are Phase 2/3 — shown as disabled "Soon" so the UI looks complete without
// pretending the feature works.
const NAV: Record<string, NavItem[]> = {
  teacher: [
    {
      label: "Dashboard",
      href: "/dashboard/teacher",
      section: "Overview",
      icon: LayoutDashboard,
    },
    {
      label: "Subjects",
      href: "/dashboard/teacher/subjects",
      section: "Content",
      icon: BookOpen,
    },
    {
      label: "Generate quiz",
      href: "/dashboard/teacher/generate",
      section: "Content",
      icon: Plus,
    },
    {
      label: "Extract quiz",
      href: "/dashboard/teacher/extract",
      section: "Content",
      icon: Sparkles,
    },
    {
      label: "Review queue",
      href: "/dashboard/teacher/review",
      section: "Content",
      icon: FileText,
    },
    {
      label: "Document log",
      href: "/dashboard/teacher/documents",
      section: "Content",
      icon: Clock,
    },
    {
      label: "Class monitor",
      href: "/dashboard/teacher/class-monitor",
      section: "Monitoring",
      icon: BarChart3,
    },
  ],
  institution_admin: [
    {
      label: "Dashboard",
      href: "/dashboard/institution-admin",
      section: "Overview",
      icon: LayoutDashboard,
    },
    {
      label: "Teachers",
      href: "/dashboard/institution-admin/users",
      section: "Management",
      icon: Users,
    },
    {
      label: "Courses & subjects",
      href: "/dashboard/institution-admin/courses",
      section: "Management",
      icon: BookOpen,
    },
    {
      label: "Quizzes",
      href: "/dashboard/institution-admin/quizzes",
      section: "Management",
      icon: FileText,
    },
    {
      label: "Analytics",
      href: "/dashboard/institution-admin/analytics",
      section: "Analytics",
      icon: BarChart3,
    },
  ],
  super_admin: [
    {
      label: "Dashboard",
      href: "/dashboard/super-admin",
      section: "Overview",
      icon: LayoutDashboard,
    },
    {
      label: "Institutions",
      href: "/dashboard/super-admin/institutions",
      section: "Management",
      icon: Building2,
    },
    {
      label: "Institution Admins",
      href: "/dashboard/super-admin/admins",
      section: "Management",
      icon: Users,
    },
    {
      label: "Question Bank",
      href: "/dashboard/super-admin/courses",
      section: "Monitoring",
      icon: BookOpen,
    },
    {
      label: "Question Quality",
      href: "/dashboard/super-admin/ai-monitoring",
      section: "Monitoring",
      icon: Sparkles,
    },
  ],
  student: [
    { label: "Dashboard", href: "/dashboard/student", section: "Overview", icon: LayoutDashboard },
    {
      label: "Take Quiz",
      href: "/dashboard/student/subjects",
      section: "Overview",
      icon: BookOpen,
    },
    {
      label: "Smart Quiz",
      href: "/dashboard/student/smart-quiz",
      section: "Practice",
      icon: Zap,
    },
    {
      label: "Revision",
      href: "/dashboard/student/revision",
      section: "Practice",
      icon: RefreshCw,
    },
    {
      label: "Daily Challenge",
      href: "/dashboard/student/daily",
      section: "Practice",
      icon: Clock,
    },
    {
      label: "Challenge a Friend",
      href: "/dashboard/student/challenge",
      section: "Practice",
      icon: UserCheck,
    },
    {
      label: "Exam Simulator",
      href: "/dashboard/student/exam",
      section: "Practice",
      icon: FileText,
    },
    {
      label: "Leaderboard",
      href: "/dashboard/student/leaderboard",
      section: "Progress",
      icon: Trophy,
    },
    {
      label: "Quiz history",
      href: "/dashboard/student/history",
      section: "Progress",
      icon: BarChart3,
    },
  ],
};

// Groups consecutive items that share a `section` under one header.
function groupBySection(items: NavItem[]) {
  const groups: { section: string; items: NavItem[] }[] = [];
  for (const item of items) {
    const section = item.section ?? "Workspace";
    const last = groups[groups.length - 1];
    if (last && last.section === section) {
      last.items.push(item);
    } else {
      groups.push({ section, items: [item] });
    }
  }
  return groups;
}

// A single sidebar link (or disabled "Soon" row), shared by the flat and
// grouped rendering paths so the two stay visually identical.
function NavRow({
  item,
  active,
  onNavigate,
}: {
  item: NavItem;
  active: boolean;
  onNavigate: () => void;
}) {
  const Icon = item.icon;
  if (!item.href) {
    return (
      <span className="flex items-center gap-2 rounded-lg px-2.5 py-2 text-sm text-white/50">
        <Icon size={16} className="shrink-0" />
        <span className="flex-1">{item.label}</span>
        <span className="rounded-full bg-white/15 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-white/70">
          Soon
        </span>
      </span>
    );
  }
  return (
    <Link
      href={item.href}
      onClick={onNavigate}
      className={`flex items-center gap-2 rounded-lg px-2.5 py-2 text-sm transition-colors ${
        active
          ? "bg-white/[0.16] font-semibold text-white shadow-glow"
          : "text-white/85 hover:bg-white/10"
      }`}
    >
      <Icon size={16} className="shrink-0" />
      {item.label}
    </Link>
  );
}

export function DashboardShell({
  role,
  email,
  mustChangePassword = false,
  canChangePassword = true,
  children,
}: {
  role: string | null;
  email: string;
  mustChangePassword?: boolean;
  canChangePassword?: boolean;
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const [menuOpen, setMenuOpen] = useState(false);
  const [navOpen, setNavOpen] = useState(false);
  const [pwOpen, setPwOpen] = useState(false);
  const [pwDone, setPwDone] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteConfirmation, setDeleteConfirmation] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [navQuery, setNavQuery] = useState("");
  const [openSections, setOpenSections] = useState<Set<string>>(
    () =>
      new Set(
        (role ? NAV[role] ?? [] : []).map(
          (item) => item.section ?? "Workspace",
        ),
      ),
  );
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

  function toggleSection(section: string) {
    setOpenSections((prev) => {
      const next = new Set(prev);
      if (next.has(section)) next.delete(section);
      else next.add(section);
      return next;
    });
  }

  async function signOut() {
    const supabase = createClient();
    await supabase.auth.signOut({ scope: "local" });
    router.replace("/login");
  }

  async function deleteAccount() {
    if (deleteConfirmation !== "DELETE") return;
    setDeleting(true);
    setDeleteError(null);
    try {
      await deleteOwnAccount();
    } catch (error) {
      setDeleteError(
        error instanceof Error
          ? error.message
          : "Account deletion could not be completed. Please try again.",
      );
      setDeleting(false);
      return;
    }
    try {
      await createClient().auth.signOut({ scope: "local" });
    } finally {
      router.replace("/login?reason=account-deleted");
    }
  }

  const sections = groupBySection(items);
  // Search narrows each group down to matching items and drops groups left
  // with none, rather than just hiding non-matches in place — so a short
  // sidebar stays scannable instead of showing gaps.
  const query = navQuery.trim().toLowerCase();
  const filteredSections = query
    ? sections
        .map((group) => ({
          ...group,
          items: group.items.filter((it) => it.label.toLowerCase().includes(query)),
        }))
        .filter((group) => group.items.length > 0)
    : sections;

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      {/* Backdrop — dims the page behind the mobile drawer; tapping it closes
          the drawer. Only rendered below md:, since the sidebar is always
          in-flow (not a drawer) at md: and above. */}
      {navOpen && (
        <div
          className="fixed inset-0 z-20 bg-black/40 md:hidden"
          onClick={() => setNavOpen(false)}
        />
      )}

      {/* Sidebar — ArivuPro green gradient rail with per-item icons (fixed;
          never scrolls). Below md: it's a slide-in drawer (off-screen by
          default); at md: and above it's the original static in-flow rail. */}
      <aside
        className={`fixed inset-y-0 left-0 z-30 flex w-64 shrink-0 flex-col overflow-y-auto bg-gradient-to-b from-[#2E8857] to-[#245a41] p-4 text-white transition-transform duration-300 ease-in-out md:relative md:translate-x-0 ${
          navOpen ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="mb-4 flex w-full items-center justify-between gap-2">
          <div className="flex items-center gap-2 rounded-xl bg-white px-3 py-2.5 shadow-sm">
            <Image
              src="/arivu-logo.png"
              alt="ArivuPro Academy"
              width={134}
              height={26}
              className="h-[26px] w-auto shrink-0"
            />
            <span className="flex shrink-0 flex-col leading-none">
              <span className="text-[13px] font-extrabold tracking-tight text-[#2E8857]">
                Quiz
              </span>
              <span className="mt-0.5 text-[8px] font-bold uppercase tracking-[0.16em] text-[#245a41]/70">
                Platform
              </span>
            </span>
          </div>
          <button
            onClick={() => setNavOpen(false)}
            className="shrink-0 rounded-md p-1 text-white/80 hover:bg-white/10 md:hidden"
            aria-label="Close menu"
          >
            <X size={20} />
          </button>
        </div>

        {items.length > 0 && (
          <div className="relative mb-4 shrink-0">
            <Search
              size={16}
              className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-white/50"
            />
            <input
              type="text"
              value={navQuery}
              onChange={(e) => setNavQuery(e.target.value)}
              placeholder="Search"
              aria-label="Filter navigation"
              className="w-full rounded-lg bg-white/10 py-2 pl-9 pr-3 text-sm text-white placeholder:text-white/50 outline-none focus:bg-white/15"
            />
          </div>
        )}

        {filteredSections.length === 0 && (
          <p className="px-2 text-sm text-white/60">No matching items</p>
        )}

        {filteredSections.map((group, i) => {
            // While searching, force every matched group open — collapsing a
            // group would hide the very item the user just searched for.
            const isOpen = query.length > 0 || openSections.has(group.section);
            return (
              <div key={group.section} className={i === 0 ? "" : "mt-3"}>
                <button
                  type="button"
                  onClick={() => toggleSection(group.section)}
                  aria-expanded={isOpen}
                  className="mb-1.5 flex w-full items-center gap-2.5 rounded-lg px-2 py-2 text-sm font-semibold text-white transition-colors hover:bg-white/10"
                >
                  <span className="flex-1 text-left">{group.section}</span>
                  <ChevronDown
                    size={14}
                    className={`shrink-0 transition-transform ${isOpen ? "" : "-rotate-90"}`}
                  />
                </button>
                {isOpen && (
                  <nav className="ml-[13px] flex flex-col gap-1 border-l border-white/15 pl-4">
                    {group.items.map((it) => (
                      <NavRow
                        key={it.label}
                        item={it}
                        active={it.href === active?.href}
                        onNavigate={() => {
                          setNavOpen(false);
                          setNavQuery("");
                        }}
                      />
                    ))}
                  </nav>
                )}
              </div>
            );
          })}
      </aside>

      {/* Main column */}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-10 flex h-16 items-center justify-between border-b bg-card px-4 sm:px-6">
          <div className="flex items-center gap-3">
            <button
              onClick={() => setNavOpen(true)}
              className="rounded-md p-1.5 text-foreground hover:bg-accent md:hidden"
              aria-label="Open menu"
            >
              <Menu size={22} />
            </button>
            <h1 className="text-lg font-semibold">{title}</h1>
          </div>

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
                  {canChangePassword && (
                    <button
                      onClick={() => {
                        setMenuOpen(false);
                        setPwOpen(true);
                      }}
                      className="w-full border-b px-4 py-2.5 text-left text-sm font-medium text-foreground hover:bg-accent"
                    >
                      Change password
                    </button>
                  )}
                  <button
                    onClick={() => {
                      setMenuOpen(false);
                      setDeleteConfirmation("");
                      setDeleteError(null);
                      setDeleteOpen(true);
                    }}
                    className="w-full border-b px-4 py-2.5 text-left text-sm font-medium text-destructive hover:bg-accent"
                  >
                    Delete account
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
        <main className="flex-1 overflow-auto p-4 sm:p-6">{children}</main>
      </div>

      <ChangePasswordModal
        open={pwOpen && (canChangePassword || mustChangePassword)}
        forced={mustChangePassword && !pwDone}
        onClose={() => setPwOpen(false)}
        onDone={async () => {
          setPwDone(true);
          setPwOpen(false);
          // First-login accounts: re-authenticate with the new password for a
          // clean session. Their old token/state is stale, so staying in the
          // dashboard shows empty/error data — send them to sign in fresh.
          if (mustChangePassword) {
            try {
              await createClient().auth.signOut({ scope: "local" });
            } finally {
              router.replace("/login?reason=password-changed");
            }
          }
        }}
      />

      {deleteOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
          onClick={(event) => {
            if (event.target === event.currentTarget && !deleting) {
              setDeleteOpen(false);
            }
          }}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="delete-account-title"
            className="w-full max-w-md rounded-2xl border border-border bg-card p-6 shadow-2xl"
          >
            <h2 id="delete-account-title" className="text-lg font-bold text-foreground">
              Permanently delete account
            </h2>
            <p className="mt-2 text-sm text-muted-foreground">
              This removes your login, profile, enrolments, attempts, answers,
              bookmarks, revision state, activity events, and original uploaded
              files. Generated institution teaching content is retained without
              your name or account ID.
            </p>
            <label className="mt-5 flex flex-col gap-2 text-sm font-medium text-foreground">
              Type DELETE to confirm
              <input
                value={deleteConfirmation}
                onChange={(event) => setDeleteConfirmation(event.target.value)}
                disabled={deleting}
                autoComplete="off"
                className="h-10 rounded-lg border border-input bg-background px-3 outline-none focus:ring-2 focus:ring-ring disabled:opacity-50"
              />
            </label>
            {deleteError && (
              <p className="mt-3 text-sm text-destructive" role="alert">
                {deleteError}
              </p>
            )}
            <div className="mt-6 flex justify-end gap-2">
              <button
                type="button"
                disabled={deleting}
                onClick={() => setDeleteOpen(false)}
                className="rounded-lg border border-input px-4 py-2 text-sm font-semibold text-foreground hover:bg-secondary disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={deleting || deleteConfirmation !== "DELETE"}
                onClick={() => void deleteAccount()}
                className="rounded-lg bg-destructive px-4 py-2 text-sm font-semibold text-destructive-foreground hover:opacity-90 disabled:opacity-50"
              >
                {deleting ? "Deleting…" : "Delete permanently"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
