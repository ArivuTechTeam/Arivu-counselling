"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";

import { AiTutor } from "@/components/ai-tutor";
import { StudentDownloads } from "@/components/pdf-buttons";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  AttemptInProgress,
  AttemptResult,
  AttemptState,
  ResultQuestion,
  TakingQuestion,
  addBookmark,
  getAttempt,
  getPracticeSession,
  submitAttempt,
  submitPracticeSession,
} from "@/lib/api";

function isAnswered(v: unknown): boolean {
  if (v === undefined || v === null || v === "") return false;
  if (Array.isArray(v)) return v.length > 0;
  return true;
}

function fmtTime(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export function QuizAttempt({
  attemptId,
  source = "quiz",
}: {
  attemptId: string;
  source?: "quiz" | "practice";
}) {
  const [state, setState] = useState<AttemptState | null>(null);
  const [answers, setAnswers] = useState<Record<string, unknown>>({});
  const [current, setCurrent] = useState(0);
  const [marked, setMarked] = useState<Record<string, boolean>>({});
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    const load = source === "practice" ? getPracticeSession : getAttempt;
    load(attemptId)
      .then(setState)
      .catch((e) => setError(e.message));
  }, [attemptId, source]);

  // Countdown for timed modes (exam). submitRef always points at the latest
  // handleSubmit so the timer auto-submits exactly once when the clock hits zero.
  const [remainingMs, setRemainingMs] = useState<number | null>(null);
  const submitRef = useRef<() => void>(() => {});
  const autoFiredRef = useRef(false);
  useEffect(() => {
    if (!state || state.status !== "in_progress") return;
    const s = state as AttemptInProgress;
    const lim = s.time_limit_minutes;
    const startedAt = s.started_at;
    if (!lim || !startedAt) return;
    const deadline = new Date(startedAt).getTime() + lim * 60_000;
    const tick = () => {
      const ms = deadline - Date.now();
      setRemainingMs(Math.max(0, ms));
      if (ms <= 0 && !autoFiredRef.current) {
        autoFiredRef.current = true;
        submitRef.current();
      }
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [state]);

  if (error) return <p className="text-red-600">{error}</p>;
  if (!state) return <p className="text-muted-foreground">Loading…</p>;
  if (state.status === "graded") {
    return <Results result={state as AttemptResult} />;
  }

  const questions = (state as { questions: TakingQuestion[] }).questions;
  const q = questions[current];
  const answeredCount = questions.filter((x) => isAnswered(answers[x.id])).length;

  function setAnswer(qid: string, val: unknown) {
    setAnswers((a) => ({ ...a, [qid]: val }));
  }
  function toggleMulti(qid: string, id: string) {
    setAnswers((a) => {
      const cur = Array.isArray(a[qid]) ? (a[qid] as string[]) : [];
      return {
        ...a,
        [qid]: cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id],
      };
    });
  }
  function clearAnswer(qid: string) {
    setAnswers((a) => {
      const n = { ...a };
      delete n[qid];
      return n;
    });
  }
  function toggleMark(qid: string) {
    setMarked((m) => ({ ...m, [qid]: !m[qid] }));
  }

  async function handleSubmit() {
    setSubmitting(true);
    setError(null);
    try {
      const payload = questions.map((qq) => {
        let val = answers[qq.id];
        if (qq.type === "numerical" && val !== undefined && val !== "") {
          val = Number(val);
        }
        return { question_id: qq.id, student_answer: val ?? null };
      });
      const submit =
        source === "practice" ? submitPracticeSession : submitAttempt;
      setState(await submit(attemptId, payload));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Submit failed");
    } finally {
      setSubmitting(false);
    }
  }

  submitRef.current = handleSubmit; // keep the timer's submit reference fresh

  const atLast = current === questions.length - 1;

  return (
    <div className="flex flex-col gap-5 lg:flex-row lg:items-start">
      {/* Question panel — one at a time */}
      <div className="flex min-w-0 flex-1 flex-col gap-4">
        <div className="flex items-center justify-between gap-3 text-sm">
          <span className="font-medium text-foreground">
            Question {current + 1}
            <span className="text-muted-foreground"> of {questions.length}</span>
          </span>
          <div className="flex items-center gap-3">
            {remainingMs !== null && (
              <span
                className={`rounded-md border px-2.5 py-1 font-semibold tabular-nums ${
                  remainingMs <= 60_000
                    ? "border-rose-300 bg-rose-50 text-rose-700"
                    : remainingMs <= 300_000
                      ? "border-amber-300 bg-amber-50 text-amber-700"
                      : "border-input bg-muted text-foreground"
                }`}
              >
                {fmtTime(remainingMs)}
              </span>
            )}
            <span className="text-muted-foreground">{answeredCount} answered</span>
          </div>
        </div>

        <div className="rounded-lg border bg-card p-5 shadow-sm">
          <div className="mb-3 flex items-center justify-between">
            <span className="font-semibold">Q{current + 1}</span>
            <Badge tone="type">{q.type}</Badge>
          </div>
          <p className="mb-4 text-[15px] text-foreground">{q.question_text}</p>
          <QuestionInput
            q={q}
            value={answers[q.id]}
            onChange={(v) => setAnswer(q.id, v)}
            onToggleMulti={(id) => toggleMulti(q.id, id)}
          />

          <div className="mt-6 flex flex-wrap items-center gap-2 border-t pt-4">
            <Button
              variant="outline"
              size="sm"
              disabled={current === 0}
              onClick={() => setCurrent((c) => Math.max(0, c - 1))}
            >
              ← Previous
            </Button>
            <Button variant="ghost" size="sm" onClick={() => toggleMark(q.id)}>
              {marked[q.id] ? "Unmark" : "Mark for review"}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              disabled={!isAnswered(answers[q.id])}
              onClick={() => clearAnswer(q.id)}
            >
              Clear
            </Button>
            <div className="ml-auto">
              {atLast ? (
                <Button size="sm" onClick={handleSubmit} disabled={submitting}>
                  {submitting ? "Submitting…" : "Submit quiz"}
                </Button>
              ) : (
                <Button size="sm" onClick={() => setCurrent((c) => c + 1)}>
                  Next →
                </Button>
              )}
            </div>
          </div>
        </div>
        {error && <p className="text-sm text-red-600">{error}</p>}
      </div>

      {/* Question palette — attempted / current / remaining */}
      <aside className="w-full shrink-0 lg:w-64">
        <div className="rounded-lg border bg-card p-4 shadow-sm">
          <p className="mb-3 text-[11px] font-semibold uppercase tracking-widest text-muted-foreground">
            Questions
          </p>
          <div className="grid grid-cols-6 gap-2 lg:grid-cols-5">
            {questions.map((qq, i) => {
              const ans = isAnswered(answers[qq.id]);
              const mk = marked[qq.id];
              const cur = i === current;
              const base = mk
                ? "bg-violet-500 text-white"
                : ans
                  ? "bg-emerald-500 text-white"
                  : "bg-muted text-muted-foreground hover:bg-accent";
              return (
                <button
                  key={qq.id}
                  type="button"
                  onClick={() => setCurrent(i)}
                  className={`flex h-9 w-9 items-center justify-center rounded-md text-sm font-medium transition ${base} ${
                    cur ? "ring-2 ring-brand-600 ring-offset-1" : ""
                  }`}
                >
                  {i + 1}
                </button>
              );
            })}
          </div>

          <div className="mt-4 flex flex-col gap-1.5 text-xs text-muted-foreground">
            <Legend cls="bg-emerald-500" label="Answered" />
            <Legend cls="bg-muted" label="Not answered" />
            <Legend cls="bg-violet-500" label="Marked for review" />
          </div>

          <div className="mt-4 rounded-md bg-muted p-2 text-center text-xs text-muted-foreground">
            <span className="font-semibold text-primary">{answeredCount}</span> /{" "}
            {questions.length} answered
          </div>

          <Button
            className="mt-3 w-full"
            size="sm"
            onClick={handleSubmit}
            disabled={submitting}
          >
            {submitting ? "Submitting…" : "Submit quiz"}
          </Button>
        </div>
      </aside>
    </div>
  );
}

