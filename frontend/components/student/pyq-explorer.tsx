"use client";

import { useCallback, useEffect, useState } from "react";

import {
  PaperFilters,
  PaperScorecard,
  PaperStart,
  PaperSubject,
  PaperTakeQuestion,
  PaperType,
  getPaperFilters,
  listPaperSubjects,
  startPaperAttempt,
  submitPaperAttempt,
} from "@/lib/api";
import { formatAnswerValue, typeLabel } from "@/lib/format";

const TYPES: { key: PaperType; label: string; blurb: string }[] = [
  { key: "pyq", label: "PYQ", blurb: "Previous-year questions" },
  { key: "mtp", label: "MTP", blurb: "Mock test papers" },
  { key: "rtp", label: "RTP", blurb: "Revision test papers" },
];

const card = "rounded-xl border bg-card p-4 shadow-sm transition-colors hover:border-primary/40";
const field = "h-10 w-full rounded-md border border-input bg-background px-3 text-sm focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20";
const primaryBtn = "inline-flex h-10 items-center rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50";
const ghostBtn = "inline-flex h-9 items-center rounded-lg border border-input px-3 text-sm hover:bg-accent";

export function PyqExplorer() {
  const [type, setType] = useState<PaperType>("pyq");
  const [view, setView] = useState<"subjects" | "config" | "taking" | "score">("subjects");
  const [subjects, setSubjects] = useState<PaperSubject[]>([]);
  const [subject, setSubject] = useState<PaperSubject | null>(null);
  const [filters, setFilters] = useState<PaperFilters | null>(null);
  const [chapterId, setChapterId] = useState("");
  const [qType, setQType] = useState("");
  const [count, setCount] = useState(10);
  const [questions, setQuestions] = useState<PaperTakeQuestion[]>([]);
  const [answers, setAnswers] = useState<Record<string, unknown>>({});
  const [score, setScore] = useState<PaperScorecard | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadSubjects = useCallback(async (t: PaperType) => {
    setLoading(true);
    setError(null);
    try {
      setSubjects(await listPaperSubjects(t));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't load.");
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    setView("subjects");
    void loadSubjects(type);
  }, [type, loadSubjects]);

  async function openSubject(s: PaperSubject) {
    setSubject(s);
    setChapterId("");
    setQType("");
    setCount(10);
    setError(null);
    setBusy(true);
    try {
      setFilters(await getPaperFilters(type, s.subject_id));
      setView("config");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't load options.");
    } finally {
      setBusy(false);
    }
  }

  async function start() {
    if (!subject) return;
    setBusy(true);
    setError(null);
    try {
      const body: PaperStart = {
        paper_type: type,
        subject_id: subject.subject_id,
        chapter_id: chapterId || null,
        question_type: qType || null,
        count,
      };
      const res = await startPaperAttempt(body);
      setQuestions(res.questions);
      setAnswers({});
      setScore(null);
      setView("taking");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't start.");
    } finally {
      setBusy(false);
    }
  }

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      const payload = questions.map((q) => ({ question_id: q.id, student_answer: answers[q.id] ?? null }));
      setScore(await submitPaperAttempt(payload));
      setView("score");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't submit.");
    } finally {
      setBusy(false);
    }
  }

  const Err = error ? <p className="text-sm text-destructive">{error}</p> : null;

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-5">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Mock Test &amp; PYQ</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Practise real exam questions — previous-year, mock, and revision papers — with an instant scorecard.
        </p>
      </div>

      {/* Type tabs */}
      <div className="flex gap-2">
        {TYPES.map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => setType(t.key)}
            className={`rounded-lg border px-4 py-2 text-sm font-medium transition-colors ${
              type === t.key ? "border-primary bg-primary/5 text-primary" : "border-input hover:bg-accent"
            }`}
            title={t.blurb}
          >
            {t.label}
          </button>
        ))}
      </div>

      {Err}

      {view === "subjects" && (
        loading ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : subjects.length === 0 ? (
          <Empty>No subjects to show yet.</Empty>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2">
            {subjects.map((s) => (
              <button
                key={s.subject_id}
                type="button"
                disabled={busy || s.count === 0}
                onClick={() => void openSubject(s)}
                className={`${card} text-left disabled:cursor-not-allowed disabled:opacity-60`}
              >
                <p className="font-semibold">{s.subject_name}</p>
                <p className="mt-1 text-sm text-muted-foreground">
                  {s.count > 0 ? `${s.count} question${s.count === 1 ? "" : "s"} available` : "None yet"}
                </p>
              </button>
            ))}
          </div>
        )
      )}

      {view === "config" && subject && filters && (
        <div className="flex flex-col gap-4">
          <button type="button" className={ghostBtn} onClick={() => setView("subjects")}>← Subjects</button>
          <div className={card}>
            <p className="mb-3 font-semibold">{subject.subject_name} · {filters.total} available</p>
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="flex flex-col gap-1 text-xs text-muted-foreground">
                Chapter
                <select className={field} value={chapterId} onChange={(e) => setChapterId(e.target.value)}>
                  <option value="">All chapters</option>
                  {filters.chapters.map((c) => (
                    <option key={c.chapter_id} value={c.chapter_id}>{c.chapter_name} ({c.count})</option>
                  ))}
                </select>
              </label>
              <label className="flex flex-col gap-1 text-xs text-muted-foreground">
                Question type
                <select className={field} value={qType} onChange={(e) => setQType(e.target.value)}>
                  <option value="">All types</option>
                  {filters.question_types.map((t) => (
                    <option key={t.type} value={t.type}>{typeLabel(t.type)} ({t.count})</option>
                  ))}
                </select>
              </label>
              <label className="flex flex-col gap-1 text-xs text-muted-foreground">
                Number of questions
                <input
                  type="number"
                  min={1}
                  max={50}
                  className={field}
                  value={count}
                  onChange={(e) => setCount(Math.max(1, Math.min(50, Number(e.target.value) || 1)))}
                />
              </label>
            </div>
            <button type="button" className={`${primaryBtn} mt-4`} disabled={busy} onClick={() => void start()}>
              {busy ? "Starting…" : "Start"}
            </button>
          </div>
        </div>
      )}

      {view === "taking" && (
        <div className="flex flex-col gap-4">
          <p className="text-sm text-muted-foreground">
            {questions.filter((q) => {
              const v = answers[q.id];
              return Array.isArray(v) ? v.length > 0 : v !== undefined && v !== "" && v !== null;
            }).length} of {questions.length} answered
          </p>
          {questions.map((q, i) => (
            <div key={q.id} className="rounded-xl border bg-card p-4 shadow-sm">
              <p className="mb-3 font-medium">
                <span className="mr-2 text-muted-foreground">Q{i + 1}.</span>{q.question_text}
                {(q.exam || q.year) && (
                  <span className="ml-2 rounded-full border border-amber-300 bg-amber-50 px-2 py-0.5 text-xs text-amber-700">
                    {[q.exam, q.year].filter(Boolean).join(" · ")}
                  </span>
                )}
              </p>
              <AnswerInput q={q} value={answers[q.id]} onChange={(v) => setAnswers((a) => ({ ...a, [q.id]: v }))} />
            </div>
          ))}
          <div className="flex gap-3">
            <button type="button" className={primaryBtn} disabled={busy} onClick={() => void submit()}>
              {busy ? "Submitting…" : "Submit"}
            </button>
            <button type="button" className={ghostBtn} onClick={() => setView("config")}>Cancel</button>
          </div>
        </div>
      )}

      {view === "score" && score && (
        <div className="flex flex-col gap-4">
          <div className="rounded-xl border bg-card p-5 text-center shadow-sm">
            <p className="text-4xl font-bold text-primary">{score.score} / {score.total}</p>
            <p className="mt-1 text-sm text-muted-foreground">
              {score.correct} of {score.count} correct · {score.total > 0 ? Math.round((score.score / score.total) * 100) : 0}%
            </p>
          </div>
          {score.results.map((r, i) => (
            <div key={r.question_id} className={`rounded-xl border p-4 shadow-sm ${r.is_correct ? "border-emerald-200 bg-emerald-50/50" : "border-red-200 bg-red-50/40"}`}>
              <p className="mb-2 font-medium"><span className="mr-2 text-muted-foreground">Q{i + 1}.</span>{r.question_text}</p>
              <p className="text-sm"><span className="text-muted-foreground">Your answer: </span>{formatAnswerValue(r.student_answer)} {r.is_correct ? "✓" : "✗"}</p>
              {!r.is_correct && <p className="text-sm text-emerald-700"><span className="text-muted-foreground">Correct: </span>{formatAnswerValue(r.correct_answer)}</p>}
              {r.explanation && <p className="mt-1 text-sm text-muted-foreground">{r.explanation}</p>}
            </div>
          ))}
          <div className="flex gap-3">
            <button type="button" className={primaryBtn} onClick={() => subject && void openSubject(subject)}>New set</button>
            <button type="button" className={ghostBtn} onClick={() => setView("subjects")}>All subjects</button>
          </div>
        </div>
      )}
    </div>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return (
    <p className="rounded-xl border border-dashed bg-card/60 p-6 text-center text-sm text-muted-foreground">
      {children}
    </p>
  );
}

