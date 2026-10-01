"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  BookOpen,
  CalendarDays,
  Check,
  CheckCircle2,
  Download,
  Eye,
  FileText,
  Search,
  ShieldCheck,
  Upload,
  X,
} from "lucide-react";

import {
  type EvaluationPaper,
  type HandwrittenSubmissionQuota,
  type HandwrittenUploadProgress,
  getHandwrittenSubmissionQuota,
  listStudentEvaluationPapers,
  submitHandwrittenAnswer,
} from "@/lib/api";
import { ErrorCard } from "@/components/ui/error-card";
import { SkeletonCards } from "@/components/ui/skeleton";

const ACCEPTED = "application/pdf,image/png,image/jpeg";

function paperQuota(paper: EvaluationPaper): HandwrittenSubmissionQuota | null {
  if (
    typeof paper.completed_attempts !== "number"
    || typeof paper.attempt_limit !== "number"
    || typeof paper.remaining_attempts !== "number"
  ) return null;
  return {
    paper_id: paper.id,
    completed_attempts: paper.completed_attempts,
    attempt_limit: paper.attempt_limit,
    remaining_attempts: paper.remaining_attempts,
    active: paper.quota_active ?? false,
  };
}

function safeFilename(value: string): string {
  return value.replace(/[^a-z0-9]+/gi, "-").replace(/^-|-$/g, "").toLowerCase() || "question-paper";
}

