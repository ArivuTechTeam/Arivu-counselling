"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowLeft,
  ChevronRight,
  Download,
  FileText,
  LayoutDashboard,
} from "lucide-react";

import { useDashboardIdentity } from "@/components/shared/dashboard-identity-context";
import { ErrorCard } from "@/components/ui/error-card";
import { Skeleton } from "@/components/ui/skeleton";
import { type HandwrittenEvaluationReport, getHandwrittenEvaluationReport } from "@/lib/api";
import { parseAnswerTranscript } from "@/lib/answer-transcript";
import {
  type QuestionGuidance,
  buildHandwrittenReportView,
  formatEvaluationMark,
} from "@/lib/handwritten-report";

function levelClass(tone: QuestionGuidance["level"]["tone"]): string {
  if (tone === "strong") return "border-emerald-300 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950/35 dark:text-emerald-300";
  if (tone === "on-track") return "border-blue-300 bg-blue-50 text-blue-700 dark:border-blue-900 dark:bg-blue-950/35 dark:text-blue-300";
  if (tone === "revision" || tone === "warning") return "border-amber-300 bg-amber-50 text-amber-800 dark:border-amber-900 dark:bg-amber-950/35 dark:text-amber-300";
  return "border-input bg-muted text-muted-foreground";
}

function LevelBadge({ item }: { item: QuestionGuidance }) {
  return <span className={`rounded-full border px-2.5 py-1 text-[11px] font-bold ${levelClass(item.level.tone)}`}>{item.level.label}</span>;
}

function AnswerTranscript({ text }: { text: string }) {
  const blocks = useMemo(() => parseAnswerTranscript(text), [text]);
  if (!text.trim()) return <p className="italic text-muted-foreground">No answer text was extracted.</p>;
  return (
    <div className="grid min-w-0 gap-3.5">
      {blocks.map((block, index) => {
        if (block.type === "table") {
          const columns = Math.max(...block.rows.map((row) => row.length));
          const [header, ...body] = block.rows;
          return (
            <div key={index} className="max-w-full overflow-x-auto rounded-[9px] border" role="region" aria-label="Student answer table" tabIndex={0}>
              <table className="w-full min-w-[520px] border-collapse text-left text-xs tabular-nums">
                <thead><tr>{Array.from({ length: columns }, (_, cell) => <th key={cell} className="border-b border-r bg-muted px-3 py-2 text-[11px] font-extrabold text-muted-foreground last:border-r-0">{header[cell] || ""}</th>)}</tr></thead>
                <tbody>{body.map((row, rowIndex) => <tr key={rowIndex} className="even:bg-muted/50">{Array.from({ length: columns }, (_, cell) => <td key={cell} className="border-b border-r px-3 py-2 align-top last:border-r-0 last-of-type:border-r-0">{row[cell] || ""}</td>)}</tr>)}</tbody>
              </table>
            </div>
          );
        }
        if (block.type === "heading") return <h5 key={index} className="border-b pb-1.5 text-sm font-extrabold">{block.text}</h5>;
        if (block.type === "working") return <section key={index} className="overflow-hidden rounded-[10px] border bg-muted/35"><div className="flex items-center gap-2 border-b bg-primary/10 px-3 py-2 text-[11px] font-extrabold uppercase tracking-wider text-primary"><span className="h-1.5 w-1.5 rotate-45 rounded-[2px] bg-primary" />Working / calculations</div><div>{block.lines.map((line, lineIndex) => <div key={`${line}-${lineIndex}`} className="grid grid-cols-[6px_minmax(0,1fr)] gap-3 border-t border-dashed px-3 py-2 first:border-0"><span className="mt-2 h-1.5 w-1.5 rounded-full bg-muted-foreground" /><p className="whitespace-pre-wrap text-[13px] leading-6">{line}</p></div>)}</div></section>;
        if (block.type === "list") return <div key={index} className="overflow-hidden rounded-[10px] border bg-muted/35">{block.lines.map((line, lineIndex) => <p key={`${line}-${lineIndex}`} className="border-t px-3 py-2 text-[13px] leading-6 first:border-0">{line}</p>)}</div>;
        if (block.type === "verdict") return <div key={index} className={`flex items-start gap-2 rounded-[9px] border border-l-[3px] p-3 ${block.verdict.toLowerCase() === "true" ? "border-l-emerald-600" : "border-l-amber-600"}`}>{block.prefix ? <span className="text-xs font-extrabold text-muted-foreground">{block.prefix}</span> : null}<strong className="rounded-full bg-muted px-2 py-0.5 text-xs">{block.verdict}</strong>{block.explanation ? <p className="text-[13px] leading-6">{block.explanation}</p> : null}</div>;
        if (block.type === "text") return <p key={index} className="whitespace-pre-wrap text-[13px] leading-6">{block.text}</p>;
        return null;
      })}
    </div>
  );
}

