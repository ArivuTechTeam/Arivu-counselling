"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { ErrorCard } from "@/components/ui/error-card";
import { Skeleton } from "@/components/ui/skeleton";
import { startExam } from "@/lib/api";
import { useStudentExamConfig } from "@/lib/student-queries";

function Stat({ value, label }: { value: string; label: string }) {
  return (
    <div className="rounded-xl bg-white/10 p-4 text-center">
      <div className="text-2xl font-extrabold">{value}</div>
      <div className="mt-1 text-[11px] uppercase tracking-widest text-white/60">
        {label}
      </div>
    </div>
  );
}

export function MockExamPanel() {
  const router = useRouter();
  const { data: cfg, error: loadError, mutate } = useStudentExamConfig();
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const penaltyLabel = !cfg || cfg.negative_marking === 0
    ? "None"
    : cfg.penalty_is_fraction
      ? `${cfg.negative_marking * 100}% of marks`
      : `−${cfg.negative_marking} marks`;
  const penaltyRule = !cfg || cfg.negative_marking === 0
    ? "Wrong answers do not have a negative-marking penalty."
    : cfg.penalty_is_fraction
      ? `A wrong answer can lose ${cfg.negative_marking * 100}% of that question's marks.`
      : `A wrong answer can lose ${cfg.negative_marking} marks.`;

  async function begin() {
    setBusy(true);
    setActionError(null);
    try {
      const { session_id } = await startExam();
      router.push(`/dashboard/student/practice/${session_id}`);
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Could not start the exam.");
      setBusy(false);
    }
  }

  if (loadError) {
    return (
      <div className="mx-auto flex max-w-3xl flex-col gap-6">
        <ErrorCard message={loadError.message} onRetry={() => void mutate()} />
      </div>
    );
  }

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-6">
      {/* Exam pattern */}
      <div
        className="animate-rise relative overflow-hidden rounded-2xl p-6 text-white shadow-lg sm:p-8"
        style={{ background: "linear-gradient(135deg, var(--tenant-sidebar-start, #1a6942), var(--tenant-primary-dark, #15603d), var(--tenant-primary-deep, #0f4e33))" }}
      >
        <div className="pointer-events-none absolute -right-10 -top-12 h-44 w-44 rounded-full bg-white/10 blur-2xl" />
        <p className="relative text-[11px] font-semibold uppercase tracking-widest text-white/70">
          {cfg?.active_session_id ? "Your active exam pattern" : "Today’s exam pattern"}
        </p>
        <div className="relative mt-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
          {cfg ? (
            <>
              <Stat value={String(cfg.questions)} label="Questions" />
              <Stat value={`${cfg.duration_minutes}m`} label="Time limit" />
              <Stat value={penaltyLabel} label="Wrong-answer penalty" />
            </>
          ) : (
            <>
              <Skeleton className="h-[86px] w-full rounded-xl bg-white/10" />
              <Skeleton className="h-[86px] w-full rounded-xl bg-white/10" />
              <Skeleton className="h-[86px] w-full rounded-xl bg-white/10" />
            </>
          )}
        </div>
      </div>

      {/* Rules */}
      <Card className="animate-rise">
        <CardHeader>
          <CardTitle>Before you begin</CardTitle>
          <CardDescription>Read these — the exam runs under real rules.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-2 text-sm">
          {cfg ? (
            [
              ["Timed", "The clock starts when you begin and keeps running if you refresh or close the tab. If it expires while closed, reopening it submits your saved work."],
              ["Complete every question", `Answer all ${cfg.questions} questions before submitting early. If time ends first, your last saved answers are graded.`],
              ["Question pacing", "The base guide is 45s for True/False, 60s for single choice, 75s for fill blank, 90s for multiple choice, and 120s for numerical. These guides scale to fit this exam's overall limit."],
              ["Marking", `${penaltyRule}${cfg.partial_credit ? " Multiple-response questions may receive partial credit." : ""}`],
              ["Leaving the exam", "Choosing another page ends and grades this attempt, including unanswered questions as zero. Refreshing restores the active exam with its original deadline; only one exam can be active at a time."],
            ].map(([t, d]) => (
              <div key={t} className="flex gap-3 rounded-lg border p-3">
                <span className="mt-0.5 h-2 w-2 shrink-0 rounded-full bg-primary" />
                <p>
                  <span className="font-semibold text-foreground">{t}.</span>{" "}
                  <span className="text-muted-foreground">{d}</span>
                </p>
              </div>
            ))
          ) : (
            <div className="flex flex-col gap-2">
              <Skeleton className="h-14 w-full rounded-lg" />
              <Skeleton className="h-14 w-full rounded-lg" />
              <Skeleton className="h-14 w-full rounded-lg" />
            </div>
          )}

          {actionError && (
            <p className="rounded-lg border border-destructive/20 bg-destructive/5 px-3 py-2 text-sm text-destructive">
              {actionError}
            </p>
          )}

          <div className="mt-2">
            <button
              onClick={begin}
              disabled={busy || !cfg}
              className="rounded-lg bg-primary px-6 py-3 text-sm font-bold text-primary-foreground shadow-sm transition-transform hover:-translate-y-0.5 hover:bg-primary/90 disabled:opacity-60"
            >
              {busy
                ? "Opening your exam…"
                : cfg?.active_session_id
                  ? "Continue active exam →"
                  : "Start the exam →"}
            </button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