function AnswerInput({
  q,
  value,
  onChange,
}: {
  q: PaperTakeQuestion;
  value: unknown;
  onChange: (v: unknown) => void;
}) {
  if (q.type === "mcq_single" || q.type === "true_false") {
    return (
      <div className="flex flex-col gap-1.5">
        {(q.options || []).map((o) => (
          <label key={o.id} className={`flex cursor-pointer items-center gap-3 rounded-md border px-3 py-2.5 ${value === o.id ? "border-primary bg-primary/5" : "border-input hover:bg-accent"}`}>
            <input type="radio" name={q.id} checked={value === o.id} onChange={() => onChange(o.id)} className="h-4 w-4 accent-primary" />
            <span>{o.text}</span>
          </label>
        ))}
      </div>
    );
  }
  if (q.type === "mcq_multi") {
    const arr = Array.isArray(value) ? (value as string[]) : [];
    return (
      <div className="flex flex-col gap-1.5">
        {(q.options || []).map((o) => (
          <label key={o.id} className={`flex cursor-pointer items-center gap-3 rounded-md border px-3 py-2.5 ${arr.includes(o.id) ? "border-primary bg-primary/5" : "border-input hover:bg-accent"}`}>
            <input
              type="checkbox"
              checked={arr.includes(o.id)}
              onChange={() => onChange(arr.includes(o.id) ? arr.filter((x) => x !== o.id) : [...arr, o.id])}
              className="h-4 w-4 accent-primary"
            />
            <span>{o.text}</span>
          </label>
        ))}
      </div>
    );
  }
  if (q.type === "descriptive") {
    return (
      <textarea
        className={`${field} min-h-28 py-2`}
        maxLength={2000}
        value={(value as string) ?? ""}
        onChange={(e) => onChange(e.target.value)}
        placeholder="Write your answer…"
      />
    );
  }
  return (
    <input
      className={field}
      type={q.type === "numerical" ? "number" : "text"}
      value={(value as string) ?? ""}
      onChange={(e) => onChange(e.target.value)}
      placeholder="Your answer"
    />
  );
}
