"use client";

import * as React from "react";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { StudentQuizzes } from "@/components/student/student-quizzes";
import { ErrorCard } from "@/components/ui/error-card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  AttemptHistoryItem,
  StudentStats,
  getStudentStats,
  listStudentAttempts,
} from "@/lib/api";

const BRAND = "#15603d";

// Count a number up from 0 with an ease-out, once `on` becomes true.
function useCountUp(target: number, on: boolean, ms = 900) {
  const [v, setV] = useState(0);
  const raf = useRef<number>();
  useEffect(() => {
    if (!on) return;
    const start = performance.now();
    const tick = (t: number) => {
      const p = Math.min(1, (t - start) / ms);
      setV(Math.round(target * (1 - Math.pow(1 - p, 3))));
      if (p < 1) raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
    return () => {
      if (raf.current) cancelAnimationFrame(raf.current);
    };
  }, [target, on, ms]);
  return v;
}

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
const CheckIcon = () => (
  <Icon>
    <circle cx="12" cy="12" r="10" />
    <path d="m9 12 2 2 4-4" />
  </Icon>
);
const FileIcon = () => (
  <Icon>
    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
    <path d="M14 2v6h6" />
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
const ClockIcon = () => (
  <Icon>
    <circle cx="12" cy="12" r="10" />
    <path d="M12 6v6l4 2" />
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
    href: "/dashboard/student/smart-quiz",
    title: "Smart Quiz",
    desc: "Random questions, any time",
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
    href: "/dashboard/student/exam",
    title: "Exam Simulator",
    desc: "A full, timed mock",
    chip: "bg-rose-500/10 text-rose-500",
    icon: <ClockIcon />,
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
    title: "Subjects",
    desc: "Browse by chapter",
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
  delay = 0,
  onClick,
}: {
  label: string;
  value: string | number;
  gradient: string;
  chip: string;
  icon: React.ReactNode;
  delay?: number;
  onClick?: () => void;
}) {
  return (
    <div
      onClick={onClick}
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={
        onClick
          ? (e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onClick();
              }
            }
          : undefined
      }
      style={{ animationDelay: `${delay}ms` }}
      className={`animate-rise relative overflow-hidden rounded-2xl border bg-gradient-to-br ${gradient} p-5 shadow-sm transition-all hover:-translate-y-0.5 hover:shadow-md ${
        onClick
          ? "cursor-pointer focus:outline-none focus:ring-2 focus:ring-primary/30"
          : ""
      }`}
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
      {onClick && (
        <span className="mt-3 inline-flex items-center gap-1 text-[11px] font-semibold text-primary/80">
          View →
        </span>
      )}
    </div>
  );
}

function masteryColor(pct: number) {
  return pct >= 70
    ? "bg-accent-green"
    : pct >= 40
      ? "bg-accent-orange"
      : "bg-accent-pink";
}

