"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Area,
  AreaChart,
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
import { ErrorCard } from "@/components/ui/error-card";
import { PageHeader } from "@/components/ui/page-header";
import {
  AdminQuizSet,
  InstitutionAnalytics,
  QualityFinding,
  getAdminQuizSets,
  getInstitutionAnalytics,
} from "@/lib/api";

import { QuizDrilldownModal } from "./_components/quiz-drilldown-modal";
import { QuizPerformanceModal } from "../quizzes/_components/quiz-performance-modal";

const BRAND = "#15603d";

const SEV: Record<
  QualityFinding["severity"],
  { label: string; color: string; chip: string }
> = {
  critical: { label: "Fix now", color: "#ff6b7a", chip: "bg-rose-100 text-rose-700" },
  warn: { label: "Improve", color: "#f5a623", chip: "bg-amber-100 text-amber-700" },
  good: { label: "Good", color: "#00a651", chip: "bg-emerald-100 text-emerald-700" },
  info: { label: "Note", color: "#6366f1", chip: "bg-indigo-100 text-indigo-700" },
};

function acc(pct: number) {
  return pct >= 70 ? "#00a651" : pct >= 40 ? "#f5a623" : "#ff6b7a";
}

function StatTile({
  label,
  value,
  color,
}: {
  label: string;
  value: number | string;
  color?: string;
}) {
  return (
    <Card className="animate-rise">
      <CardContent className="p-5">
        <div className="text-[26px] font-bold leading-none" style={{ color }}>
          {value}
        </div>
        <div className="mt-2 text-[11px] font-semibold uppercase tracking-widest text-muted-foreground">
          {label}
        </div>
      </CardContent>
    </Card>
  );
}

