"use client";

import { useEffect, useMemo, useState } from "react";

import { AlertTriangle, Check, Copy, FileText, X } from "@/components/ui/icons";
import { Dialog } from "@/components/ui/dialog";
import type { EvaluationPaper, EvaluationPaperRubricQuestion } from "@/lib/api";

type Tab = "question" | "answers" | "schema";

const tabLabels: Record<Tab, string> = {
  question: "Question Paper",
  answers: "Suggested Answers",
  schema: "Grading Schema",
};

function readableQuestionCount(schema: EvaluationPaperRubricQuestion[]) {
  return `${schema.length.toLocaleString()} question${schema.length === 1 ? "" : "s"}`;
}

function EmptyExtractedText({ label, message }: { label: string; message: string }) {
  return (
    <div className="flex min-h-52 items-center justify-center rounded-xl border border-dashed bg-background/70 p-8 text-center">
      <div>
        <FileText size={28} className="mx-auto text-muted-foreground" />
        <p className="mt-3 text-sm font-semibold">{label} is not available yet</p>
        <p className="mt-1 max-w-sm text-xs leading-5 text-muted-foreground">
          {message}
        </p>
      </div>
    </div>
  );
}

function TextPane({ text, emptyLabel, emptyMessage }: { text: string; emptyLabel: string; emptyMessage: string }) {
  if (!text.trim()) return <EmptyExtractedText label={emptyLabel} message={emptyMessage} />;
  return (
    <div className="min-h-full rounded-xl border bg-card px-5 py-4 shadow-sm">
      <div className="whitespace-pre-wrap break-words text-sm leading-7 text-foreground">{text}</div>
    </div>
  );
}

function SchemaPane({ questions, emptyMessage }: { questions: EvaluationPaperRubricQuestion[]; emptyMessage: string }) {
  if (questions.length === 0) return <EmptyExtractedText label="Grading schema" message={emptyMessage} />;
  return (
    <div className="space-y-3">
      {questions.map((question, index) => (
        <article key={`${question.question_ref ?? "question"}-${index}`} className="rounded-xl border bg-card p-4 shadow-sm">
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-xs font-bold uppercase tracking-[0.12em] text-primary">
                {question.question_ref || `Question ${index + 1}`}
              </p>
              <h3 className="mt-1 text-sm font-semibold leading-6">
                {question.question_text || "Question text unavailable"}
              </h3>
            </div>
            <span className="shrink-0 rounded-full bg-primary/10 px-3 py-1 text-xs font-bold text-primary">
              {question.total_marks ?? 0} marks
            </span>
          </div>
          {question.topic ? <p className="mt-2 text-xs text-muted-foreground">Topic: {question.topic}</p> : null}
          {question.suggested_answer ? (
            <div className="mt-3 rounded-lg bg-muted/60 p-3">
              <p className="text-[11px] font-bold uppercase tracking-[0.1em] text-muted-foreground">Marking answer</p>
              <p className="mt-1 whitespace-pre-wrap text-sm leading-6">{question.suggested_answer}</p>
            </div>
          ) : null}
          {(question.criteria ?? []).length > 0 ? (
            <div className="mt-3 space-y-2">
              {(question.criteria ?? []).map((criterion, criterionIndex) => (
                <div key={criterion.criterion_id ?? criterionIndex} className="flex gap-3 rounded-lg border bg-background p-3 text-sm">
                  <span className="flex h-6 min-w-6 items-center justify-center rounded-full bg-primary/10 text-[11px] font-bold text-primary">
                    {criterionIndex + 1}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="leading-5">{criterion.description || criterion.criterion || "Criterion"}</p>
                    {criterion.category ? <p className="mt-1 text-xs text-muted-foreground">{criterion.category}</p> : null}
                  </div>
                  <span className="shrink-0 text-xs font-semibold text-muted-foreground">
                    {criterion.marks ?? criterion.marks_available ?? 0}m
                  </span>
                </div>
              ))}
            </div>
          ) : null}
        </article>
      ))}
    </div>
  );
}

