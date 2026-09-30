"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  BarChart3,
  ChevronRight,
  ClipboardList,
  FileText,
  Inbox,
  RefreshCw,
  Upload,
} from "lucide-react";

import {
  attachHandwrittenAdditionalPages,
  type EvaluationSubmission,
  listStudentEvaluationSubmissions,
  retriggerHandwrittenEvaluation,
} from "@/lib/api";
import { ErrorCard } from "@/components/ui/error-card";
import { SkeletonList } from "@/components/ui/skeleton";

type Filter = "all" | "pending" | "evaluated" | "failed";

function normalizedStatus(submission: EvaluationSubmission): Exclude<Filter, "all"> {
  if (submission.report_available) return "evaluated";
  if (submission.status === "failed" || submission.status === "blocked_rubric_failed" || submission.job_status === "failed") return "failed";
  return "pending";
}

function statusLabel(submission: EvaluationSubmission): string {
  if (submission.report_available) return "Evaluated";
  if (submission.status === "blocked_rubric_failed") return "Waiting for paper rubric";
  if (normalizedStatus(submission) === "failed") return "Failed";
  if (submission.status === "review") return "Faculty review";
  return submission.job_status === "queued" || submission.job_status === "claimed"
    ? "Queued"
    : "Evaluating";
}

function StatusBadge({ submission }: { submission: EvaluationSubmission }) {
  const status = normalizedStatus(submission);
  const tone = status === "evaluated"
    ? "border-emerald-300 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950/35 dark:text-emerald-300"
    : status === "failed"
      ? "border-red-300 bg-red-50 text-red-700 dark:border-red-900 dark:bg-red-950/35 dark:text-red-300"
      : "border-amber-300 bg-amber-50 text-amber-700 dark:border-amber-900 dark:bg-amber-950/35 dark:text-amber-300";
  return <span className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-bold ${tone}`}><span className="h-1.5 w-1.5 rounded-full bg-current" />{statusLabel(submission)}</span>;
}

function ScoreRing({ submission }: { submission: EvaluationSubmission }) {
  if (submission.marks_obtained == null || submission.marks_possible == null) {
    return <span className="text-sm text-muted-foreground">—</span>;
  }
  const percentage = submission.percentage ?? (submission.marks_possible ? (submission.marks_obtained / submission.marks_possible) * 100 : 0);
  const clamped = Math.max(0, Math.min(100, Math.round(percentage)));
  const circumference = 2 * Math.PI * 22;
  const color = clamped >= 60 ? "#2E8857" : clamped >= 40 ? "#D97706" : "#DC2626";
  return (
    <div className="flex items-center gap-3">
      <div className="relative h-[54px] w-[54px] shrink-0">
        <svg width="54" height="54" className="-rotate-90"><circle cx="27" cy="27" r="22" fill="none" stroke="hsl(var(--border))" strokeWidth="5" /><circle cx="27" cy="27" r="22" fill="none" stroke={color} strokeWidth="5" strokeDasharray={`${(clamped / 100) * circumference} ${circumference}`} strokeLinecap="round" /></svg>
        <span className="absolute inset-0 grid place-items-center text-[11px] font-black" style={{ color }}>{clamped}%</span>
      </div>
      <div><p className="font-extrabold leading-none">{submission.marks_obtained}<span className="text-xs font-normal text-muted-foreground">/{submission.marks_possible}</span></p><p className="mt-1 text-xs text-muted-foreground">marks</p></div>
    </div>
  );
}

function EvaluationTabs() {
  return (
    <nav className="flex flex-wrap gap-2" aria-label="Handwritten evaluation">
      <Link href="/dashboard/student/handwritten-evaluation" className="rounded-full border bg-card px-4 py-2 text-sm font-semibold text-muted-foreground transition hover:border-primary/40 hover:text-primary">Exam Papers</Link>
      <Link href="/dashboard/student/handwritten-evaluation/submissions" className="rounded-full bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground">My Submissions</Link>
    </nav>
  );
}

export function HandwrittenSubmissions() {
  const [submissions, setSubmissions] = useState<EvaluationSubmission[]>([]);
  const [filter, setFilter] = useState<Filter>("all");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [actionId, setActionId] = useState<string | null>(null);

  const load = useCallback(async (silent = false) => {
    if (silent) setRefreshing(true); else setLoading(true);
    try {
      setSubmissions(await listStudentEvaluationSubmissions());
      setError(null);
    } catch (reason) {
      if (!silent) setError(reason instanceof Error ? reason.message : "Couldn't load your submissions.");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);
  const hasInFlight = submissions.some((submission) => normalizedStatus(submission) === "pending");
  useEffect(() => {
    if (!hasInFlight) return;
    const timer = window.setInterval(() => { if (document.visibilityState === "visible") void load(true); }, 5000);
    return () => window.clearInterval(timer);
  }, [hasInFlight, load]);

  const counts = useMemo(() => ({
    all: submissions.length,
    pending: submissions.filter((submission) => normalizedStatus(submission) === "pending").length,
    evaluated: submissions.filter((submission) => normalizedStatus(submission) === "evaluated").length,
    failed: submissions.filter((submission) => normalizedStatus(submission) === "failed").length,
  }), [submissions]);
  const filtered = filter === "all" ? submissions : submissions.filter((submission) => normalizedStatus(submission) === filter);

  function mergeSubmission(next: EvaluationSubmission) {
    setSubmissions((current) => {
      const exists = current.some((row) => row.id === next.id);
      return exists
        ? current.map((row) => row.id === next.id ? next : row)
        : [next, ...current];
    });
  }

  async function retrigger(submission: EvaluationSubmission) {
    setActionId(submission.id);
    setError(null);
    try {
      mergeSubmission(await retriggerHandwrittenEvaluation(submission.id));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The evaluation could not be restarted.");
    } finally {
      setActionId(null);
    }
  }

  async function addPages(submission: EvaluationSubmission, file: File | null) {
    if (!file) return;
    setActionId(submission.id);
    setError(null);
    try {
      mergeSubmission(await attachHandwrittenAdditionalPages(submission, file));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The additional pages could not be attached.");
    } finally {
      setActionId(null);
    }
  }

  return (
    <div className="mx-auto w-full max-w-[1440px] space-y-6">
      <section className="relative overflow-hidden rounded-3xl bg-primary px-6 py-7 text-primary-foreground shadow-lg sm:px-8">
        <div className="absolute -right-12 -top-20 h-52 w-52 rounded-full bg-white/5" />
        <div className="relative flex flex-col gap-5 lg:flex-row lg:items-center lg:justify-between">
          <div><h1 className="text-3xl font-black tracking-tight">My Submissions</h1><p className="mt-1 text-sm text-white/75">Track and review all your submitted answer scripts.</p></div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-xl border border-white/20 bg-white/10 px-4 py-2 text-sm"><strong className="mr-1 text-lg">{counts.all}</strong> Total</span>
            <span className="rounded-xl border border-white/20 bg-white/10 px-4 py-2 text-sm"><strong className="mr-1 text-lg">{counts.evaluated}</strong> Evaluated</span>
            <button type="button" onClick={() => void load()} disabled={refreshing} className="grid h-11 w-11 place-items-center rounded-xl border border-white/20 bg-white/10 hover:bg-white/15" aria-label="Refresh submissions"><RefreshCw size={16} className={refreshing ? "animate-spin" : ""} /></button>
            <Link href="/dashboard/student/handwritten-evaluation" className="inline-flex min-h-11 items-center gap-2 rounded-xl bg-white px-4 text-sm font-bold text-primary shadow-sm"><Upload size={15} /> Upload New</Link>
          </div>
        </div>
      </section>

      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between"><EvaluationTabs /><div className="flex max-w-full gap-2 overflow-x-auto pb-1">{(["all", "pending", "evaluated", "failed"] as Filter[]).map((item) => <button key={item} type="button" onClick={() => setFilter(item)} className={`shrink-0 rounded-full px-4 py-2 text-sm font-semibold capitalize ${filter === item ? "bg-primary text-primary-foreground" : "border bg-card text-muted-foreground hover:border-primary/35 hover:text-primary"}`}>{item}<span className={`ml-2 rounded-full px-1.5 py-0.5 text-xs ${filter === item ? "bg-white/20" : "bg-muted"}`}>{counts[item]}</span></button>)}</div></div>

      {error ? <ErrorCard title="We couldn't load your submissions" message={error} onRetry={() => void load()} /> : null}
      {loading ? <SkeletonList rows={4} /> : filtered.length === 0 && !error ? (
        <div className="rounded-2xl border bg-card px-6 py-16 text-center"><span className="mx-auto grid h-16 w-16 place-items-center rounded-full bg-primary/10 text-primary"><Inbox size={28} /></span><h2 className="mt-4 text-lg font-bold">{filter === "all" ? "No submissions yet" : `No ${filter} submissions`}</h2><p className="mt-1 text-sm text-muted-foreground">{filter === "all" ? "Attempt an exam paper and upload your handwritten answer script." : "Choose a different filter to see other submissions."}</p></div>
      ) : (
        <div className="space-y-3">
          {filtered.map((submission) => (
            <article key={submission.id} className="grid gap-4 rounded-2xl border bg-card p-5 shadow-sm transition hover:border-primary/30 hover:shadow-md md:grid-cols-[minmax(0,2fr)_minmax(140px,0.8fr)_minmax(160px,0.9fr)_minmax(160px,1fr)_auto] md:items-center">
              <div className="flex min-w-0 items-start gap-3"><span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-primary/20 bg-primary/10 text-primary"><FileText size={18} /></span><div className="min-w-0"><h2 className="truncate font-bold">{submission.paper_title || "Exam Paper"}</h2><p className="mt-0.5 text-xs text-muted-foreground">{submission.subject_name || "Subject"}</p><p className="mt-1 text-[11px] text-muted-foreground">{submission.regraded_from ? "Re-evaluation" : "Original evaluation"}{submission.retrigger_count > 0 ? ` · Restart ${submission.retrigger_count}` : ""}</p></div></div>
              <StatusBadge submission={submission} />
              <ScoreRing submission={submission} />
              <div className="text-sm text-muted-foreground">{new Date(submission.evaluation_date || submission.submitted_at).toLocaleString("en-IN", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" })}</div>
              <div>
                {submission.report_available ? <div className="flex flex-col gap-2"><Link href={`/dashboard/student/handwritten-evaluation/submissions/${submission.id}`} className="inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-xl bg-primary px-4 text-sm font-bold text-primary-foreground shadow-sm md:w-auto"><BarChart3 size={15} /> View Report <ChevronRight size={14} /></Link><button type="button" disabled={actionId === submission.id || !submission.paper_id} onClick={() => void retrigger(submission)} className="min-h-9 rounded-lg border px-3 text-xs font-semibold text-primary disabled:opacity-50">{actionId === submission.id ? "Starting…" : "Re-evaluate"}</button></div> : normalizedStatus(submission) === "failed" ? <div className="max-w-xs space-y-2"><div className="rounded-lg border border-destructive/25 bg-destructive/5 p-3 text-xs text-destructive">{submission.error_message || "Evaluation failed. You can retry without losing an attempt."}</div>{submission.status !== "blocked_rubric_failed" ? <div className="flex flex-wrap gap-2"><button type="button" disabled={actionId === submission.id || !submission.paper_id} onClick={() => void retrigger(submission)} className="min-h-9 rounded-lg bg-primary px-3 text-xs font-bold text-primary-foreground disabled:opacity-50">{actionId === submission.id ? "Restarting…" : "Retry evaluation"}</button><label className="inline-flex min-h-9 cursor-pointer items-center rounded-lg border px-3 text-xs font-semibold text-primary"><Upload size={13} className="mr-1.5" /> Add pages<input type="file" accept="application/pdf,image/png,image/jpeg" className="sr-only" disabled={actionId === submission.id} onChange={(event) => void addPages(submission, event.target.files?.[0] ?? null)} /></label></div> : null}</div> : <span className="inline-flex items-center gap-2 rounded-lg border border-primary/20 bg-primary/5 px-3 py-2 text-xs font-semibold text-primary"><span className="h-2 w-2 animate-pulse rounded-full bg-primary" /> Evaluation in progress</span>}
              </div>
            </article>
          ))}
          <p className="pt-2 text-center text-xs text-muted-foreground"><ClipboardList size={13} className="mr-1 inline" />{filtered.length} submission{filtered.length === 1 ? "" : "s"} · In-progress evaluations refresh every 5 seconds</p>
        </div>
      )}
    </div>
  );
}