function FindingCard({ f }: { f: QualityFinding }) {
  const s = SEV[f.severity];
  return (
    <div
      className="animate-rise rounded-xl border bg-card p-4 shadow-sm"
      style={{ borderLeft: `3px solid ${s.color}` }}
    >
      <div className="flex items-start justify-between gap-3">
        <p className="font-semibold text-foreground">{f.title}</p>
        <span
          className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] font-semibold ${s.chip}`}
        >
          {s.label}
        </span>
      </div>
      <p className="mt-1.5 text-sm text-muted-foreground">{f.detail}</p>
      <div className="mt-3 flex items-start gap-2 rounded-lg bg-muted px-3 py-2 text-sm">
        <span className="font-semibold text-primary">Do this</span>
        <span className="text-foreground">{f.action}</span>
      </div>
    </div>
  );
}

/** Skeleton shown instantly while data loads — so the page never looks blank. */
function Skeleton() {
  return (
    <div className="flex animate-pulse flex-col gap-6">
      <div className="h-28 rounded-2xl bg-muted" />
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="h-24 rounded-xl bg-muted" />
        ))}
      </div>
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="h-28 rounded-xl bg-muted" />
        ))}
      </div>
      <div className="h-64 rounded-xl bg-muted" />
    </div>
  );
}

export default function InstitutionAnalyticsPage() {
  const [d, setD] = useState<InstitutionAnalytics | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [quizzes, setQuizzes] = useState<AdminQuizSet[]>([]);
  const [drilldown, setDrilldown] = useState<{ type: "course" | "teacher"; id: string; name: string } | null>(null);
  const [selectedQuiz, setSelectedQuiz] = useState<AdminQuizSet | null>(null);

  function load() {
    setLoading(true);
    Promise.all([getInstitutionAnalytics(), getAdminQuizSets()])
      .then(([analytics, quizRows]) => { setD(analytics); setQuizzes(quizRows); })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }
  useEffect(load, []);

  const drilldownQuizzes = useMemo(() => {
    if (!drilldown) return [];
    return quizzes
      .filter((quiz) => drilldown.type === "course" ? quiz.course_id === drilldown.id : quiz.teacher_id === drilldown.id)
      .sort((a, b) => b.attempts_count - a.attempts_count || a.avg_accuracy - b.avg_accuracy);
  }, [drilldown, quizzes]);

  if (error) {
    return (
      <div className="flex flex-col gap-6">
        <PageHeader
          title="Institution analytics"
          description="See performance trends, quality signals, and where your institution needs attention."
        />
        <ErrorCard message={error} onRetry={load} />
      </div>
    );
  }

  const sm = d?.summary;
  const trend = d?.trend;
  const findings = d?.findings ?? [];
  const updated = d?.updated_at ? new Date(d.updated_at) : null;
  const maxTeacher = Math.max(1, ...(d?.teacher_activity ?? []).map((t) => t.quiz_sets));

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Institution analytics"
        description="See performance trends, quality signals, and where your institution needs attention."
        actions={
          <div className="flex items-center gap-3">
            {updated && (
              <span className="text-xs text-muted-foreground">
                Updated{" "}
                {updated.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
              </span>
            )}
            <button
              onClick={load}
              disabled={loading}
              className="rounded-lg border border-input bg-card px-3 py-1.5 text-sm font-medium text-foreground shadow-sm transition-colors hover:bg-accent disabled:opacity-60"
            >
              {loading ? "Refreshing…" : "Refresh"}
            </button>
          </div>
        }
      />

      {d === null ? (
        <Skeleton />
      ) : (
        <>
          {/* Verdict hero */}
          <div className="animate-rise relative overflow-hidden rounded-2xl bg-gradient-to-br from-[#1a6942] via-[#15603d] to-[#0f4e33] p-6 text-white shadow-lg sm:p-8">
            <div className="pointer-events-none absolute -right-8 -top-10 h-40 w-40 rounded-full bg-white/10 blur-2xl" />
            <div className="relative flex flex-wrap items-center justify-between gap-6">
              <div className="min-w-0">
                <p className="text-[11px] font-semibold uppercase tracking-widest text-white/70">
                  Institution health
                </p>
                {(sm?.graded_attempts ?? 0) > 0 ? (
                  <>
                    <h2 className="mt-2 text-2xl font-bold leading-tight sm:text-[28px]">
                      <span className="text-[#9ff0a6]">{sm?.avg_accuracy ?? 0}%</span>{" "}
                      average accuracy across {sm?.students ?? 0} students.
                    </h2>
                    <p className="mt-2 text-sm text-white/80">
                      {sm!.active_week} active this week · {sm!.at_risk} at risk ·{" "}
                      {sm!.published_quizzes} quizzes published
                    </p>
                    {trend?.has_trend &&
                      trend.attempts_last7 + trend.attempts_prev7 >= 4 && (
                        <p className="mt-3 inline-flex items-center gap-1.5 rounded-full bg-white/10 px-3 py-1 text-xs font-medium">
                          {trend.delta >= 0 ? (
                            <span className="text-[#9ff0a6]">
                              ↑ +{trend.delta} attempts vs last week
                            </span>
                          ) : (
                            <span className="text-[#ffb4bc]">
                              ↓ {trend.delta} attempts vs last week
                            </span>
                          )}
                        </p>
                      )}
                  </>
                ) : (
                  <>
                    <h2 className="mt-2 text-2xl font-bold leading-tight sm:text-[28px]">
                      Getting started…
                    </h2>
                    <p className="mt-2 max-w-xl text-sm text-white/80">
                      {sm?.students ?? 0} students and {sm?.teachers ?? 0} teachers are
                      set up. Once students take quizzes, their outcomes and your
                      insights appear here.
                    </p>
                  </>
                )}
              </div>
              {(sm?.graded_attempts ?? 0) > 0 && (
                <div
                  className="relative flex h-28 w-28 shrink-0 items-center justify-center rounded-full transition-all duration-700 ease-out"
                  style={{
                    background: `conic-gradient(#7ae582 ${(sm?.avg_accuracy ?? 0) * 3.6}deg, rgba(255,255,255,0.16) 0deg)`,
                  }}
                >
                  <div className="flex h-[94px] w-[94px] flex-col items-center justify-center rounded-full bg-[#15603d]">
                    <span className="text-3xl font-bold">{sm?.avg_accuracy ?? 0}%</span>
                    <span className="text-[10px] uppercase tracking-widest text-white/70">
                      accuracy
                    </span>
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Stat tiles */}
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <StatTile label="Students" value={sm?.students ?? 0} />
            <StatTile label="Active this week" value={sm?.active_week ?? 0} />
            <StatTile
              label="At-risk students"
              value={sm?.at_risk ?? 0}
              color={(sm?.at_risk ?? 0) > 0 ? "#ff6b7a" : undefined}
            />
            <StatTile
              label="Avg accuracy"
              value={`${sm?.avg_accuracy ?? 0}%`}
              color={acc(sm?.avg_accuracy ?? 0)}
            />
          </div>

          {/* Findings */}
          <Card className="animate-rise">
            <CardHeader>
              <CardTitle>Key findings &amp; what to do</CardTitle>
              <CardDescription>
                Your data turned into actions. Work top to bottom — the most urgent
                items come first.
              </CardDescription>
            </CardHeader>
            <CardContent>
              {findings.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  Nothing to flag yet — as your institution gets busier, insights will
                  appear here.
                </p>
              ) : (
                <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
                  {findings.map((f, i) => (
                    <FindingCard key={i} f={f} />
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Engagement trend + at-risk */}
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
            <Card className="animate-rise lg:col-span-2">
              <CardHeader>
                <CardTitle>Quiz activity</CardTitle>
                <CardDescription>Graded attempts across the last 14 days.</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="h-56">
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart
                      data={d.activity}
                      margin={{ top: 8, right: 12, bottom: 0, left: -20 }}
                    >
                      <defs>
                        <linearGradient id="actFill" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor={BRAND} stopOpacity={0.28} />
                          <stop offset="100%" stopColor={BRAND} stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <XAxis dataKey="date" tick={{ fontSize: 11, fill: "#8b8b85" }} />
                      <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: "#8b8b85" }} />
                      <Tooltip />
                      <Area
                        type="monotone"
                        dataKey="attempts"
                        stroke={BRAND}
                        strokeWidth={2.5}
                        fill="url(#actFill)"
                        dot={{ r: 2.5, fill: BRAND }}
                      />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              </CardContent>
            </Card>

            <Card className="animate-rise lg:col-span-1" style={{ animationDelay: "60ms" }}>
              <CardHeader>
                <CardTitle>Students needing help</CardTitle>
                <CardDescription>Averaging below 40% — share with teachers.</CardDescription>
              </CardHeader>
              <CardContent className="flex flex-col gap-2">
                {d.at_risk_students.length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    No struggling students right now.
                  </p>
                ) : (
                  d.at_risk_students.map((s, i) => (
                    <div
                      key={i}
                      className="flex items-center justify-between rounded-lg border p-3 text-sm"
                    >
                      <span className="min-w-0 truncate text-foreground">{s.name}</span>
                      <span className="shrink-0 font-semibold" style={{ color: "#ff6b7a" }}>
                        {s.accuracy}%
                      </span>
                    </div>
                  ))
                )}
              </CardContent>
            </Card>
          </div>

          {/* Course performance */}
          <Card className="animate-rise">
            <CardHeader>
              <CardTitle>Course performance</CardTitle>
              <CardDescription>
                Enrolment, published quizzes and average accuracy per course.
              </CardDescription>
            </CardHeader>
            <CardContent>
              {d.course_perf.length === 0 ? (
                <p className="text-sm text-muted-foreground">No courses yet.</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b text-left text-xs uppercase tracking-wide text-muted-foreground">
                        <th className="px-2 py-2 font-medium">Course</th>
                        <th className="px-2 py-2 text-right font-medium">Students</th>
                        <th className="px-2 py-2 text-right font-medium">Published</th>
                        <th className="px-2 py-2 text-right font-medium">Attempts</th>
                        <th className="px-2 py-2 text-right font-medium">Accuracy</th>
                      </tr>
                    </thead>
                    <tbody>
                      {d.course_perf.map((c, i) => (
                        <tr
                          key={i}
                          role="button"
                          tabIndex={0}
                          className="cursor-pointer border-b transition hover:bg-accent focus:bg-accent focus:outline-none last:border-0"
                          onClick={() => setDrilldown({ type: "course", id: c.course_id, name: c.name })}
                          onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") setDrilldown({ type: "course", id: c.course_id, name: c.name }); }}
                        >
                          <td className="px-2 py-2.5 font-medium text-foreground">
                            {c.name}
                          </td>
                          <td className="px-2 py-2.5 text-right text-muted-foreground">
                            {c.students}
                          </td>
                          <td className="px-2 py-2.5 text-right text-muted-foreground">
                            {c.published}
                          </td>
                          <td className="px-2 py-2.5 text-right text-muted-foreground">
                            {c.attempts}
                          </td>
                          <td
                            className="px-2 py-2.5 text-right font-semibold"
                            style={{ color: c.attempts > 0 ? acc(c.accuracy) : "#94a3b8" }}
                          >
                            {c.attempts > 0 ? `${c.accuracy}%` : "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </CardContent>
          </Card>

          {/* Teacher activity */}
          <Card className="animate-rise">
            <CardHeader>
              <CardTitle>Teacher activity</CardTitle>
              <CardDescription>Who is creating and publishing content.</CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              {d.teacher_activity.length === 0 ? (
                <p className="text-sm text-muted-foreground">No teachers yet.</p>
              ) : (
                d.teacher_activity.map((tc, i) => (
                  <button key={i} type="button" onClick={() => setDrilldown({ type: "teacher", id: tc.teacher_id, name: tc.name })} className="flex flex-col gap-1 rounded-lg p-2 text-left transition hover:bg-accent">
                    <div className="flex items-center justify-between gap-3 text-sm">
                      <span className="truncate text-foreground">{tc.name}</span>
                      <span className="shrink-0 text-muted-foreground">
                        {tc.quiz_sets} set{tc.quiz_sets === 1 ? "" : "s"} · {tc.published}{" "}
                        published · {tc.attempts} attempts · {tc.attempts ? `${tc.accuracy}% accuracy` : "no attempts"}
                      </span>
                    </div>
                    <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
                      <div
                        className="h-full rounded-full bg-primary transition-[width] duration-700 ease-out"
                        style={{ width: `${(tc.quiz_sets / maxTeacher) * 100}%` }}
                      />
                    </div>
                  </button>
                ))
              )}
            </CardContent>
          </Card>

          {drilldown && (
            <QuizDrilldownModal
              title={`${drilldown.name} quizzes`}
              description={drilldown.type === "course" ? "Course quizzes sorted by engagement, then lowest accuracy." : "Teacher quizzes sorted by engagement, then lowest accuracy."}
              quizzes={drilldownQuizzes}
              onClose={() => setDrilldown(null)}
              onSelect={(quiz) => { setDrilldown(null); setSelectedQuiz(quiz); }}
            />
          )}
          {selectedQuiz && <QuizPerformanceModal quiz={selectedQuiz} onClose={() => setSelectedQuiz(null)} />}
        </>
      )}
    </div>
  );
}
