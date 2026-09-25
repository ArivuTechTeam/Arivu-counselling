"use client";

import * as React from "react";
import Link from "next/link";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { StudentQuizzes } from "@/components/student/student-quizzes";
import {
  usePracticeSubjects,
  useStudentDaily,
  useStudentQuizzes,
} from "@/lib/student-queries";
import { countQuizActions } from "@/lib/student-dashboard-metrics";

// --- inline icons (lucide paths) ------------------------------------------
function Icon({ children }: { children: React.ReactNode }) {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {children}
    </svg>
  );
}
const FileIcon = () => (
  <Icon>
    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
    <path d="M14 2v6h6" />
  </Icon>
);
const RetryIcon = () => (
  <Icon>
    <path d="M3 11a9 9 0 1 1 2.6 6.4" />
    <path d="M3 4v7h7" />
  </Icon>
);
const TrophyIcon = () => (
  <Icon>
    <path d="M6 9H4.5a2.5 2.5 0 0 1 0-5H6" />
    <path d="M18 9h1.5a2.5 2.5 0 0 0 0-5H18" />
    <path d="M4 22h16" />
    <path d="M10 14.66V17c0 .55-.47.98-.97 1.21C7.85 18.75 7 20.24 7 22" />
    <path d="M14 14.66V17c0 .55.47.98.97 1.21C16.15 18.75 17 20.24 17 22" />
    <path d="M18 2H6v7a6 6 0 0 0 12 0V2Z" />
  </Icon>
);
const AlertIcon = () => (
  <Icon>
    <path d="m10.29 3.86-8.18 14.14A2 2 0 0 0 3.82 21h16.36a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
    <path d="M12 9v4" />
    <path d="M12 17h.01" />
  </Icon>
);

const BoltIcon = () => (
  <Icon>
    <path d="M13 2 3 14h9l-1 8 10-12h-9l1-8z" />
  </Icon>
);
const CalendarIcon = () => (
  <Icon>
    <rect x="3" y="4" width="18" height="18" rx="2" />
    <path d="M16 2v4M8 2v4M3 10h18" />
  </Icon>
);
const UsersIcon = () => (
  <Icon>
    <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
    <circle cx="9" cy="7" r="4" />
    <path d="M22 21v-2a4 4 0 0 0-3-3.87" />
    <path d="M16 3.13a4 4 0 0 1 0 7.75" />
  </Icon>
);
const BookmarkIcon = () => (
  <Icon>
    <path d="m19 21-7-4-7 4V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z" />
  </Icon>
);
const GridIcon = () => (
  <Icon>
    <rect x="3" y="3" width="7" height="7" />
    <rect x="14" y="3" width="7" height="7" />
    <rect x="14" y="14" width="7" height="7" />
    <rect x="3" y="14" width="7" height="7" />
  </Icon>
);

const FEATURES: {
  href: string;
  title: string;
  desc: string;
  chip: string;
  icon: React.ReactNode;
}[] = [
  {
    href: "/dashboard/student/practice",
    title: "Practice & Mock Tests",
    desc: "Focus on a topic or take a timed mock",
    chip: "bg-amber-500/10 text-amber-600",
    icon: <BoltIcon />,
  },
  {
    href: "/dashboard/student/daily",
    title: "Daily Challenge",
    desc: "Keep your streak alive",
    chip: "bg-emerald-500/10 text-emerald-600",
    icon: <CalendarIcon />,
  },
  {
    href: "/dashboard/student/challenge",
    title: "Challenge a Friend",
    desc: "Compete with classmates",
    chip: "bg-violet-500/10 text-violet-600",
    icon: <UsersIcon />,
  },
  {
    href: "/dashboard/student/revision",
    title: "Revision",
    desc: "Weak topics & saved questions",
    chip: "bg-blue-500/10 text-blue-600",
    icon: <BookmarkIcon />,
  },
  {
    href: "/dashboard/student/leaderboard",
    title: "Leaderboard",
    desc: "See where you rank",
    chip: "bg-amber-500/10 text-amber-600",
    icon: <TrophyIcon />,
  },
  {
    href: "/dashboard/student/subjects",
    title: "Take Quiz",
    desc: "Browse quizzes by subject",
    chip: "bg-brand-500/10 text-brand-600",
    icon: <GridIcon />,
  },
  {
    href: "/dashboard/student/weak-areas",
    title: "Weak Areas",
    desc: "Where to focus next",
    chip: "bg-rose-500/10 text-rose-500",
    icon: <AlertIcon />,
  },
];

function FeatureCard({
  href,
  title,
  desc,
  chip,
  icon,
}: {
  href: string;
  title: string;
  desc: string;
  chip: string;
  icon: React.ReactNode;
}) {
  return (
    <Link
      href={href}
      className="animate-rise flex items-start gap-3 rounded-xl border bg-card p-4 shadow-sm transition-all hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-md"
    >
      <span
        className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full ${chip}`}
      >
        {icon}
      </span>
      <span className="min-w-0">
        <span className="block text-sm font-semibold text-foreground">{title}</span>
        <span className="block text-xs text-muted-foreground">{desc}</span>
      </span>
    </Link>
  );
}

function MetricTile({
  label,
  value,
  gradient,
  chip,
  icon,
  href,
  delay = 0,
}: {
  label: string;
  value: string | number;
  gradient: string;
  chip: string;
  icon: React.ReactNode;
  href: string;
  delay?: number;
}) {
  return (
    <Link
      href={href}
      style={{ animationDelay: `${delay}ms` }}
      className={`animate-rise relative overflow-hidden rounded-2xl border bg-gradient-to-br ${gradient} p-5 shadow-sm transition-all hover:-translate-y-0.5 hover:shadow-md focus:outline-none focus:ring-2 focus:ring-primary/30`}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-[28px] font-bold leading-none tracking-tight text-foreground">
            {value}
          </div>
          <div className="mt-2 text-[11px] font-semibold uppercase tracking-widest text-muted-foreground">
            {label}
          </div>
        </div>
        <span
          className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full ${chip}`}
        >
          {icon}
        </span>
      </div>
      <span className="mt-3 inline-flex items-center gap-1 text-[11px] font-semibold text-primary/80">
        View →
      </span>
    </Link>
  );
}

