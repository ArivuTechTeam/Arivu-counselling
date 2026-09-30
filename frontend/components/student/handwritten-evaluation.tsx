"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  BookOpen,
  CalendarDays,
  Download,
  Eye,
  FileText,
  Search,
  Upload,
  X,
} from "lucide-react";

import {
  type EvaluationPaper,
  listStudentEvaluationPapers,
  submitHandwrittenAnswer,
} from "@/lib/api";
import { ErrorCard } from "@/components/ui/error-card";
import { SkeletonCards } from "@/components/ui/skeleton";

const ACCEPTED = "application/pdf,image/png,image/jpeg";

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

  async function submit() {
    if (!file) { setError("Choose your completed answer script first."); return; }
    setBusy(true);
    setError(null);
    try {
      await submitHandwrittenAnswer(paper.id, file);
      router.push("/dashboard/student/handwritten-evaluation/submissions");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The answer script could not be submitted.");
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/55 p-4" role="dialog" aria-modal="true" aria-labelledby="attempt-title">
      <div className="w-full max-w-xl overflow-hidden rounded-2xl border bg-card shadow-2xl">
        <div className="flex items-start justify-between gap-4 border-b p-5">
          <div><p className="text-xs font-bold uppercase tracking-[0.16em] text-primary">Attempt paper</p><h2 id="attempt-title" className="mt-1 text-xl font-bold">{paper.title}</h2><p className="mt-1 text-sm text-muted-foreground">Upload one PDF, PNG, or JPEG containing your completed handwritten answers.</p></div>
          <button type="button" onClick={onClose} disabled={busy} className="grid h-10 w-10 shrink-0 place-items-center rounded-full border hover:bg-muted" aria-label="Close upload dialog"><X size={18} /></button>
        </div>
        <div className="space-y-4 p-5">
          {error ? <p role="alert" className="rounded-lg border border-destructive/25 bg-destructive/5 p-3 text-sm text-destructive">{error}</p> : null}
          <label className="flex min-h-40 cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed border-primary/25 bg-primary/5 px-5 text-center transition hover:border-primary/50">
            <Upload size={26} className="text-primary" /><span className="mt-3 text-sm font-semibold">{file ? file.name : "Choose answer script"}</span><span className="mt-1 text-xs text-muted-foreground">PDF, PNG or JPEG · maximum 30 MB</span>
            <input type="file" accept={ACCEPTED} className="sr-only" onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
          </label>
          <div className="rounded-xl border bg-muted/30 p-3 text-xs leading-5 text-muted-foreground">Keep all pages upright and in order. Evaluation progress appears automatically under My Submissions.</div>
        </div>
        <div className="flex flex-col-reverse gap-2 border-t p-5 sm:flex-row sm:justify-end">
          <button type="button" onClick={onClose} disabled={busy} className="min-h-11 rounded-lg border px-5 text-sm font-semibold hover:bg-muted">Cancel</button>
          <button type="button" onClick={() => void submit()} disabled={busy || !file} className="min-h-11 rounded-lg bg-primary px-5 text-sm font-bold text-primary-foreground disabled:opacity-50">{busy ? "Uploading and submitting…" : "Submit for Evaluation"}</button>
        </div>
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