function QuestionDetail({ item }: { item: QuestionGuidance }) {
  const fullScore = item.state === "evaluated" && item.total > 0 && item.score >= item.total;
  return (
    <article className="overflow-hidden rounded-2xl border bg-card shadow-sm">
      <header className="flex flex-col justify-between gap-3 border-b bg-muted/30 p-5 sm:flex-row sm:items-start">
        <div><h3 className="text-lg font-bold">{item.label}</h3>{item.title ? <p className="mt-1 max-w-3xl text-sm text-muted-foreground">{item.title}</p> : null}</div>
        <div className="flex items-center justify-between gap-3 sm:flex-col sm:items-end"><strong className="text-lg">{item.scoreLabel}</strong><LevelBadge item={item} /></div>
      </header>
      {item.statusDescription ? <div className="m-5 mb-0 rounded-xl border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-200"><strong>{item.level.label}.</strong> {item.statusDescription}</div> : null}
      <div className="space-y-4 p-5">
        <section className="overflow-hidden rounded-xl border border-t-4 border-t-primary bg-card"><h4 className="border-b bg-primary/5 px-4 py-3 text-sm font-bold text-primary">What you wrote</h4><div className="p-4 text-sm"><AnswerTranscript text={item.studentAnswer} /></div><div className="border-t bg-primary/5 px-4 py-3 text-sm"><strong className="text-primary">What you did well:</strong> <span className="text-muted-foreground">{item.didWell}</span></div></section>
        {fullScore ? <section className="rounded-xl border border-emerald-300 bg-emerald-50 p-4 dark:border-emerald-900 dark:bg-emerald-950/25"><h4 className="font-bold text-emerald-700 dark:text-emerald-300">Well done</h4><p className="mt-2 text-sm text-muted-foreground">{item.didWell} Keep it up.</p></section> : item.mistakes.length ? <section className="rounded-xl border border-amber-300 bg-amber-50 p-4 dark:border-amber-900 dark:bg-amber-950/25"><h4 className="font-bold text-amber-800 dark:text-amber-300">Mistakes &amp; expected answers</h4><ul className="mt-3 space-y-2">{item.mistakes.map((pair, index) => <li key={`${pair.mistake}-${index}`} className="rounded-lg border border-amber-200 bg-card p-3 text-sm"><p><strong className="text-amber-800 dark:text-amber-300">Mistake:</strong> {pair.mistake}</p><p className="mt-1 text-muted-foreground"><strong>Expected:</strong> {pair.expected}</p></li>)}</ul></section> : <section className="rounded-xl border border-amber-300 bg-amber-50 p-4 dark:border-amber-900 dark:bg-amber-950/25"><h4 className="font-bold text-amber-800 dark:text-amber-300">Improve next</h4><ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-muted-foreground">{item.improvements.map((point) => <li key={point}>{point}</li>)}</ul></section>}
        {item.state !== "evaluated" && item.expectedPoints.length ? <section className="rounded-xl border border-blue-300 bg-blue-50 p-4 dark:border-blue-900 dark:bg-blue-950/25"><h4 className="font-bold text-blue-700 dark:text-blue-300">Expected answer points</h4><ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-muted-foreground">{item.expectedPoints.map((point) => <li key={point}>{point}</li>)}</ul></section> : null}
      </div>
    </article>
  );
}

export function HandwrittenReport({ submissionId }: { submissionId: string }) {
  const { institution, email } = useDashboardIdentity();
  const [report, setReport] = useState<HandwrittenEvaluationReport | null>(null);
  const [activeSection, setActiveSection] = useState("overview");
  const [loading, setLoading] = useState(true);
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const contentRef = useRef<HTMLElement>(null);
  const activeNavRef = useRef<HTMLButtonElement>(null);
  const hasNavigatedRef = useRef(false);

  useEffect(() => {
    let active = true;
    getHandwrittenEvaluationReport(submissionId)
      .then((value) => { if (active) setReport(value); })
      .catch((reason) => { if (active) setError(reason instanceof Error ? reason.message : "Couldn't load the evaluation report."); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [submissionId]);

  const view = useMemo(() => report ? buildHandwrittenReportView(report) : null, [report]);
  const activeQuestion = view && activeSection.startsWith("question-") ? view.guidance[Number(activeSection.slice(9))] : null;

  useEffect(() => {
    if (!hasNavigatedRef.current) {
      hasNavigatedRef.current = true;
      return;
    }
    contentRef.current?.focus({ preventScroll: true });
    contentRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    activeNavRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [activeSection]);

  async function downloadReport() {
    if (!report) return;
    setDownloading(true);
    setError(null);
    try {
      const [{ downloadPdf, slug }, { HandwrittenEvaluationReportDoc }] = await Promise.all([
        import("@/lib/pdf/download"),
        import("@/lib/pdf/handwritten-evaluation-report"),
      ]);
      await downloadPdf(
        <HandwrittenEvaluationReportDoc report={report} branding={institution} />,
        `${slug(report.student.name || report.student.email || email || "student")}-${slug(report.paper.title)}-evaluation-summary`,
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not generate the report PDF.");
    } finally {
      setDownloading(false);
    }
  }

  if (loading) return <div className="mx-auto max-w-[1440px] space-y-4"><Skeleton className="h-20 rounded-2xl" /><div className="grid gap-5 lg:grid-cols-[235px_minmax(0,1fr)]"><Skeleton className="h-96 rounded-2xl" /><Skeleton className="h-[520px] rounded-2xl" /></div></div>;
  if (error && !report) return <div className="mx-auto max-w-2xl"><ErrorCard title="We couldn't open this report" message={error} onRetry={() => window.location.reload()} /></div>;
  if (!report || !view) return null;
  const evaluatedDate = new Date(report.evaluation_date).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });

  return (
    <div className="min-h-full bg-muted/30">
      <header className="sticky top-0 z-20 flex min-h-[68px] flex-col gap-3 border-b bg-card/95 px-4 py-3 shadow-sm backdrop-blur sm:flex-row sm:items-center sm:justify-between sm:px-6">
        <div className="flex min-w-0 items-center gap-3.5">
          <Link href="/dashboard/student/handwritten-evaluation/submissions" className="grid h-11 w-11 shrink-0 place-items-center rounded-[10px] border bg-muted/40 hover:bg-muted" aria-label="Back to submissions"><ArrowLeft size={18} /></Link>
          <div className="min-w-0"><h1 className="text-base font-extrabold">Evaluation Report</h1><p className="mt-0.5 truncate text-xs text-muted-foreground">{report.paper.title}</p></div>
        </div>
        <div className="flex flex-wrap justify-end gap-2.5">
          {report.answer_script_url ? <a href={report.answer_script_url} target="_blank" rel="noreferrer" className="inline-flex min-h-11 items-center gap-2 rounded-[10px] border border-primary/25 bg-primary/5 px-4 text-[13px] font-bold text-primary"><FileText size={16} /> View Answer Sheet</a> : null}
          <button type="button" onClick={() => void downloadReport()} disabled={downloading} className="inline-flex min-h-11 items-center gap-2 rounded-[10px] bg-primary px-4 text-[13px] font-bold text-primary-foreground disabled:cursor-wait disabled:opacity-60"><Download size={16} />{downloading ? "Generating…" : "Download Report"}</button>
        </div>
      </header>

      <div className="mx-auto w-[min(1440px,calc(100%-2rem))] py-6">
        {error ? <p role="alert" className="mb-4 rounded-xl border border-destructive/25 bg-destructive/5 p-3 text-sm text-destructive">{error}</p> : null}
        {report.requires_review ? <p role="status" className="mb-4 rounded-xl border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-200">Some extracted answers need faculty review. Scores marked for review should not be treated as final.</p> : null}

        <div className="grid items-start gap-5 lg:grid-cols-[235px_minmax(0,1fr)]">
          <aside className="overflow-hidden rounded-2xl border bg-card shadow-[0_8px_24px_rgba(18,28,24,0.06)] lg:sticky lg:top-[84px] lg:max-h-[calc(100vh-110px)]">
            <div className="flex items-center justify-between gap-2 border-b bg-gradient-to-br from-primary/10 to-card p-3.5"><div><p className="text-[10px] font-extrabold uppercase tracking-[0.07em] text-muted-foreground">Overall score</p><p className="mt-1 text-xl font-black text-primary">{formatEvaluationMark(view.score)}/{formatEvaluationMark(view.total)}</p></div><span className={`rounded-full border px-2.5 py-1 text-[11px] font-bold ${levelClass(view.level.tone)}`}>{view.level.label}</span></div>
            <p className="px-3.5 pb-1 pt-3 text-[10px] font-extrabold uppercase tracking-[0.08em] text-muted-foreground">Report sections</p>
            <nav className="max-h-[calc(100vh-260px)] space-y-1 overflow-y-auto px-2 pb-3 pt-1.5" aria-label="Report sections">
              <button ref={activeSection === "overview" ? activeNavRef : null} type="button" onClick={() => setActiveSection("overview")} aria-current={activeSection === "overview" ? "page" : undefined} className={`flex min-h-11 w-full items-center justify-between rounded-[10px] border border-transparent px-3 text-[13px] font-bold ${activeSection === "overview" ? "bg-primary/10 text-primary shadow-[inset_3px_0_0_hsl(var(--primary))]" : "text-muted-foreground hover:border-border hover:bg-muted"}`}><span className="inline-flex items-center gap-2"><LayoutDashboard size={15} /> Overview</span><span className="rounded-full bg-card px-2 py-0.5 text-[11px]">{view.level.percentage}%</span></button>
              {view.guidance.map((item, index) => {
                const id = `question-${index}`;
                return <button ref={activeSection === id ? activeNavRef : null} key={`${item.label}-${index}`} type="button" onClick={() => setActiveSection(id)} aria-current={activeSection === id ? "page" : undefined} className={`flex min-h-11 w-full items-center justify-between rounded-[10px] border border-transparent px-3 text-[13px] font-bold ${activeSection === id ? "bg-primary/10 text-primary shadow-[inset_3px_0_0_hsl(var(--primary))]" : "text-muted-foreground hover:border-border hover:bg-muted"}`}><span className="inline-flex min-w-0 items-center gap-2"><span className={`h-[7px] w-[7px] shrink-0 rounded-full border-2 ${activeSection === id ? "border-primary bg-primary" : "border-muted-foreground bg-card"}`} /><span className="truncate">{item.label}</span></span><span className="ml-2 shrink-0 rounded-full bg-card px-2 py-0.5 text-[10px]">{item.scoreLabel}</span></button>;
              })}
            </nav>
          </aside>

          <main ref={contentRef} tabIndex={-1} className="min-w-0 scroll-mt-[84px] outline-none">
            {activeSection === "overview" ? (
              <div>
                <div className="mb-4"><p className="text-[11px] font-extrabold uppercase tracking-[0.08em] text-primary">Evaluation complete</p><h2 className="mt-1 text-[21px] font-black tracking-tight">Performance Overview</h2><p className="mt-1 text-[13px] text-muted-foreground">See your result and choose any question for focused guidance.</p></div>
                <section className="grid overflow-hidden rounded-[18px] border border-primary/20 bg-card shadow-[0_10px_28px_rgba(46,136,87,0.09)] md:grid-cols-[minmax(190px,0.7fr)_minmax(0,1.6fr)]">
                  <div className="relative overflow-hidden bg-gradient-to-br from-primary/95 via-primary to-primary/80 p-6 text-primary-foreground"><div className="absolute -bottom-16 -right-10 h-[155px] w-[155px] rounded-full bg-white/[0.06]" /><p className="relative text-[11px] font-extrabold uppercase tracking-[0.08em] text-white/70">Overall score</p><div className="relative mt-3 flex items-baseline gap-1.5"><strong className="text-[52px] leading-none">{formatEvaluationMark(view.score)}</strong><span className="text-base font-bold text-white/65">/ {formatEvaluationMark(view.total)}</span></div><div className="relative mt-3 flex items-center gap-2.5"><strong className="text-[13px]">{view.level.percentage}%</strong><span className="rounded-full border border-white/25 bg-white/10 px-2.5 py-1 text-[11px] font-extrabold">{view.level.label}</span></div></div>
                  <div className="flex min-w-0 flex-col justify-between gap-5 p-6"><p className="max-w-[650px] text-sm font-semibold leading-6 text-muted-foreground">{view.summary}</p><dl className="grid gap-3 sm:grid-cols-[minmax(0,1.6fr)_minmax(120px,0.8fr)_minmax(100px,0.6fr)]"><div className="min-w-0 border-t pt-3"><dt className="text-[10px] font-extrabold uppercase tracking-widest text-muted-foreground">Paper</dt><dd className="mt-1 truncate text-xs font-bold">{report.paper.title}</dd></div><div className="min-w-0 border-t pt-3"><dt className="text-[10px] font-extrabold uppercase tracking-widest text-muted-foreground">Student</dt><dd className="mt-1 truncate text-xs font-bold">{report.student.name || report.student.email || email || "Student"}</dd></div><div className="min-w-0 border-t pt-3"><dt className="text-[10px] font-extrabold uppercase tracking-widest text-muted-foreground">Evaluated</dt><dd className="mt-1 text-xs font-bold">{evaluatedDate}</dd></div></dl></div>
                </section>
                <div className="mt-4 grid items-start gap-4 xl:grid-cols-[minmax(0,1.25fr)_minmax(285px,0.75fr)]">
                  <section className="overflow-hidden rounded-2xl border bg-card shadow-sm"><div className="border-b px-4 py-4"><p className="text-[11px] font-extrabold uppercase tracking-[0.08em] text-primary">At a glance</p><h3 className="mt-1 text-base font-bold">Question Performance</h3><p className="mt-1 text-xs text-muted-foreground">Select a question to view its improvement guidance.</p></div><div className="max-h-[410px] overflow-y-auto p-2">{view.guidance.map((item, index) => <button key={`${item.label}-${index}`} type="button" onClick={() => setActiveSection(`question-${index}`)} className="grid min-h-[62px] w-full grid-cols-[46px_minmax(0,1fr)_20px] items-center gap-3 rounded-[10px] border border-transparent px-3 py-2 text-left transition hover:border-primary/20 hover:bg-muted"><span className="grid h-9 w-[42px] place-items-center rounded-[9px] border border-primary/20 bg-primary/10 text-xs font-black text-primary">{item.label}</span><span className="min-w-0"><span className="flex items-center justify-between gap-3"><strong className="text-[13px]">{item.scoreLabel}</strong><LevelBadge item={item} /></span><span className="mt-2 block h-1 overflow-hidden rounded-full bg-muted"><span className="block h-full rounded-full bg-primary" style={{ width: `${Math.max(0, Math.min(100, item.level.percentage ?? 0))}%` }} /></span></span><ChevronRight size={17} className="text-muted-foreground" /></button>)}</div></section>
                  <div className="space-y-4">{view.strengths.length ? <section className="overflow-hidden rounded-2xl border bg-card shadow-sm"><div className="border-b px-4 py-4"><p className="text-[11px] font-extrabold uppercase tracking-[0.08em] text-primary">Keep doing this</p><h3 className="mt-1 text-base font-bold">Your Strengths</h3></div><ul>{view.strengths.map((strength) => <li key={strength} className="relative border-t py-3 pl-8 pr-4 text-xs leading-5 text-muted-foreground first:border-0"><span className="absolute left-4 font-black text-primary">✓</span>{strength}</li>)}</ul></section> : null}<section className="overflow-hidden rounded-2xl border bg-card shadow-sm"><div className="border-b px-4 py-4"><p className="text-[11px] font-extrabold uppercase tracking-[0.08em] text-primary">Action plan</p><h3 className="mt-1 text-base font-bold">Your Next Three Steps</h3></div><ol>{view.nextSteps.map((step, index) => <li key={step} className="flex gap-3 border-t px-4 py-3.5 first:border-0"><span className="grid h-7 w-7 shrink-0 place-items-center rounded-[9px] bg-primary/10 text-xs font-black text-primary">{index + 1}</span><p className="text-xs leading-5 text-muted-foreground">{step}</p></li>)}</ol></section></div>
                </div>
              </div>
            ) : activeQuestion ? <section aria-label={`${activeQuestion.label} guidance`}><div className="mb-3.5"><p className="text-[11px] font-extrabold uppercase tracking-[0.08em] text-primary">Focused feedback</p><h2 className="mt-1 text-lg font-black">{activeQuestion.label} Guidance</h2></div><QuestionDetail item={activeQuestion} /></section> : null}
          </main>
        </div>
      </div>
    </div>
  );
}