function Legend({ cls, label }: { cls: string; label: string }) {
  return (
    <div className="flex items-center gap-2">
      <span className={`h-3 w-3 rounded ${cls}`} />
      {label}
    </div>
  );
}

function QuestionInput({
  q,
  value,
  onChange,
  onToggleMulti,
}: {
  q: TakingQuestion;
  value: unknown;
  onChange: (v: unknown) => void;
  onToggleMulti: (id: string) => void;
}) {
  if (q.type === "mcq_single" || q.type === "true_false") {
    return (
      <div className="flex flex-col gap-1.5">
        {(q.options || []).map((o) => {
          const selected = value === o.id;
          return (
            <label
              key={o.id}
              className={`flex cursor-pointer items-center gap-3 rounded-md border px-3 py-2.5 transition-colors ${
                selected
                  ? "border-primary bg-primary/5"
                  : "border-input hover:bg-accent"
              }`}
            >
              <input
                type="radio"
                name={q.id}
                checked={selected}
                onChange={() => onChange(o.id)}
                className="h-4 w-4 accent-primary"
              />
              {o.id.length <= 1 && (
                <span className="font-mono text-xs text-muted-foreground">
                  {o.id}
                </span>
              )}
              <span className="flex-1">{o.text}</span>
            </label>
          );
        })}
      </div>
    );
  }
  if (q.type === "mcq_multi") {
    const arr = Array.isArray(value) ? (value as string[]) : [];
    return (
      <div className="flex flex-col gap-1.5">
        {(q.options || []).map((o) => {
          const selected = arr.includes(o.id);
          return (
            <label
              key={o.id}
              className={`flex cursor-pointer items-center gap-3 rounded-md border px-3 py-2.5 transition-colors ${
                selected
                  ? "border-primary bg-primary/5"
                  : "border-input hover:bg-accent"
              }`}
            >
              <input
                type="checkbox"
                checked={selected}
                onChange={() => onToggleMulti(o.id)}
                className="h-4 w-4 accent-primary"
              />
              {o.id.length <= 1 && (
                <span className="font-mono text-xs text-muted-foreground">
                  {o.id}
                </span>
              )}
              <span className="flex-1">{o.text}</span>
            </label>
          );
        })}
      </div>
    );
  }
  if (q.type === "numerical") {
    return (
      <Input
        type="number"
        value={(value as string) ?? ""}
        onChange={(e) => onChange(e.target.value)}
        placeholder="Your numeric answer"
      />
    );
  }
  // fill_blank
  return (
    <Input
      value={(value as string) ?? ""}
      onChange={(e) => onChange(e.target.value)}
      placeholder="Type your answer"
    />
  );
}