export function StudentDashboard() {
  // Catalog, enrolled subjects and daily streak are actionable, and none can
  // mistake an early exit for completed work or a solved question.
  const quizQuery = useStudentQuizzes();
  const subjectsQuery = usePracticeSubjects();
  const dailyQuery = useStudentDaily();
  const quizActions = countQuizActions(quizQuery.data ?? []);

  return (
    <div className="flex flex-col gap-6">
      {/* Hero */}
      <div
        className="animate-rise relative overflow-hidden rounded-2xl p-6 text-white shadow-lg sm:p-8"
        style={{ background: "linear-gradient(135deg, var(--tenant-sidebar-start, #1a6942), var(--tenant-primary-dark, #15603d), var(--tenant-primary-deep, #0f4e33))" }}
      >
        <div className="pointer-events-none absolute -right-8 -top-10 h-40 w-40 rounded-full bg-white/10 blur-2xl" />
        <div className="pointer-events-none absolute -bottom-16 right-32 h-52 w-52 rounded-full bg-white/10 blur-3xl" />
        <div className="relative flex flex-wrap items-center justify-between gap-6">
          <div className="min-w-0 max-w-2xl">
            <p className="text-[11px] font-semibold uppercase tracking-widest text-white/70">
              Your next step
            </p>
            <h2 className="mt-2 text-2xl font-bold leading-tight sm:text-[28px]">
              Choose what to work on next
            </h2>
            <p className="mt-2 text-sm text-white/80">
              Find a new quiz, revisit one you started, or practise a subject at your own pace.
            </p>
            <div className="mt-5 flex flex-wrap gap-2">
              <Link href="#available" className="rounded-lg bg-white px-4 py-2 text-sm font-semibold text-primary shadow-sm hover:bg-white/90 focus:outline-none focus:ring-2 focus:ring-white/80">
                Browse quizzes
              </Link>
              <Link href="/dashboard/student/practice?mode=topic" className="rounded-lg border border-white/50 px-4 py-2 text-sm font-semibold text-white hover:bg-white/10 focus:outline-none focus:ring-2 focus:ring-white/80">
                Start topic practice
              </Link>
            </div>
          </div>
        </div>
      </div>

      {/* Actionable opportunities, not counts inferred from abandoned attempts. */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <MetricTile
          label="New quizzes"
          value={quizQuery.data ? quizActions.newQuizzes : "—"}
          gradient="from-card to-emerald-50/70"
          chip="bg-emerald-500/10 text-emerald-600"
          icon={<FileIcon />}
          href="#available"
          delay={0}
        />
        <MetricTile
          label="Quizzes to revisit"
          value={quizQuery.data ? quizActions.revisitQuizzes : "—"}
          gradient="from-card to-blue-50/70"
          chip="bg-blue-500/10 text-blue-600"
          icon={<RetryIcon />}
          href="#available"
          delay={60}
        />
        <MetricTile
          label="Subjects to practise"
          value={subjectsQuery.data ? subjectsQuery.data.length : "—"}
          gradient="from-card to-brand-50/70"
          chip="bg-brand-500/10 text-brand-600"
          icon={<GridIcon />}
          href="/dashboard/student/practice?mode=topic"
          delay={120}
        />
        <MetricTile
          label="Daily challenge streak"
          value={dailyQuery.data ? `${dailyQuery.data.streak} days` : "—"}
          gradient="from-card to-rose-50/70"
          chip="bg-rose-500/10 text-rose-500"
          icon={<CalendarIcon />}
          href="/dashboard/student/daily"
          delay={180}
        />
      </div>

      {(subjectsQuery.error || dailyQuery.error) && (
        <p className="text-sm text-muted-foreground" role="status">
          Some shortcuts are unavailable right now.{" "}
          <button type="button" className="font-medium text-primary underline" onClick={() => {
            if (subjectsQuery.error) void subjectsQuery.mutate();
            if (dailyQuery.error) void dailyQuery.mutate();
          }}>
            Try again
          </button>
        </p>
      )}

      {/* Quizzes to attend — third in the first-sight order */}
      <div id="available" className="scroll-mt-24">
        <StudentQuizzes />
      </div>

      {/* Practice launchpad — everything self-serve, one tap away */}
      <Card className="animate-rise">
        <CardHeader>
          <CardTitle>Practice &amp; compete</CardTitle>
          <CardDescription>
            Everything you need to prep — pick one and go.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {FEATURES.map((f) => (
            <FeatureCard key={f.href} {...f} />
          ))}
        </CardContent>
      </Card>

    </div>
  );
}