export function StudentDashboard() {
  const router = useRouter();
  const [stats, setStats] = useState<StudentStats | null>(null);
  const [attempts, setAttempts] = useState<AttemptHistoryItem[]>([]);
  const [error, setError] = useState<string | null>(null);

  function load() {
    setError(null);
    Promise.all([getStudentStats(), listStudentAttempts()])
      .then(([s, a]) => {
        setStats(s);
        setAttempts(a);
      })
      .catch((e) =>
        setError(e instanceof Error ? e.message : "Could not load your dashboard."),
      );
  }

  useEffect(() => {
    load();
  }, []);

  const ready = stats !== null;
  const acc = stats?.overall_accuracy ?? 0;
  const solved = stats?.questions_solved ?? 0;
  const quizzes = stats?.quizzes_taken ?? 0;
  const weak = stats?.weak_areas.length ?? 0;

  const scrollToId = (id: string) =>
    document
      .getElementById(id)
      ?.scrollIntoView({ behavior: "smooth", block: "start" });

  const trend = [...attempts].reverse().map((a, i) => ({
    name: `#${i + 1}`,
    score:
      a.total_score != null && a.max_score
        ? Math.round((a.total_score / a.max_score) * 100)
        : 0,
  }));
  const best = trend.reduce((m, t) => Math.max(m, t.score), 0);

  const mastery = attempts
    .map((a) => ({
      id: a.attempt_id,
      title: a.quiz_title,
      pct:
        a.total_score != null && a.max_score
          ? Math.round((a.total_score / a.max_score) * 100)
          : 0,
    }))
    .sort((x, y) => y.pct - x.pct)
    .slice(0, 6);

  // animated numbers
  const accA = useCountUp(acc, ready);
  const solvedA = useCountUp(solved, ready);
  const quizzesA = useCountUp(quizzes, ready);
  const bestA = useCountUp(best, ready && attempts.length > 0);

  // Both fetches failed — show a retryable error instead of a zeroed dashboard.
  if (error) {
    return <ErrorCard message={error} onRetry={load} />;
  }

  // First paint before stats arrive — skeleton the hero + tile grid.
  if (!ready) {
    return (
      <div className="flex flex-col gap-6">
        <Skeleton className="h-44 w-full rounded-2xl sm:h-48" />
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-28 w-full rounded-2xl" />
          ))}
        </div>
        <Skeleton className="h-64 w-full rounded-2xl" />
      </div>
    );
  }

  // New students: onboard them straight into taking their first quiz.
  if (ready && quizzes === 0) {
    return (
      <div className="flex flex-col gap-6">
        <div className="animate-rise relative overflow-hidden rounded-2xl bg-gradient-to-br from-[#1a6942] via-[#15603d] to-[#0f4e33] p-8 text-white shadow-lg">
          <div className="pointer-events-none absolute -right-8 -top-10 h-40 w-40 rounded-full bg-white/10 blur-2xl" />
          <div className="pointer-events-none absolute -bottom-16 right-32 h-52 w-52 rounded-full bg-[#7ae582]/20 blur-3xl" />
          <div className="relative max-w-xl">
            <p className="text-[11px] font-semibold uppercase tracking-widest text-white/70">
              Welcome
            </p>
            <h2 className="mt-2 text-2xl font-bold leading-tight sm:text-[28px]">
              Start taking quizzes
            </h2>
            <p className="mt-3 text-sm text-white/80">
              Take your first quiz to unlock your progress dashboard — your
              accuracy, score trend, quiz mastery, and weak areas all appear here
              once you start.
            </p>
          </div>
        </div>
        <StudentQuizzes />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      {/* Hero */}
      <div className="animate-rise relative overflow-hidden rounded-2xl bg-gradient-to-br from-[#1a6942] via-[#15603d] to-[#0f4e33] p-6 text-white shadow-lg sm:p-8">
        <div className="pointer-events-none absolute -right-8 -top-10 h-40 w-40 rounded-full bg-white/10 blur-2xl" />
        <div className="pointer-events-none absolute -bottom-16 right-32 h-52 w-52 rounded-full bg-[#7ae582]/20 blur-3xl" />
        <div className="relative flex flex-wrap items-center justify-between gap-6">
          <div className="min-w-0">
            <p className="text-[11px] font-semibold uppercase tracking-widest text-white/70">
              Your progress
            </p>
            <h2 className="mt-2 text-2xl font-bold leading-tight sm:text-[28px]">
              You&apos;ve solved{" "}
              <span className="text-[#9ff0a6]">{solvedA}</span> questions across{" "}
              <span className="text-[#9ff0a6]">{quizzesA}</span> quizzes.
            </h2>
            <p className="mt-2 text-sm text-white/80">
              {weak > 0
                ? `Focus on your ${weak} weak ${weak === 1 ? "area" : "areas"} to lift your score.`
                : "Keep practising to build your mastery."}
            </p>
            {quizzes < 10 && (
              <div className="mt-4 max-w-xs">
                <div className="flex items-center justify-between text-[11px] text-white/70">
                  <span>{quizzes} of 10 quizzes</span>
                  <span>Keep going!</span>
                </div>
                <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-white/20">
                  <div
                    className="h-full rounded-full bg-[#9ff0a6] transition-[width] duration-700 ease-out"
                    style={{ width: `${Math.min(100, quizzes * 10)}%` }}
                  />
                </div>
              </div>
            )}
          </div>

          {/* accuracy ring */}
          <div
            className="relative flex h-28 w-28 shrink-0 items-center justify-center rounded-full transition-all duration-700 ease-out"
            style={{
              background: `conic-gradient(#7ae582 ${(ready ? acc : 0) * 3.6}deg, rgba(255,255,255,0.16) 0deg)`,
            }}
          >
            <div className="flex h-[94px] w-[94px] flex-col items-center justify-center rounded-full bg-[#15603d]">
              <span className="text-3xl font-bold">{accA}%</span>
              <span className="text-[10px] uppercase tracking-widest text-white/70">
                accuracy
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Metric tiles */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <MetricTile
          label="Questions solved"
          value={ready ? solvedA : "—"}
          gradient="from-card to-emerald-50/70"
          chip="bg-emerald-500/10 text-emerald-600"
          icon={<CheckIcon />}
          delay={0}
        />
        <MetricTile
          label="Quizzes taken"
          value={ready ? quizzesA : "—"}
          gradient="from-card to-blue-50/70"
          chip="bg-blue-500/10 text-blue-600"
          icon={<FileIcon />}
          delay={60}
          onClick={() => scrollToId("available")}
        />
        <MetricTile
          label="Best score"
          value={attempts.length ? `${bestA}%` : "—"}
          gradient="from-card to-brand-50/70"
          chip="bg-brand-500/10 text-brand-600"
          icon={<TrophyIcon />}
          delay={120}
          onClick={() => scrollToId("score-trend")}
        />
        <MetricTile
          label="Weak areas"
          value={ready ? weak : "—"}
          gradient="from-card to-rose-50/70"
          chip="bg-rose-500/10 text-rose-500"
          icon={<AlertIcon />}
          delay={180}
          onClick={() => router.push("/dashboard/student/weak-areas")}
        />
      </div>

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

      {/* Score trend area chart */}
      <Card id="score-trend" className="animate-rise scroll-mt-24">
        <CardHeader>
          <CardTitle>Score trend</CardTitle>
          <CardDescription>Your attempts over time (score %).</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="h-56">
            {trend.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No attempts yet — take a quiz to start your trend.
              </p>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart
                  data={trend}
                  margin={{ top: 8, right: 12, bottom: 0, left: -18 }}
                >
                  <defs>
                    <linearGradient id="scoreFill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={BRAND} stopOpacity={0.28} />
                      <stop offset="100%" stopColor={BRAND} stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#eee" />
                  <XAxis dataKey="name" tick={{ fontSize: 12, fill: "#8b8b85" }} />
                  <YAxis domain={[0, 100]} tick={{ fontSize: 12, fill: "#8b8b85" }} />
                  <Tooltip
                    contentStyle={{
                      borderRadius: 12,
                      border: "1px solid #e5e7eb",
                      boxShadow: "0 4px 16px rgba(0,0,0,0.08)",
                      fontSize: 12,
                    }}
                  />
                  <Area
                    type="monotone"
                    dataKey="score"
                    stroke={BRAND}
                    strokeWidth={2.5}
                    fill="url(#scoreFill)"
                    dot={{ r: 3, fill: BRAND }}
                  />
                </AreaChart>
              </ResponsiveContainer>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Quiz mastery */}
      <Card className="animate-rise">
        <CardHeader>
          <CardTitle>Quiz mastery</CardTitle>
          <CardDescription>
            Your best-performing quizzes — green is strong, red needs another go.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          {mastery.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Take a quiz to see how you&apos;re performing.
            </p>
          ) : (
            mastery.map((m) => (
              <div key={m.id} className="flex flex-col gap-1">
                <div className="flex items-center justify-between gap-3 text-sm">
                  <span className="truncate text-foreground">{m.title}</span>
                  <span className="shrink-0 font-semibold text-muted-foreground">
                    {m.pct}%
                  </span>
                </div>
                <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
                  <div
                    className={`h-full rounded-full transition-[width] duration-700 ease-out ${masteryColor(m.pct)}`}
                    style={{ width: ready ? `${m.pct}%` : "0%" }}
                  />
                </div>
              </div>
            ))
          )}
        </CardContent>
      </Card>
    </div>
  );
}
