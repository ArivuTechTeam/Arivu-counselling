"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { ChangePasswordModal } from "@/components/shared/change-password-modal";
import { DevAccountSwitcher } from "@/components/shared/dev-account-switcher";
import { useEscapeKey } from "@/components/ui/dialog";
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
  Settings,
  Sparkles,
  Trophy,
  UserCheck,
  Users,
  X,
  Zap,
} from "@/components/ui/icons";
import { type DashboardProfile } from "@/lib/api";
import {
  clearDashboardBootstrap,
  HOME_BY_ROLE,
  type DashboardRole,
} from "@/lib/dashboard-bootstrap";
import { createClient } from "@/lib/supabase";
import { useCourses } from "@/lib/staff-queries";
import { institutionLoginPath } from "@/lib/institution-portal";
import { institutionThemeStyle } from "@/lib/institution-theme";
import { useDashboardIdentity } from "@/components/shared/dashboard-identity-context";

type IconComponent = (p: { size?: number; className?: string }) => React.JSX.Element;

// `section` groups items under a header in the sidebar (presentation only —
// it doesn't affect which items a role can see).
type NavItem = {
  label: string;
  href?: string;
  soon?: boolean;
  section?: string;
  icon: IconComponent;
  feature?: keyof DashboardProfile["features"];
};

const PRIMARY_ACTION: Record<
  DashboardRole,
  { label: string; href: string }