function Results({ result }: { result: AttemptResult }) {
  const [showCard, setShowCard] = useState(false);
  const correct = result.results.filter((q) => q.is_correct).length;
  const pct =
    result.max_score > 0
      ? Math.round((result.total_score / result.max_score) * 100)
      : 0;

  return (
    <div className="flex flex-col gap-4">
      <Link
        href="/dashboard/student"
        className="inline-flex w-fit items-center gap-1 text-sm text-muted-foreground transition-colors hover:text-foreground"
      >
        ← Back to dashboard
      </Link>
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border bg-card p-5 shadow-sm">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground">
            Your score
          </div>
          <div className="mt-1 text-3xl font-bold tracking-tight text-primary">
            {result.total_score} / {result.max_score}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            onClick={() => setShowCard(true)}
            className="rounded-md bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground shadow-sm transition-colors hover:bg-primary/90"
          >
            Share result
          </button>
          <StudentDownloads
            quizTitle={result.quiz_title ?? "Quiz"}
            score={result.total_score}
            maxScore={result.max_score}
            results={result.results}
          />
        </div>
      </div>

      {result.challenge_token && (
        <Link
          href={`/dashboard/student/challenge/${result.challenge_token}`}
          className="flex items-center justify-between gap-3 rounded-lg border border-primary/30 bg-primary/5 px-5 py-4 text-sm font-semibold text-primary transition-colors hover:bg-primary/10"
        >
          See the leaderboard &amp; challenge a friend
          <span>→</span>
        </Link>
      )}

      {showCard && (
        <ScoreCard
          title={result.quiz_title ?? "Quiz"}
          pct={pct}
          correct={correct}
          total={result.results.length}
          onClose={() => setShowCard(false)}
        />
      )}

      {result.results.map((q, i) => (
        <div
          key={q.id}
          className={`rounded-md border bg-card p-4 text-sm ${
            q.is_correct ? "border-emerald-300" : "border-rose-300"
          }`}
        >
          <div className="mb-2 flex items-center justify-between gap-2">
            <span className="font-semibold">Q{i + 1}</span>
            <div className="flex items-center gap-2">
              <BookmarkButton questionId={q.id} />
              <span
                className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                  q.is_correct
                    ? "bg-emerald-100 text-emerald-700"
                    : "bg-rose-100 text-rose-700"
                }`}
              >
                {q.is_correct ? "✓ Correct" : "✗ Incorrect"}
              </span>
            </div>
          </div>
          <p className="mb-1">{q.question_text}</p>
          <p className="text-muted-foreground">
            Your answer: {formatVal(q.student_answer)}
          </p>
          {!q.is_correct && (
            <p className="font-medium text-emerald-700">
              Correct: {formatAnswer(q)}
            </p>
          )}
          {q.explanation && (
            <p className="mt-1 text-muted-foreground">Why: {q.explanation}</p>
          )}
          <AiTutor questionId={q.id} />
        </div>
      ))}
    </div>
  );
}

/** "Save to revision" toggle — adds the question to the student's bookmark list. */
function BookmarkButton({ questionId }: { questionId: string }) {
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  async function save() {
    if (saved || busy) return;
    setBusy(true);
    try {
      await addBookmark(questionId);
      setSaved(true);
    } catch {
      /* non-critical — ignore */
    } finally {
      setBusy(false);
    }
  }
  return (
    <button
      onClick={save}
      disabled={saved || busy}
      className={`rounded-full border px-2 py-0.5 text-xs font-medium transition-colors ${
        saved
          ? "border-primary/40 bg-primary/10 text-primary"
          : "border-input text-muted-foreground hover:border-primary/40 hover:text-primary"
      }`}
    >
      {saved ? "★ Saved" : "☆ Revise"}
    </button>
  );
}

/** Branded, shareable score card with a WhatsApp share link. */
function ScoreCard({
  title,
  pct,
  correct,
  total,
  onClose,
}: {
  title: string;
  pct: number;
  correct: number;
  total: number;
  onClose: () => void;
}) {
  const tone = pct >= 70 ? "#34d399" : pct >= 40 ? "#e6a817" : "#60a5fa";
  const shareText = `I scored ${pct}% (${correct}/${total}) on "${title}" with ArivuPro! Practice for your exam here:`;
  const waHref = `https://wa.me/?text=${encodeURIComponent(shareText + " " + (typeof window !== "undefined" ? window.location.origin : ""))}`;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="animate-rise w-[360px] max-w-full rounded-2xl bg-gradient-to-br from-[#0f1f17] to-[#1a3a25] p-8 text-center text-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="text-[11px] uppercase tracking-widest text-white/50">
          {title}
        </div>
        <div
          className="mx-auto mt-4 flex h-28 w-28 flex-col items-center justify-center rounded-full text-4xl font-extrabold"
          style={{ border: `4px solid ${tone}`, color: tone }}
        >
          {pct}%
        </div>
        <div className="mt-5 flex justify-center gap-8">
          <div>
            <div className="text-lg font-bold">{correct}</div>
            <div className="text-[10px] uppercase tracking-wide text-white/40">
              Correct
            </div>
          </div>
          <div>
            <div className="text-lg font-bold">{total}</div>
            <div className="text-[10px] uppercase tracking-wide text-white/40">
              Questions
            </div>
          </div>
        </div>
        <a
          href={waHref}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-6 inline-flex w-full items-center justify-center gap-2 rounded-lg bg-[#25D366] px-4 py-2.5 text-sm font-semibold text-white transition-transform hover:-translate-y-0.5"
        >
          Share on WhatsApp
        </a>
        <button
          onClick={onClose}
          className="mt-3 text-xs text-white/50 hover:text-white/80"
        >
          Close
        </button>
      </div>
    </div>
  );
}

function formatVal(v: unknown): string {
  if (v === null || v === undefined || v === "") return "(no answer)";
  if (Array.isArray(v)) return v.join(", ");
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

function formatAnswer(q: ResultQuestion): string {
  const a = q.correct_answer;
  if (Array.isArray(a)) return a.join(", ");
  if (a && typeof a === "object") {
    const o = a as Record<string, unknown>;
    if ("value" in o) return `${o.value}${o.tolerance ? ` (±${o.tolerance})` : ""}`;
    if ("answers" in o) return (o.answers as string[]).join(" / ");
    return JSON.stringify(o);
  }
  return String(a);
}
