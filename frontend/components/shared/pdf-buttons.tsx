"use client";

import { useState } from "react";

import { getQuizSet, getStudentReport } from "@/lib/api";
import {
  QuestionPaperDoc,
  ReportCardDoc,
  StudentReportDoc,
} from "@/lib/pdf/documents";
import { downloadPdf, slug } from "@/lib/pdf/download";

const btn =
  "inline-flex items-center gap-1 rounded-md border border-input px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:border-primary/50 hover:text-primary disabled:opacity-50";

// Staff: fetch the quiz set, then download a question paper (with/without key).
export function QuestionPaperButtons({
  quizSetId,
  title,
  meta,
  compact = false,
}: {
  quizSetId: string;
  title: string;
  meta?: string;
  compact?: boolean;
}) {
  const [busy, setBusy] = useState<"q" | "a" | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function go(withAnswers: boolean) {
    setBusy(withAnswers ? "a" : "q");
    setError(null);
    try {
      const detail = await getQuizSet(quizSetId);
      const questions = detail.variants?.[0]?.questions ?? [];
      await downloadPdf(
        <QuestionPaperDoc
          title={title}
          meta={meta}
          questions={questions as never}
          withAnswers={withAnswers}
        />,
        `${slug(title)}${withAnswers ? "-answer-key" : "-question-paper"}`,
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Download failed");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <button className={btn} disabled={!!busy} onClick={() => go(false)}>
        {busy === "q" ? "Preparing…" : compact ? "Paper" : "Download question paper"}
      </button>
      <button className={btn} disabled={!!busy} onClick={() => go(true)}>
        {busy === "a" ? "Preparing…" : "With answers"}
      </button>
      {error && <span className="text-xs text-red-600">{error}</span>}
    </div>
  );
}

// Student: build both docs from their own graded attempt (no staff API needed).
type ResultQ = {
  type: string;
  question_text: string;
  options?: { id: string; text: string }[] | null;
  correct_answer: unknown;
  explanation?: string | null;
  marks?: number | null;
  is_correct?: boolean | null;
  student_answer?: unknown;
};
export function StudentDownloads({
  quizTitle,
  score,
  maxScore,
  results,
}: {
  quizTitle: string;
  score: number;
  maxScore: number;
  results: ResultQ[];
}) {
  const [busy, setBusy] = useState<"r" | "p" | null>(null);

  async function report() {
    setBusy("r");
    try {
      await downloadPdf(
        <ReportCardDoc
          quizTitle={quizTitle}
          score={score}
          maxScore={maxScore}
          results={results as never}
        />,
        `${slug(quizTitle)}-report-card`,
      );
    } finally {
      setBusy(null);
    }
  }
  async function paper() {
    setBusy("p");
    try {
      await downloadPdf(
        <QuestionPaperDoc
          title={quizTitle}
          questions={results as never}
          withAnswers
        />,
        `${slug(quizTitle)}-with-answers`,
      );
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <button className={btn} disabled={!!busy} onClick={report}>
        {busy === "r" ? "Preparing…" : "Download report card"}
      </button>
      <button className={btn} disabled={!!busy} onClick={paper}>
        {busy === "p" ? "Preparing…" : "Download question paper (with answers)"}
      </button>
    </div>
  );
}

// Teacher: overall report for one student (from Class monitor).
export function StudentReportButton({
  studentId,
  studentName,
}: {
  studentId: string;
  studentName: string;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function go() {
    setBusy(true);
    setError(null);
    try {
      const r = await getStudentReport(studentId);
      await downloadPdf(
        <StudentReportDoc
          studentName={r.student.name}
          overall={r.overall}
          perQuiz={r.per_quiz}
          weakAreas={r.weak_areas}
        />,
        `${slug(studentName)}-report`,
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Download failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <span className="inline-flex items-center gap-2">
      <button className={btn} disabled={busy} onClick={go}>
        {busy ? "Preparing…" : "Report"}
      </button>
      {error && <span className="text-xs text-red-600">{error}</span>}
    </span>
  );
}
