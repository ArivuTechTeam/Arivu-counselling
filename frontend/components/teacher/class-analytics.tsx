"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorCard } from "@/components/ui/error-card";
import { Skeleton, SkeletonCards } from "@/components/ui/skeleton";
import {
  AttentionStudent,
} from "@/lib/api";
import { useTeacherOverview } from "@/lib/staff-queries";

function color(pct: number) {
  return pct >= 70 ? "#00a651" : pct >= 40 ? "#f5a623" : "#ff6b7a";
}

// Count a number up from 0 with an ease-out once `on` is true.
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

function StudentRow({ s }: { s: AttentionStudent }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-lg border p-3">
      <div className="flex min-w-0 items-center gap-3">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-semibold text-muted-foreground">
          {s.initials}
        </span>
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-foreground">{s.name}</p>
          <p className="truncate text-xs text-muted-foreground">{s.note}</p>
        </div>
      </div>
      <span
        className="shrink-0 text-sm font-semibold"
        style={{ color: color(s.accuracy) }}
      >
        {s.accuracy}%
      </span>
    </div>
  );
}

// Quizzes-taken-per-day over the last 14 days (zero-filled by the backend).
function ActivityTrendChart({
  data,
}: {
  data: { date: string; count: number }[];
}) {
  const max = Math.max(1, ...data.map((d) => d.count));
  const total = data.reduce((a, d) => a + d.count, 0);
  return (
    <Card className="animate-rise lg:col-span-2">
      <CardHeader>
        <CardTitle>Activity — last 14 days</CardTitle>
        <CardDescription>Quizzes taken by your students each day.</CardDescription>
      </CardHeader>
      <CardContent>
        {total === 0 ? (
          <EmptyState message="No quizzes taken in the last 14 days." />
        ) : (
          <div className="flex h-44 items-end gap-1.5">
            {data.map((d) => {
              const day = new Date(`${d.date}T00:00:00`);
              const h = d.count ? Math.max(6, Math.round((d.count / max) * 150)) : 2;
              return (
                <div
                  key={d.date}
                  className="group flex flex-1 flex-col items-center gap-1"
                >
                  <div
                    title={`${d.count} quiz${d.count === 1 ? "" : "zes"} taken · ${d.date}`}
                    className={`w-full rounded-t transition-all duration-500 ${
                      d.count ? "bg-primary/80 group-hover:bg-primary" : "bg-muted"
                    }`}
                    style={{ height: `${h}px` }}
                  />
                  <span className="text-[9px] leading-none text-muted-foreground">
                    {day.getDate()}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

const BAND_COLOR = ["bg-rose-500", "bg-amber-500", "bg-lime-500", "bg-emerald-500"];

// How graded attempts spread across score bands (0–40 … 80–100).
function ScoreDistributionChart({
  data,
}: {
  data: { label: string; count: number }[];
}) {
  const max = Math.max(1, ...data.map((d) => d.count));
  const total = data.reduce((a, d) => a + d.count, 0);
  return (
    <Card className="animate-rise" style={{ animationDelay: "60ms" }}>
      <CardHeader>
        <CardTitle>Score distribution</CardTitle>
        <CardDescription>How your graded attempts scored.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {total === 0 ? (
          <EmptyState message="No graded attempts yet." />
        ) : (
          data.map((d, i) => (
            <div key={d.label} className="flex items-center gap-3">
              <span className="w-14 shrink-0 text-xs font-medium text-muted-foreground">
                {d.label}%
              </span>
              <div className="h-3 flex-1 overflow-hidden rounded-full bg-muted">
                <div
                  className={`h-full rounded-full ${BAND_COLOR[i]} transition-all duration-700`}
                  style={{ width: `${Math.round((d.count / max) * 100)}%` }}
                />
              </div>
              <span className="w-6 shrink-0 text-right text-sm font-semibold text-foreground">
                {d.count}
              </span>
            </div>
          ))
        )}
      </CardContent>
    </Card>
  );
}

export function ClassAnalytics() {
  const router = useRouter();
  const { data = null, error, mutate } = useTeacherOverview();

  const loaded = data !== null;
  const quizzes = data?.accuracy_by_quiz ?? [];
  const attention = data?.needs_attention ?? [];
  const performers = data?.top_performers ?? [];
  const pipeline = data?.pipeline ?? {
    pending_review: 0,
    approved: 0,
    rejected: 0,
    needs_edit: 0,
  };
  const classAccuracy = data?.class_accuracy ?? 0;
  const students = data?.students ?? 0;
  const attempts = data?.total_attempts ?? 0;
  const atRisk = data?.at_risk ?? 0;
  const trend = data?.activity_trend ?? [];
  const distribution = data?.score_distribution ?? [];

  const accA = useCountUp(classAccuracy, loaded);
  const hasData = attempts > 0;

  if (error)
    return <ErrorCard message={error.message} onRetry={() => void mutate()} />;
  if (!loaded) {
    return (
      <div className="flex flex-col gap-6">
        <Skeleton className="h-32 w-full rounded-2xl" />
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          <Skeleton className="h-64 w-full rounded-2xl lg:col-span-2" />
          <Skeleton className="h-64 w-full rounded-2xl" />
        </div>
        <SkeletonCards count={2} />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      {/* Class performance summary */}
      <Card className="animate-rise overflow-hidden">
        <CardContent className="flex flex-wrap items-center gap-6 p-6">
          {/* accuracy ring */}
          <div
            className="relative flex h-24 w-24 shrink-0 items-center justify-center rounded-full transition-all duration-700 ease-out"
            style={{
              background: `conic-gradient(${color(classAccuracy)} ${
                (loaded ? classAccuracy : 0) * 3.6
              }deg, #eef1ee 0deg)`,
            }}
          >
            <div className="flex h-[76px] w-[76px] flex-col items-center justify-center rounded-full bg-card">
              <span className="text-xl font-bold text-foreground">{accA}%</span>
              <span className="text-[9px] uppercase tracking-widest text-muted-foreground">
                accuracy
              </span>
            </div>
          </div>

          <div className="min-w-0 flex-1">
            <h3 className="text-lg font-semibold text-foreground">
              Class performance
            </h3>
            <p className="mt-1 text-sm text-muted-foreground">
              {hasData
                ? `Across ${attempts} graded ${
                    attempts === 1 ? "quiz taken" : "quizzes taken"
                  } from ${students} ${students === 1 ? "student" : "students"}.`
                : "No graded quizzes yet — publish a quiz and your class results appear here."}
            </p>
          </div>

          {/* mini KPIs */}
          <div className="flex gap-6">
            <div className="text-center">
              <div className="text-2xl font-bold text-foreground">{students}</div>
              <div className="text-[11px] uppercase tracking-wide text-muted-foreground">
                students
              </div>
            </div>
            <div className="text-center">
              <div className="text-2xl font-bold text-foreground">{attempts}</div>
              <div className="text-[11px] uppercase tracking-wide text-muted-foreground">
                quizzes taken
              </div>
            </div>
            <div className="text-center">
              <div
                className="text-2xl font-bold"
                style={{ color: atRisk > 0 ? "#ff6b7a" : undefined }}
              >
                {atRisk}
              </div>
              <div className="text-[11px] uppercase tracking-wide text-muted-foreground">
                at risk
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Data-viz: activity trend + score distribution */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <ActivityTrendChart data={trend} />
        <ScoreDistributionChart data={distribution} />
      </div>

      {/* Accuracy by quiz + review pipeline */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <Card className="animate-rise lg:col-span-2">
          <CardHeader>
            <CardTitle>Class accuracy by quiz</CardTitle>
            <CardDescription>
              How students score on each quiz — click a quiz to open its review.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            {quizzes.length === 0 ? (
              <EmptyState message="No quizzes taken yet — once students take your published quizzes, their scores appear here." />
            ) : (
              quizzes.map((q) => (
                <button
                  key={q.set_id}
                  type="button"
                  onClick={() =>
                    router.push(`/dashboard/teacher/review/${q.set_id}`)
                  }
                  className="group flex flex-col gap-1 rounded-lg p-2 text-left transition-colors hover:bg-accent"
                >
                  <div className="flex items-center justify-between gap-3 text-sm">
                    <span className="truncate text-foreground group-hover:text-primary">
                      {q.title}
                    </span>
                    <span className="shrink-0 text-muted-foreground">
                      {q.accuracy}% · {q.attempts}{" "}
                      {q.attempts === 1 ? "quiz taken" : "quizzes taken"}
                    </span>
                  </div>
                  <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
                    <div
                      className="h-full rounded-full transition-[width] duration-700 ease-out"
                      style={{
                        width: `${q.accuracy}%`,
                        background: color(q.accuracy),
                      }}
                    />
                  </div>
                </button>
              ))
            )}
          </CardContent>
        </Card>

        {/* Review pipeline */}
        <Card className="animate-rise lg:col-span-1" style={{ animationDelay: "60ms" }}>
          <CardHeader>
            <CardTitle>Review status</CardTitle>
            <CardDescription>Your questions by status.</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            <button
              type="button"
              onClick={() => router.push("/dashboard/teacher/review")}
              className="flex items-center justify-between rounded-lg border border-amber-200 bg-amber-50 p-3 text-left transition-colors hover:bg-amber-100"
            >
              <span className="text-sm font-medium text-amber-800">
                Pending review
              </span>
              <span className="text-lg font-bold text-amber-700">
                {pipeline.pending_review}
              </span>
            </button>
            <button
              type="button"
              onClick={() => router.push("/dashboard/teacher/review")}
              className="flex items-center justify-between rounded-lg border border-orange-200 bg-orange-50 p-3 text-left transition-colors hover:bg-orange-100"
            >
              <span className="text-sm font-medium text-orange-800">Needs edit</span>
              <span className="text-lg font-bold text-orange-700">
                {pipeline.needs_edit}
              </span>
            </button>
            <div className="flex items-center justify-between rounded-lg border border-emerald-200 bg-emerald-50 p-3">
              <span className="text-sm font-medium text-emerald-800">Approved</span>
              <span className="text-lg font-bold text-emerald-700">
                {pipeline.approved}
              </span>
            </div>
            <div className="flex items-center justify-between rounded-lg border border-rose-200 bg-rose-50 p-3">
              <span className="text-sm font-medium text-rose-800">Rejected</span>
              <span className="text-lg font-bold text-rose-700">
                {pipeline.rejected}
              </span>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Needs attention + top performers */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card className="animate-rise">
          <CardHeader>
            <CardTitle>Needs attention</CardTitle>
            <CardDescription>Students scoring below 60%.</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            {attention.length === 0 ? (
              <EmptyState message="No students flagged — nice work." />
            ) : (
              attention.map((s, i) => <StudentRow key={i} s={s} />)
            )}
          </CardContent>
        </Card>

        <Card className="animate-rise" style={{ animationDelay: "60ms" }}>
          <CardHeader>
            <CardTitle>Top performers</CardTitle>
            <CardDescription>Your highest-scoring students.</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            {performers.length === 0 ? (
              <EmptyState message="No graded quizzes yet." />
            ) : (
              performers.map((s, i) => <StudentRow key={i} s={s} />)
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