async function downloadPaper(paper: EvaluationPaper) {
  if (!paper.question_paper_url) return;
  const response = await fetch(paper.question_paper_url);
  if (!response.ok) throw new Error("The question paper could not be downloaded.");
  const url = URL.createObjectURL(await response.blob());
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${safeFilename(paper.title)}.pdf`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function EvaluationTabs() {
  return (
    <nav className="flex flex-wrap gap-2" aria-label="Handwritten evaluation">
      <Link href="/dashboard/student/handwritten-evaluation" className="rounded-full bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground">
        Exam Papers
      </Link>
      <Link href="/dashboard/student/handwritten-evaluation/submissions" className="rounded-full border bg-card px-4 py-2 text-sm font-semibold text-muted-foreground transition hover:border-primary/40 hover:text-primary">
        My Submissions
      </Link>
    </nav>
  );
}

function PaperCard({ paper, onAttempt, onError }: {
  paper: EvaluationPaper;
  onAttempt: (paper: EvaluationPaper) => void;
  onError: (message: string) => void;
}) {
  const [downloading, setDownloading] = useState(false);

  return (
    <article className="flex min-h-[285px] flex-col overflow-hidden rounded-2xl border bg-card shadow-sm transition hover:-translate-y-0.5 hover:border-primary/35 hover:shadow-md">
      <div className="h-1 bg-primary" />
      <div className="flex flex-1 flex-col p-5">
        <div className="flex items-center justify-between gap-3">
          <span className="rounded-full border border-primary/20 bg-primary/5 px-3 py-1 text-[11px] font-bold uppercase tracking-wide text-primary">Mock Test</span>
          {paper.subject_name ? <span className="max-w-[55%] truncate rounded-full border border-primary/15 bg-primary/5 px-3 py-1 text-xs font-semibold text-primary">{paper.subject_name}</span> : null}
        </div>
        <h2 className="mt-4 text-lg font-bold leading-snug">{paper.title}</h2>
        <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
          {paper.created_at ? <span className="inline-flex items-center gap-1.5"><CalendarDays size={13} />{new Date(paper.created_at).toLocaleDateString("en-IN", { month: "short", year: "numeric" })}</span> : null}
          <span className="inline-flex items-center gap-1.5 rounded-md bg-muted/60 px-2.5 py-1.5 font-semibold text-foreground"><FileText size={13} /> {paper.total_marks} Marks</span>
        </div>
        {paper.course_name || paper.level_name ? <p className="mt-3 text-xs text-muted-foreground">{[paper.course_name, paper.level_name].filter(Boolean).join(" · ")}</p> : null}
        <div className="mt-auto grid grid-cols-2 gap-2 pt-5">
          <a href={paper.question_paper_url ?? "#"} target="_blank" rel="noreferrer" aria-disabled={!paper.question_paper_url} className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg border bg-background px-3 text-sm font-semibold transition hover:border-primary/35 hover:text-primary aria-disabled:pointer-events-none aria-disabled:opacity-50"><Eye size={15} /> View</a>
          <button type="button" disabled={!paper.question_paper_url || downloading} onClick={async () => {
            setDownloading(true);
            try { await downloadPaper(paper); }
            catch (reason) { onError(reason instanceof Error ? reason.message : "Download failed."); }
            finally { setDownloading(false); }
          }} className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg border border-primary/30 bg-background px-3 text-sm font-semibold text-primary transition hover:bg-primary/5 disabled:opacity-50"><Download size={15} /> {downloading ? "Preparing…" : "Download"}</button>
          <button type="button" onClick={() => onAttempt(paper)} className="col-span-2 inline-flex min-h-12 items-center justify-center gap-2 rounded-xl bg-primary px-4 text-sm font-bold text-primary-foreground shadow-sm transition hover:bg-primary/90"><Upload size={16} /> Attempt This Paper</button>
        </div>
      </div>
    </article>
  );
}

function AttemptModal({ paper, onClose }: { paper: EvaluationPaper; onClose: () => void }) {
  const router = useRouter();
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState<HandwrittenUploadProgress | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const [quota, setQuota] = useState<HandwrittenSubmissionQuota | null>(() => paperQuota(paper));
  const [quotaLoading, setQuotaLoading] = useState(() => paperQuota(paper) === null);
  const [quotaError, setQuotaError] = useState<string | null>(null);

  function quotaBlocksSubmission(value: HandwrittenSubmissionQuota): boolean {
    const reservedAttempts = value.completed_attempts + (value.active ? 1 : 0);
    return value.remaining_attempts <= 0 || reservedAttempts >= value.attempt_limit;
  }

  function quotaMessage(value: HandwrittenSubmissionQuota): string {
    if (value.remaining_attempts <= 0) {
      return `You have already used all ${value.attempt_limit} completed attempts for this paper.`;
    }
    return "An evaluation is already using your final available attempt. Wait for it to finish before trying again.";
  }

  const refreshQuota = useCallback(async (signal?: { active: boolean }) => {
    setQuotaLoading(true);
    setQuotaError(null);
    try {
      const value = await getHandwrittenSubmissionQuota(paper.id);
      if (!signal || signal.active) setQuota(value);
    } catch {
      if (!signal || signal.active) {
        setQuotaError("Attempt availability could not be refreshed. Please try again.");
      }
    } finally {
      if (!signal || signal.active) setQuotaLoading(false);
    }
  }, [paper.id]);

  useEffect(() => {
    const signal = { active: true };
    void refreshQuota(signal);
    return () => { signal.active = false; };
  }, [refreshQuota]);

  const progressCopy: Record<HandwrittenUploadProgress["stage"], string> = {
    authorizing: "Preparing a secure upload…",
    uploading: "Uploading your answer sheet…",
    verifying: "Checking that every page arrived safely…",
    queuing: "Starting your AI evaluation…",
    complete: "Submission received. Opening the evaluation tracker…",
  };

  async function submit() {
    if (!file) { setError("Choose your completed answer script first."); return; }
    setBusy(true);
    setError(null);
    try {
      // Recheck immediately before upload so a stale modal cannot upload a file
      // that the server will reject after the student's quota changes.
      const currentQuota = await getHandwrittenSubmissionQuota(paper.id);
      setQuota(currentQuota);
      if (quotaBlocksSubmission(currentQuota)) {
        setError(quotaMessage(currentQuota));
        setBusy(false);
        return;
      }
      const submission = await submitHandwrittenAnswer(paper.id, file, setProgress);
      setSubmitted(true);
      window.setTimeout(() => {
        router.push(`/dashboard/student/handwritten-evaluation/submissions/${submission.id}`);
      }, 700);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The answer script could not be submitted.");
      setProgress(null);
      setBusy(false);
    }
  }

  const quotaBlocked = quota ? quotaBlocksSubmission(quota) : true;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/55 p-4" role="dialog" aria-modal="true" aria-labelledby="attempt-title">
      <div className="flex max-h-[94vh] w-full max-w-2xl flex-col overflow-hidden rounded-2xl border bg-card shadow-2xl">
        <div className="flex items-start justify-between gap-4 border-b p-5">
          <div><p className="text-xs font-bold uppercase tracking-[0.16em] text-primary">Upload answer sheet</p><h2 id="attempt-title" className="mt-1 text-xl font-bold">{paper.title}</h2><p className="mt-1 text-sm text-muted-foreground">Review the checks below before submitting your handwritten work.</p></div>
          <button type="button" onClick={onClose} disabled={busy} className="grid h-10 w-10 shrink-0 place-items-center rounded-full border hover:bg-muted" aria-label="Close upload dialog"><X size={18} /></button>
        </div>
        <div className="min-h-0 space-y-4 overflow-y-auto p-5">
          {error ? <p role="alert" className="rounded-lg border border-destructive/25 bg-destructive/5 p-3 text-sm text-destructive">{error}</p> : null}
          {submitted ? (
            <div className="flex min-h-72 flex-col items-center justify-center rounded-2xl border border-emerald-200 bg-emerald-50 p-8 text-center dark:border-emerald-900 dark:bg-emerald-950/25">
              <span className="grid h-14 w-14 place-items-center rounded-full bg-emerald-600 text-white"><CheckCircle2 size={29} /></span>
              <h3 className="mt-4 text-lg font-bold">Submitted successfully</h3>
              <p className="mt-2 max-w-md text-sm leading-6 text-muted-foreground">Upload complete — evaluation queued. You can leave the tracker later and return from My Submissions.</p>
            </div>
          ) : (
            <>
              <section className="rounded-2xl border bg-muted/25 p-4">
                <div className="flex items-center gap-2"><ShieldCheck size={18} className="text-primary" /><h3 className="font-bold">Before you upload</h3></div>
                <p className="mt-1 text-xs text-muted-foreground">Check every page so the evaluator can match each answer correctly.</p>
                <ul className="mt-3 grid gap-2 text-sm sm:grid-cols-2">
                  {[
                    "Keep every question number and the full left margin visible.",
                    "Write your name and label answers clearly, such as Q1 or Q2(a).",
                    "Keep pages upright, well lit, readable, and free from blur.",
                    "Upload one PDF, PNG, or JPEG no larger than 30 MB.",
                    "For multiple pages, combine them into one file in the correct order.",
                  ].map((instruction) => <li key={instruction} className="flex gap-2 rounded-lg bg-background p-2.5 leading-5"><Check size={15} className="mt-0.5 shrink-0 text-emerald-600" /><span>{instruction}</span></li>)}
                </ul>
              </section>
              {quota ? <div className={`flex flex-col justify-between gap-1 rounded-xl border px-4 py-3 text-sm sm:flex-row sm:items-center ${quotaBlocked ? "border-destructive/30 bg-destructive/5 text-destructive" : "border-primary/20 bg-primary/5"}`}><span className="font-semibold">Evaluation attempts</span><span className={quotaBlocked ? "font-semibold" : "text-muted-foreground"}>{quotaBlocked ? quotaMessage(quota) : `${quota.remaining_attempts} of ${quota.attempt_limit} completed attempts remaining${quota.active ? " · one evaluation is already in progress" : ""}`}</span></div> : quotaLoading ? <div className="flex items-center justify-between rounded-xl border border-primary/20 bg-primary/5 px-4 py-3 text-sm" aria-live="polite"><span className="font-semibold">Evaluation attempts</span><span className="text-muted-foreground">Checking attempt availability…</span></div> : <div role="alert" className="flex flex-col justify-between gap-2 rounded-xl border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive sm:flex-row sm:items-center"><span>{quotaError ?? "Attempt availability is unavailable."}</span><button type="button" onClick={() => void refreshQuota()} className="font-bold underline underline-offset-2">Try again</button></div>}
              {quota && quotaError ? <p role="status" className="text-xs text-amber-700 dark:text-amber-300">{quotaError} The last known attempt count is shown.</p> : null}
              <label className={`flex min-h-36 flex-col items-center justify-center rounded-2xl border-2 border-dashed border-primary/25 bg-primary/5 px-5 text-center transition ${busy || quotaBlocked ? "cursor-not-allowed opacity-55" : "cursor-pointer hover:border-primary/50"}`}>
                <Upload size={26} className="text-primary" /><span className="mt-3 text-sm font-semibold">{file ? file.name : "Choose answer script"}</span><span className="mt-1 text-xs text-muted-foreground">PDF, PNG or JPEG · maximum 30 MB</span>
                <input type="file" accept={ACCEPTED} disabled={busy || quotaBlocked} className="sr-only" onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
              </label>
              {progress ? <div className="rounded-xl border border-primary/20 bg-primary/5 p-4" aria-live="polite"><div className="flex items-center justify-between gap-3 text-sm"><span className="font-semibold">{progressCopy[progress.stage]}</span><span className="font-bold text-primary">{progress.percent}%</span></div><div className="mt-3 h-2 overflow-hidden rounded-full bg-primary/10"><div className="h-full rounded-full bg-primary transition-all duration-500" style={{ width: `${progress.percent}%` }} /></div><p className="mt-2 text-xs text-muted-foreground">Keep this page open until the upload is complete.</p></div> : null}
            </>
          )}
        </div>
        {!submitted ? <div className="flex flex-col-reverse gap-2 border-t p-5 sm:flex-row sm:justify-end">
          <button type="button" onClick={onClose} disabled={busy} className="min-h-11 rounded-lg border px-5 text-sm font-semibold hover:bg-muted">Cancel</button>
          <button type="button" onClick={() => void submit()} disabled={busy || !file || quotaBlocked} className="min-h-11 rounded-lg bg-primary px-5 text-sm font-bold text-primary-foreground disabled:cursor-not-allowed disabled:opacity-50">{!quota ? quotaLoading ? "Checking Attempts…" : "Attempts Unavailable" : quotaBlocked ? "No Attempts Remaining" : busy ? "Submitting securely…" : "Submit for Evaluation"}</button>
        </div> : null}
      </div>
    </div>
  );
}

export function HandwrittenEvaluation() {
  const [papers, setPapers] = useState<EvaluationPaper[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [activePaper, setActivePaper] = useState<EvaluationPaper | null>(null);

  useEffect(() => {
    let active = true;
    listStudentEvaluationPapers()
      .then((items) => { if (active) setPapers(items); })
      .catch((reason) => { if (active) setError(reason instanceof Error ? reason.message : "Couldn't load exam papers."); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) return papers;
    return papers.filter((paper) => [paper.title, paper.subject_name, paper.course_name, paper.level_name].some((value) => value?.toLowerCase().includes(query)));
  }, [papers, search]);
  const courseLabel = papers[0]?.course_name && papers[0]?.level_name ? `${papers[0].course_name} · ${papers[0].level_name}` : papers[0]?.course_name || papers[0]?.level_name || "Your course";

  return (
    <div className="mx-auto w-full max-w-[1440px] space-y-6">
      <section className="relative overflow-hidden rounded-3xl bg-primary px-6 py-7 text-primary-foreground shadow-lg sm:px-8">
        <div className="absolute -right-12 -top-20 h-52 w-52 rounded-full bg-white/5" />
        <div className="relative flex flex-col gap-6 lg:flex-row lg:items-center lg:justify-between">
          <div><div className="flex flex-wrap items-center gap-2 text-xs font-semibold"><span className="inline-flex items-center gap-1.5 rounded-full border border-white/20 bg-white/10 px-3 py-1"><FileText size={13} /> Exam Papers</span><span className="rounded-full border border-white/20 bg-white/10 px-3 py-1">{papers.length} Available</span></div><h1 className="mt-3 text-3xl font-black tracking-tight">Available Exam Papers</h1><p className="mt-1 text-sm text-white/75">Select, download, and submit your handwritten answer script for evaluation.</p></div>
          <label className="relative block w-full lg:max-w-md"><Search size={17} className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-white/65" /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search papers or subjects…" className="h-12 w-full rounded-xl border border-white/30 bg-white/15 pl-11 pr-4 text-sm text-white outline-none placeholder:text-white/70 focus:bg-white/20 focus:ring-2 focus:ring-white/35" /></label>
        </div>
      </section>
      <div className="flex flex-col gap-4 rounded-2xl border bg-card p-5 shadow-sm sm:flex-row sm:items-center sm:justify-between"><div className="flex items-center gap-3"><span className="grid h-11 w-11 place-items-center rounded-xl bg-primary text-primary-foreground"><BookOpen size={19} /></span><div><p className="font-bold">{courseLabel}</p><p className="text-xs text-muted-foreground">{filtered.length} paper{filtered.length === 1 ? "" : "s"}</p></div></div><EvaluationTabs /></div>
      {error ? <ErrorCard title="We couldn't load the exam papers" message={error} onRetry={() => window.location.reload()} /> : null}
      {loading ? <SkeletonCards count={4} /> : filtered.length ? <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">{filtered.map((paper) => <PaperCard key={paper.id} paper={paper} onAttempt={setActivePaper} onError={setError} />)}</div> : !error ? <div className="rounded-2xl border border-dashed bg-card px-6 py-14 text-center"><FileText size={34} className="mx-auto text-muted-foreground" /><h2 className="mt-4 font-bold">No exam papers found</h2><p className="mt-1 text-sm text-muted-foreground">There are no active papers matching your course, level, and search.</p></div> : null}
      {activePaper ? <AttemptModal paper={activePaper} onClose={() => setActivePaper(null)} /> : null}
    </div>
  );
}
