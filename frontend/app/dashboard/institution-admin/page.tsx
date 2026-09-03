"use client";

import { useEffect, useState } from "react";
import {
  Area,
  AreaChart,
  Cell,
  Pie,
  PieChart,
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
import {
  CheckIcon,
  GradIcon,
  HeroBanner,
  LayersIcon,
  MetricTile,
  UsersIcon,
  useCountUp,
} from "@/components/admin/dashboard-kit";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorCard } from "@/components/ui/error-card";
import { InstitutionOverview, getInstitutionOverview } from "@/lib/api";

const BRAND = "#15603d";
const ROLE_COLORS = ["#2e8857", "#7ae582", "#bbf7d0"]; // teachers, students, admins

function fmtDate(iso: string | null) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

const STATUS_TONE: Record<string, string> = {
  published: "bg-emerald-100 text-emerald-700",
  draft: "bg-amber-100 text-amber-700",
};

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

export default function InstitutionOverviewPage() {
  const [s, setS] = useState<InstitutionOverview | null>(null);
  const [error, setError] = useState<string | null>(null);

  function load() {
    setError(null);
    getInstitutionOverview()
      .then(setS)
      .catch((e) => setError(e.message));
  }
  useEffect(load, []);

  const ready = s !== null;
  const teachers = useCountUp(s?.teachers ?? 0, ready);
  const students = useCountUp(s?.students ?? 0, ready);
  const published = useCountUp(s?.published_quizzes ?? 0, ready);
  const attempts = useCountUp(s?.attempts ?? 0, ready);
  const accuracy = useCountUp(s?.accuracy ?? 0, ready);

  if (error) return <ErrorCard message={error} onRetry={load} />;

  if (s === null) {
    return (
      <div className="flex animate-pulse flex-col gap-6">
        <div className="h-32 rounded-2xl bg-muted" />
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-24 rounded-xl bg-muted" />
          ))}
        </div>
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          <div className="h-64 rounded-xl bg-muted lg:col-span-2" />
          <div className="h-64 rounded-xl bg-muted" />
        </div>
      </div>
    );
  }

  const roleData = [
    { name: "Teachers", value: s?.teachers ?? 0 },
    { name: "Students", value: s?.students ?? 0 },
    { name: "Admins", value: s?.admins ?? 0 },
  ].filter((r) => r.value > 0);
  const people = (s?.teachers ?? 0) + (s?.students ?? 0) + (s?.admins ?? 0);

  const topCourses = s?.top_courses ?? [];
  const maxCourse = Math.max(1, ...topCourses.map((c) => c.students));
  const recent = s?.recent_quiz_sets ?? [];

  return (
    <div className="flex flex-col gap-6">
      <HeroBanner
        eyebrow="Institution overview"
        title={
          <>
            <span className="text-[#9ff0a6]">{teachers}</span> teachers and{" "}
            <span className="text-[#9ff0a6]">{students}</span> students.
          </>
        }
        subtitle={`${plural(s?.courses ?? 0, "course")} · ${plural(
          s?.subjects ?? 0,
          "subject",
        )} · ${plural(s?.documents ?? 0, "document")}`}
        ring={{ value: `${accuracy}%`, label: "accuracy", pct: ready ? s!.accuracy : 0 }}
      />

      {/* Metric tiles */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <MetricTile
          label="Students"
          value={ready ? students : "—"}
          gradient="from-card to-emerald-50/70"
          chip="bg-emerald-500/10 text-emerald-600"
          icon={<GradIcon />}
          delay={0}
        />
        <MetricTile
          label="Teachers"
          value={ready ? teachers : "—"}
          gradient="from-card to-blue-50/70"
          chip="bg-blue-500/10 text-blue-600"
          icon={<UsersIcon />}
          delay={60}
        />
        <MetricTile
          label="Published quizzes"
          value={ready ? published : "—"}
          gradient="from-card to-brand-50/70"
          chip="bg-brand-500/10 text-brand-600"
          icon={<CheckIcon />}
          delay={120}
        />
        <MetricTile
          label="Quiz attempts"
          value={ready ? attempts : "—"}
          gradient="from-card to-amber-50/70"
          chip="bg-amber-500/10 text-amber-600"
          icon={<LayersIcon />}
          delay={180}
        />
      </div>

      {/* Activity trend + users by role */}
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
                  data={s?.activity ?? []}
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
            <CardTitle>People</CardTitle>
            <CardDescription>{people} accounts in your institution.</CardDescription>
          </CardHeader>
          <CardContent>
            {people === 0 ? (
              <EmptyState
                title="No users yet"
                message="Add teachers and students to see how your institution is made up."
              />
            ) : (
              <div className="flex items-center gap-4">
                <div className="h-36 w-36 shrink-0">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie
                        data={roleData}
                        dataKey="value"
                        nameKey="name"
                        innerRadius={38}
                        outerRadius={62}
                        paddingAngle={2}
                        stroke="none"
                      >
                        {roleData.map((_, i) => (
                          <Cell key={i} fill={ROLE_COLORS[i % ROLE_COLORS.length]} />
                        ))}
                      </Pie>
                      <Tooltip />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
                <div className="flex flex-col gap-2 text-sm">
                  {roleData.map((r, i) => (
                    <div key={r.name} className="flex items-center gap-2">
                      <span
                        className="h-3 w-3 rounded-full"
                        style={{ background: ROLE_COLORS[i % ROLE_COLORS.length] }}
                      />
                      <span className="text-muted-foreground">{r.name}</span>
                      <span className="ml-auto font-semibold text-foreground">
                        {r.value}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Recent quiz sets + top courses */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <Card className="animate-rise lg:col-span-2">
          <CardHeader>
            <CardTitle>Recent quiz sets</CardTitle>
            <CardDescription>The latest content created in your institution.</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            {recent.length === 0 ? (
              <EmptyState
                title="No quiz sets yet"
                message="Once your teachers create content, the newest quiz sets will show up here."
              />
            ) : (
              recent.map((q, i) => (
                <div
                  key={i}
                  className="flex items-center justify-between gap-3 rounded-lg border p-3"
                >
                  <span className="min-w-0 truncate text-sm font-medium text-foreground">
                    {q.title}
                  </span>
                  <span className="flex shrink-0 items-center gap-3">
                    <span className="text-xs text-muted-foreground">
                      {fmtDate(q.created_at)}
                    </span>
                    <span
                      className={`rounded-full px-2 py-0.5 text-xs font-medium capitalize ${
                        STATUS_TONE[q.status] ?? "bg-muted text-muted-foreground"
                      }`}
                    >
                      {q.status}
                    </span>
                  </span>
                </div>
              ))
            )}
          </CardContent>
        </Card>

        <Card className="animate-rise lg:col-span-1" style={{ animationDelay: "60ms" }}>
          <CardHeader>
            <CardTitle>Top courses</CardTitle>
            <CardDescription>By student enrolment.</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            {topCourses.length === 0 ? (
              <EmptyState
                title="No enrolments yet"
                message="As students enrol, your most popular courses will appear here."
              />
            ) : (
              topCourses.map((c) => (
                <div key={c.name} className="flex flex-col gap-1">
                  <div className="flex items-center justify-between gap-3 text-sm">
                    <span className="truncate text-foreground">{c.name}</span>
                    <span className="shrink-0 font-semibold text-muted-foreground">
                      {c.students}
                    </span>
                  </div>
                  <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
                    <div
                      className="h-full rounded-full bg-primary transition-[width] duration-700 ease-out"
                      style={{ width: `${(c.students / maxCourse) * 100}%` }}
                    />
                  </div>
                </div>
              ))
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