function CopyButton({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    await navigator.clipboard.writeText(value);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1400);
  }
  return (
    <button type="button" onClick={() => void copy()} className="inline-flex h-8 items-center gap-1.5 rounded-lg border bg-card px-3 text-xs font-semibold text-muted-foreground transition hover:border-primary/40 hover:text-primary">
      {copied ? <Check size={14} /> : <Copy size={14} />}
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

export function EvaluationPaperExtractedDialog({
  paper,
  loading,
  onClose,
}: {
  paper: EvaluationPaper | null;
  loading: boolean;
  onClose: () => void;
}) {
  const [tab, setTab] = useState<Tab>("question");

  useEffect(() => setTab("question"), [paper?.id]);

  const schema = useMemo(
    () => (Array.isArray(paper?.structured_qa) ? paper.structured_qa : []),
    [paper?.structured_qa],
  );
  const questionText = paper?.question_paper_text ?? "";
  const answerText = paper?.suggested_answer_text ?? "";
  const activeValue = tab === "question"
    ? questionText
    : tab === "answers"
      ? answerText
      : JSON.stringify(schema, null, 2);
  const counts: Record<Tab, string> = {
    question: `${questionText.length.toLocaleString()} chars`,
    answers: `${answerText.length.toLocaleString()} chars`,
    schema: readableQuestionCount(schema),
  };
  const emptyMessage = paper?.rubric_status === "failed"
    ? (paper.rubric_error || "Rubric generation failed. Replace the source file or save a grading-related edit to retry.")
    : paper?.rubric_status === "ready"
      ? "The API reported a ready rubric but returned no stored content. Refresh the backend service and reopen this view."
      : "The background rubric job is still extracting this document. Close this window and try again shortly.";
  const readyPayloadMissing = paper?.rubric_status === "ready"
    && !questionText.trim() && !answerText.trim() && schema.length === 0;

  return (
    <Dialog
      onClose={onClose}
      ariaLabel="Extracted paper text"
      overlayClassName="fixed inset-0 z-[80] flex items-center justify-center bg-slate-950/80 p-3 backdrop-blur-sm sm:p-6"
      contentClassName="flex h-[92vh] w-full max-w-[1500px] flex-col overflow-hidden rounded-2xl border border-white/10 bg-card shadow-2xl"
    >
      <header className="flex shrink-0 items-center justify-between gap-4 bg-slate-950 px-5 py-4 text-white">
        <div className="flex min-w-0 items-center gap-3">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-white/10">
            <FileText size={19} />
          </span>
          <div className="min-w-0">
            <h2 className="truncate text-base font-bold">Extracted Text</h2>
            <p className="truncate text-xs text-white/65">{paper?.title ?? "Loading paper…"}</p>
          </div>
        </div>
        <button type="button" onClick={onClose} aria-label="Close extracted text" className="flex h-9 w-9 items-center justify-center rounded-lg bg-white/10 transition hover:bg-white/20">
          <X size={18} />
        </button>
      </header>

      <div role="tablist" aria-label="Extracted paper content" className="flex shrink-0 overflow-x-auto border-b bg-card px-2 sm:px-4">
        {(Object.keys(tabLabels) as Tab[]).map((key) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={tab === key}
            onClick={() => setTab(key)}
            className={`flex min-w-max items-center gap-2 border-b-2 px-3 py-3 text-xs font-bold transition sm:px-4 sm:text-sm ${
              tab === key ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            {tabLabels[key]}
            <span className="text-[10px] font-semibold opacity-70 sm:text-xs">({counts[key]})</span>
          </button>
        ))}
      </div>

      {loading ? (
        <div className="flex flex-1 items-center justify-center bg-muted/35">
          <div className="text-center">
            <span className="mx-auto block h-9 w-9 animate-spin rounded-full border-4 border-primary/20 border-t-primary" />
            <p className="mt-3 text-sm font-semibold">Loading extracted content…</p>
          </div>
        </div>
      ) : (
        <div className="flex min-h-0 flex-1 flex-col bg-muted/35">
          {(paper?.rubric_status === "failed" || readyPayloadMissing) ? (
            <div role="alert" className="mx-4 mt-4 flex shrink-0 items-start gap-2 rounded-xl border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive sm:mx-5">
              <AlertTriangle size={17} className="mt-0.5 shrink-0" />
              <span>{emptyMessage}</span>
            </div>
          ) : null}
          <div className="grid min-h-0 flex-1 lg:grid-cols-2">
          <section aria-label="Formatted extracted content" className="min-h-0 overflow-y-auto border-b p-4 lg:border-b-0 lg:border-r sm:p-5">
            <div className="mb-3 flex items-center justify-between gap-3">
              <p className="text-[11px] font-bold uppercase tracking-[0.12em] text-muted-foreground">Formatted</p>
              <span className="text-xs text-muted-foreground">{counts[tab]}</span>
            </div>
            {tab === "schema" ? (
              <SchemaPane questions={schema} emptyMessage={emptyMessage} />
            ) : (
              <TextPane text={activeValue} emptyLabel={tabLabels[tab]} emptyMessage={emptyMessage} />
            )}
          </section>
          <section aria-label="Raw extracted content" className="min-h-0 overflow-y-auto p-4 sm:p-5">
            <div className="mb-3 flex items-center justify-between gap-3">
              <p className="text-[11px] font-bold uppercase tracking-[0.12em] text-muted-foreground">Raw — exactly as stored in the DB</p>
              <CopyButton value={activeValue} />
            </div>
            <pre className="min-h-full whitespace-pre-wrap break-words rounded-xl border bg-card p-5 font-mono text-xs leading-6 text-foreground shadow-sm">
              {activeValue || "No extracted content stored yet."}
            </pre>
          </section>
          </div>
        </div>
      )}
    </Dialog>
  );
}