> = {
  super_admin: {
    label: "Add institution",
    href: "/dashboard/super-admin/institutions#onboard",
  },
  institution_admin: {
    label: "Courses & subjects",
    href: "/dashboard/institution-admin/courses",
  },
  teacher: {
    label: "Create quiz",
    href: "/dashboard/teacher/generate",
  },
  student: {
    label: "Take quiz",
    href: "/dashboard/student/subjects",
  },
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
      label: "Create from material",
      href: "/dashboard/teacher/generate",
      section: "Content",
      icon: Plus,
    },
    {
      label: "Import existing quiz",
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
      label: "Paper bank",
      href: "/dashboard/teacher/paper-bank",
      section: "Content",
      icon: BookOpen,
      feature: "paper_bank",
    },
    {
      label: "Class monitor",
      href: "/dashboard/teacher/class-monitor",
      section: "Monitoring",
      icon: BarChart3,
    },
    {
      label: "Published quizzes",
      href: "/dashboard/teacher/published-quizzes",
      section: "Monitoring",
      icon: FileText,
    },
    {
      label: "Settings",
      href: "/dashboard/teacher/settings",
      section: "Account",
      icon: Settings,
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
      label: "Students",
      href: "/dashboard/institution-admin/students",
      section: "Management",
      icon: UserCheck,
    },
    {
      label: "Courses & subjects",
      href: "/dashboard/institution-admin/courses",
      section: "Management",
      icon: BookOpen,
    },
    {
      label: "Batches",
      href: "/dashboard/institution-admin/batches",
      section: "Management",
      icon: Users,
      feature: "batches",
    },
    {
      label: "Exam standards",
      href: "/dashboard/institution-admin/exam-standards",
      section: "Management",
      icon: BarChart3,
      feature: "scoring_policies",
    },
    {
      label: "Paper profiles",
      href: "/dashboard/institution-admin/paper-profiles",
      section: "Management",
      icon: BookOpen,
      feature: "commerce_pack",
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
    {
      label: "Settings",
      href: "/dashboard/institution-admin/settings",
      section: "Account",
      icon: Settings,
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
      label: "Question coverage",
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
    {
      label: "AI API logs",
      href: "/dashboard/super-admin/api-logs",
      section: "Monitoring",
      icon: BarChart3,
    },
    {
      label: "Settings",
      href: "/dashboard/super-admin/settings",
      section: "Account",
      icon: Settings,
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
      label: "Practice & Mock Tests",
      href: "/dashboard/student/practice",
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
      label: "Mock Test & PYQ",
      href: "/dashboard/student/pyq",
      section: "Practice",
      icon: FileText,
      feature: "paper_bank",
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
    {
      label: "Weak areas",
      href: "/dashboard/student/weak-areas",
      section: "Progress",
      icon: RefreshCw,
    },
    {
      label: "Settings",
      href: "/dashboard/student/settings",
      section: "Account",
      icon: Settings,
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
      aria-current={active ? "page" : undefined}
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

function InstitutionPrimaryAction() {
  const { data: courses, error } = useCourses();
  if (courses === undefined && !error) {
    return (
      <>
        <span
          aria-hidden="true"
          className="h-9 w-9 animate-pulse rounded-lg bg-muted sm:hidden"
        />
        <span
          aria-hidden="true"
          className="hidden h-9 w-28 animate-pulse rounded-lg bg-muted sm:inline-block"
        />
      </>
    );
  }
  const setupComplete = Boolean(
    courses?.length && courses.some((course) => course.subjects.length > 0),
  );
  const action = error
    ? {
        label: "Manage courses",
        href: "/dashboard/institution-admin/courses",
      }
    : setupComplete
    ? {
        label: "Add teacher",
        href: "/dashboard/institution-admin/users#add-teacher",
      }
    : {
        label: "Set up courses",
        href: "/dashboard/institution-admin/courses",
      };

  return (
    <>
      <Link
        href={action.href}
        aria-label={action.label}
        className="inline-flex h-9 w-9 items-center justify-center rounded-lg bg-primary text-primary-foreground shadow-sm transition-colors hover:bg-primary/90 sm:hidden"
      >
        <Plus size={17} />
      </Link>
      <Link
        href={action.href}
        className="hidden items-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-sm font-semibold text-primary-foreground shadow-sm transition-colors hover:bg-primary/90 sm:inline-flex"
      >
        <Plus size={16} />
        {action.label}
      </Link>
    </>
  );
}

export function DashboardShell({
  role,
  email,
  institution = null,
  mustChangePassword = false,
  children,
}: {
  role: string | null;
  email: string;
  institution?: DashboardProfile["institution"];
  mustChangePassword?: boolean;
  children: React.ReactNode;
}) {
  const { features } = useDashboardIdentity();
  const pathname = usePathname();
  const router = useRouter();
  const [menuOpen, setMenuOpen] = useState(false);
  const [navOpen, setNavOpen] = useState(false);
  const navRef = useRef<HTMLElement>(null);
  const navTriggerRef = useRef<HTMLButtonElement>(null);
  const [pwOpen, setPwOpen] = useState(false);
  const [pwDone, setPwDone] = useState(false);
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
  const tenantRole =
    role === "institution_admin" || role === "teacher" || role === "student";
  const tenantLogin = institutionLoginPath(institution?.subdomain ?? "");

  // First-login security prompt: admin-created accounts still hold a temp
  // password the admin set — nudge them to replace it.
  useEffect(() => {
    if (mustChangePassword) setPwOpen(true);
  }, [mustChangePassword]);

  // The progressive shell can mount before the profile role is available.
  // Open that role's sections when it arrives instead of leaving every group
  // collapsed from the initial role-less render.
  useEffect(() => {
    if (!role) return;
    setOpenSections(
      new Set((NAV[role] ?? []).map((item) => item.section ?? "Workspace")),
    );
  }, [role]);

  useEscapeKey(menuOpen, () => setMenuOpen(false));

  const closeNav = useCallback(() => setNavOpen(false), []);
  useEscapeKey(navOpen, closeNav);

  useEffect(() => {
    if (!navOpen) return;
    const nav = navRef.current;
    const navTrigger = navTriggerRef.current;
    if (!nav) return;

    const focusableSelector = [
      "a[href]",
      "button:not([disabled])",
      "input:not([disabled])",
      "[tabindex]:not([tabindex='-1'])",
    ].join(",");
    const getFocusable = () =>
      Array.from(nav.querySelectorAll<HTMLElement>(focusableSelector)).filter(
        (element) => element.getClientRects().length > 0,
      );
    getFocusable()[0]?.focus({ preventScroll: true });

    function trapFocus(event: KeyboardEvent) {
      if (event.key !== "Tab") return;
      const focusable = getFocusable();
      if (focusable.length === 0) {
        event.preventDefault();
        nav?.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", trapFocus);
    return () => {
      document.removeEventListener("keydown", trapFocus);
      navTrigger?.focus({ preventScroll: true });
    };
  }, [navOpen]);

  const items = role
    ? (NAV[role] ?? []).filter((item) => !item.feature || features[item.feature])
    : [];
  const dashboardRole = role && role in PRIMARY_ACTION
    ? (role as DashboardRole)
    : null;
  const primaryAction = dashboardRole ? PRIMARY_ACTION[dashboardRole] : null;
  const homeHref = dashboardRole ? HOME_BY_ROLE[dashboardRole] : "/dashboard";
  const navPathname = pathname.startsWith("/dashboard/student/attempt/") ||
    pathname.startsWith("/dashboard/student/practice/")
    ? "/dashboard/student/subjects"
    : pathname.startsWith("/dashboard/teacher/performance/")
      ? "/dashboard/teacher/published-quizzes"
      : pathname;
  // Pick the most specific matching nav item (longest href), so a parent like
  // "Overview" isn't highlighted while you're on a child route like "/users".
  const active = items
    .filter((i) => i.href && (navPathname === i.href || navPathname.startsWith(i.href + "/")))
    .sort((a, b) => (b.href?.length ?? 0) - (a.href?.length ?? 0))[0];
  const title = pathname.startsWith("/dashboard/student/attempt/")
    ? "Quiz attempt"
    : pathname.startsWith("/dashboard/student/practice/")
      ? "Quiz session"
      : pathname.startsWith("/dashboard/teacher/performance/")
        ? "Quiz performance"
        : active?.label ?? "Dashboard";

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
    clearDashboardBootstrap();
    await supabase.auth.signOut({ scope: "local" });
    router.replace(tenantLogin);
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
    <div
      className="flex h-screen overflow-hidden bg-background"
      style={tenantRole ? institutionThemeStyle(institution?.primary_color) : undefined}
    >
      <a
        href="#dashboard-main"
        className="fixed left-3 top-3 z-[60] -translate-y-20 rounded-md bg-background px-4 py-2 font-semibold text-foreground shadow-lg transition-transform focus:translate-y-0"
      >
        Skip to main content
      </a>
      {/* Backdrop — dims the page behind the mobile drawer; tapping it closes
          the drawer. Only rendered below md:, since the sidebar is always
          in-flow (not a drawer) at md: and above. */}
      {navOpen && (
        <button
          type="button"
          aria-label="Close navigation"
          className="fixed inset-0 z-20 bg-black/40 md:hidden"
          onClick={closeNav}
        />
      )}

      {/* Sidebar — ArivuPro green gradient rail with per-item icons (fixed;
          never scrolls). Below md: it's a slide-in drawer (off-screen by
          default); at md: and above it's the original static in-flow rail. */}
      <aside
        id="dashboard-navigation"
        ref={navRef}
        role={navOpen ? "dialog" : undefined}
        aria-modal={navOpen ? "true" : undefined}
        aria-label={navOpen ? "Dashboard navigation" : undefined}
        tabIndex={navOpen ? -1 : undefined}
        className={`fixed inset-y-0 left-0 z-30 flex w-64 shrink-0 flex-col overflow-y-auto p-4 text-white transition-transform duration-300 ease-in-out md:visible md:relative md:translate-x-0 ${
          navOpen ? "visible translate-x-0" : "invisible -translate-x-full"
        }`}
        style={{ background: "linear-gradient(to bottom, var(--tenant-sidebar-start, #2E8857), var(--tenant-primary-dark, #245a41))" }}
      >
        <div className="mb-4 flex w-full items-center justify-between gap-2">
          <Link
            href={homeHref}
            onClick={closeNav}
            aria-label={`Go to ${institution?.name ?? "dashboard"} home`}
            className="flex min-w-0 flex-1 items-center justify-center gap-2 rounded-xl bg-white px-3 py-2.5 shadow-sm transition hover:shadow-md"
          >
            {tenantRole ? (
              <span className="flex min-w-0 flex-col items-center gap-1.5 text-center">
                {institution?.logo_url ? (
                  <>
                    {/* The source is a short-lived URL from the private logo bucket. */}
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={institution.logo_url}
                      alt={`${institution.name} logo`}
                      className="max-h-9 max-w-[180px] object-contain"
                    />
                  </>
                ) : (
                  <Building2 size={25} className="text-primary" aria-hidden="true" />
                )}
                <span className="max-w-[190px] truncate text-xs font-bold text-primary">
                  {institution?.name ?? "Institution"}
                </span>
              </span>
            ) : (
              <>
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
              </>
            )}
          </Link>
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
              ref={navTriggerRef}
              onClick={() => setNavOpen(true)}
              className="rounded-md p-1.5 text-foreground hover:bg-accent md:hidden"
              aria-label="Open menu"
              aria-controls="dashboard-navigation"
              aria-expanded={navOpen}
            >
              <Menu size={22} />
            </button>
            <div className="min-w-0">
              <h1 className="text-lg font-semibold">{title}</h1>
              {tenantRole && institution?.name && (
                <p className="max-w-[44vw] truncate text-xs text-muted-foreground sm:max-w-none">
                  {institution.name}
                </p>
              )}
            </div>
          </div>

          <div className="flex items-center gap-3">
            {dashboardRole === "institution_admin" ? (
              <InstitutionPrimaryAction />
            ) : primaryAction ? (
              <>
                <Link
                  href={primaryAction.href}
                  aria-label={primaryAction.label}
                  className="inline-flex h-9 w-9 items-center justify-center rounded-lg bg-primary text-primary-foreground shadow-sm transition-colors hover:bg-primary/90 sm:hidden"
                >
                  <Plus size={17} />
                </Link>
                <Link
                  href={primaryAction.href}
                  className="hidden items-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-sm font-semibold text-primary-foreground shadow-sm transition-colors hover:bg-primary/90 sm:inline-flex"
                >
                  <Plus size={16} />
                  {primaryAction.label}
                </Link>
              </>
            ) : null}
            <ThemeToggle />
            {/* Dev-only account switcher — stripped from production builds */}
            <DevAccountSwitcher currentEmail={email} />

            {/* Account avatar + dropdown (sign out lives here) */}
            <div className="relative">
            <button
              onClick={() => setMenuOpen((o) => !o)}
              aria-expanded={menuOpen}
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
                  <Link
                    href={`${homeHref}/settings`}
                    onClick={() => setMenuOpen(false)}
                    className="block w-full border-b px-4 py-2.5 text-left text-sm font-medium text-foreground hover:bg-accent"
                  >
                    Profile & settings
                  </Link>
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
        <main id="dashboard-main" tabIndex={-1} className="flex-1 overflow-auto p-4 outline-none sm:p-6">{children}</main>
      </div>

      <ChangePasswordModal
        open={pwOpen && mustChangePassword}
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
              clearDashboardBootstrap();
              await createClient().auth.signOut({ scope: "local" });
            } finally {
              router.replace("/login?reason=password-changed");
            }
          }
        }}
      />
    </div>
  );
}
