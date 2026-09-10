"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useSWRConfig } from "swr";

import { AiTutor } from "@/components/student/ai-tutor";
import { StudentDownloads } from "@/components/shared/pdf-buttons";
import { downloadCardImage } from "@/lib/share-card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ErrorCard } from "@/components/ui/error-card";
import { Skeleton } from "@/components/ui/skeleton";
import { Check, X } from "@/components/ui/icons";
import { formatAnswerValue, typeLabel } from "@/lib/format";
import {
  AttemptInProgress,
  AttemptResult,
  AttemptState,
  TakingQuestion,
  addBookmark,
  consumePrimedAttemptState,
  getAttempt,
  getPracticeSession,
  saveAttemptProgress,
  savePracticeProgress,
  submitAttempt,
  submitPracticeSession,
} from "@/lib/api";
import {
  STUDENT_ATTEMPTS_KEY,
  STUDENT_BOOKMARKS_KEY,
  STUDENT_CHALLENGE_KEY_PREFIX,
  STUDENT_DAILY_KEY,
  STUDENT_LEADERBOARD_KEY_PREFIX,
  STUDENT_QUIZZES_KEY,
  STUDENT_REVISION_TOPICS_KEY,
  STUDENT_STATS_KEY,
  STUDENT_WEAK_ANALYSIS_KEY,
} from "@/lib/student-queries";

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
  const { mutate: mutateCache } = useSWRConfig();
  const [state, setState] = useState<AttemptState | null>(null);
  const [answers, setAnswers] = useState<Record<string, unknown>>({});
  const [current, setCurrent] = useState(0);
  const [marked, setMarked] = useState<Record<string, boolean>>({});
  const [error, setError] = useState<string | null>(null);
  const [autosaveError, setAutosaveError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const loadedAttemptKey = useRef<string | null>(null);
  const answerRevision = useRef(0);
  const savedAnswerRevision = useRef(0);

  function load() {
    setError(null);
    const primed = consumePrimedAttemptState(attemptId);
    if (primed) {
      setState(primed);
      if (primed.status === "in_progress") {
        setAnswers((primed as AttemptInProgress).autosave_state ?? {});
        answerRevision.current = 0;
        savedAnswerRevision.current = 0;
      }
      return;
    }
    const fetcher = source === "practice" ? getPracticeSession : getAttempt;
    fetcher(attemptId)
      .then((next) => {
        setState(next);
        if (next.status === "in_progress") {
          setAnswers((next as AttemptInProgress).autosave_state ?? {});
          answerRevision.current = 0;
          savedAnswerRevision.current = 0;
        }
      })
      .catch((e) => setError(e.message));
  }

  useEffect(() => {
    const key = `${source}:${attemptId}`;
    if (loadedAttemptKey.current === key) return;
    loadedAttemptKey.current = key;
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [attemptId, source]);

  useEffect(() => {
    if (!state || state.status !== "in_progress") return;
    if (answerRevision.current === savedAnswerRevision.current) return;
    const revisionToSave = answerRevision.current;
    const timer = window.setTimeout(() => {
      const saver = source === "practice" ? savePracticeProgress : saveAttemptProgress;
      saver(attemptId, answers)
        .then(() => {
          savedAnswerRevision.current = revisionToSave;
          setAutosaveError(null);
        })
        .catch(() =>
          setAutosaveError(
            "Progress could not be saved. Keep this page open and check your connection.",
          ),
        );
    }, 600);
    return () => window.clearTimeout(timer);
  }, [answers, attemptId, source, state]);

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

  if (error && !state) return <ErrorCard message={error} onRetry={load} />;
  if (!state) return <QuestionPanelSkeleton />;
  if (state.status === "graded") {
    return <Results result={state as AttemptResult} />;
  }

  const questions = (state as { questions: TakingQuestion[] }).questions;
  if (questions.length === 0) {
    return (
      <ErrorCard message="This quiz has no available questions. Please return to the dashboard and choose another quiz." />
    );
  }
  const q = questions[current];
  const answeredCount = questions.filter((x) => isAnswered(answers[x.id])).length;

  function setAnswer(qid: string, val: unknown) {
    answerRevision.current += 1;
    setAnswers((a) => ({ ...a, [qid]: val }));
  }
  function toggleMulti(qid: string, id: string) {
    answerRevision.current += 1;
    setAnswers((a) => {
      const cur = Array.isArray(a[qid]) ? (a[qid] as string[]) : [];
      return {
        ...a,
        [qid]: cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id],
      };
    });
  }
  function clearAnswer(qid: string) {
    answerRevision.current += 1;
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
      const result = await submit(attemptId, payload);
      setState(result);
      // Grading changes every student summary derived from attempt results.
      // Evict them without issuing requests while the results page is visible;
      // their next mount will reload fresh data once.
      await Promise.all([
        mutateCache(STUDENT_QUIZZES_KEY, undefined, { revalidate: false }),
        mutateCache(STUDENT_STATS_KEY, undefined, { revalidate: false }),
        mutateCache(STUDENT_ATTEMPTS_KEY, undefined, { revalidate: false }),
        mutateCache(STUDENT_WEAK_ANALYSIS_KEY, undefined, { revalidate: false }),
        mutateCache(STUDENT_REVISION_TOPICS_KEY, undefined, { revalidate: false }),
        mutateCache(STUDENT_DAILY_KEY, undefined, { revalidate: false }),
        mutateCache(
          (key) =>
            typeof key === "string" &&
            (key.startsWith(STUDENT_LEADERBOARD_KEY_PREFIX) ||
              key.startsWith(STUDENT_CHALLENGE_KEY_PREFIX)),
          undefined,
          { revalidate: false },
        ),
      ]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Submit failed");
    } finally {
      setSubmitting(false);
    }
  }

  submitRef.current = handleSubmit; // keep the timer's submit reference fresh

  const atLast = current === questions.length - 1;
  const paletteLayout = getPaletteLayout(questions.length);

  return (
    <div className={`grid gap-4 lg:items-start ${paletteLayout.pageColumns}`}>
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
            <Badge tone="type">{typeLabel(q.type)}</Badge>
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
        {autosaveError && (
          <p className="text-sm text-amber-700">{autosaveError}</p>
        )}
        {error && <p className="text-sm text-red-600">{error}</p>}
      </div>

      {/* Question palette — attempted / current / remaining */}
      <aside className="w-full lg:sticky lg:top-0">
        <div className="rounded-lg border bg-card p-3 shadow-sm sm:p-4">
          <div className="mb-2 flex items-center justify-between gap-3">
            <p className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground">
              Questions
            </p>
            <span className="text-xs font-medium text-muted-foreground">
              {current + 1} / {questions.length}
            </span>
          </div>
          <div
            className={`grid grid-cols-8 gap-1.5 sm:grid-cols-10 ${paletteLayout.paletteColumns}`}
          >
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
                  aria-label={`Go to question ${i + 1}${ans ? ", answered" : ""}${mk ? ", marked for review" : ""}`}
                  aria-current={cur ? "step" : undefined}
                  className={`flex h-8 min-w-0 items-center justify-center rounded-md text-xs font-medium transition ${base} ${
                    cur ? "ring-2 ring-brand-600 ring-offset-1" : ""
                  }`}
                >
                  {i + 1}
                </button>
              );
            })}
          </div>

          <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5 text-[11px] text-muted-foreground">
            <Legend cls="bg-emerald-500" label="Answered" />
            <Legend cls="bg-muted" label="Not answered" />
            <Legend cls="bg-violet-500" label="Marked for review" />
          </div>

          <div className="mt-3 flex items-center gap-2 border-t pt-3">
            <div className="min-w-0 flex-1 rounded-md bg-muted px-2 py-2 text-center text-xs text-muted-foreground">
              <span className="font-semibold text-primary">{answeredCount}</span> /{" "}
              {questions.length} answered
            </div>
            <Button
              className="shrink-0"
              size="sm"
              onClick={handleSubmit}
              disabled={submitting}
            >
              {submitting ? "Submitting…" : "Submit quiz"}
            </Button>
          </div>
        </div>
      </aside>
    </div>
  );
}

/** First-paint placeholder mirroring the question panel + palette layout. */
function QuestionPanelSkeleton() {
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(20rem,22rem)] lg:items-start">
      <div className="flex min-w-0 flex-1 flex-col gap-4">
        <div className="flex items-center justify-between">
          <Skeleton className="h-5 w-32" />
          <Skeleton className="h-5 w-24" />
        </div>
        <div className="rounded-lg border bg-card p-5 shadow-sm">
          <div className="mb-3 flex items-center justify-between">
            <Skeleton className="h-5 w-10" />
            <Skeleton className="h-5 w-20 rounded-full" />
          </div>
          <Skeleton className="mb-4 h-5 w-3/4" />
          <div className="flex flex-col gap-2">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-11 w-full rounded-md" />
            ))}
          </div>
          <div className="mt-6 flex items-center gap-2 border-t pt-4">
            <Skeleton className="h-8 w-24" />
            <Skeleton className="ml-auto h-8 w-24" />
          </div>
        </div>
      </div>
      <aside className="w-full lg:sticky lg:top-0">
        <Skeleton className="h-[28rem] w-full rounded-lg" />
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

/**
 * Keep small quizzes visually compact while reserving enough palette space for
 * large exams. Static class strings are intentional so Tailwind can discover
 * every responsive variant during the production build.
 */
function getPaletteLayout(questionCount: number) {
  if (questionCount <= 5) {
    return {
      pageColumns: "lg:grid-cols-[minmax(0,1fr)_14rem]",
      paletteColumns: "lg:grid-cols-5",
    };
  }
  if (questionCount <= 20) {
    return {
      pageColumns: "lg:grid-cols-[minmax(0,1fr)_16rem]",
      paletteColumns: "lg:grid-cols-5",
    };
  }
  if (questionCount <= 50) {
    return {
      pageColumns: "lg:grid-cols-[minmax(0,1fr)_20rem]",
      paletteColumns: "lg:grid-cols-8",
    };
  }
  return {
    pageColumns: "lg:grid-cols-[minmax(0,1fr)_minmax(20rem,22rem)]",
    paletteColumns: "lg:grid-cols-10",
  };
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
          score={result.total_score}
          maxScore={result.max_score}
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
                className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${
                  q.is_correct
                    ? "bg-emerald-100 text-emerald-700"
                    : "bg-rose-100 text-rose-700"
                }`}
              >
                {q.is_correct ? <Check size={13} /> : <X size={13} />}
                {q.is_correct ? "Correct" : "Incorrect"}
              </span>
            </div>
          </div>
          <p className="mb-3">{q.question_text}</p>

          <div className="flex flex-col divide-y divide-border rounded-md border bg-muted/30">
            <div className="flex flex-wrap gap-x-2 px-3 py-2">
              <span className="shrink-0 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Your answer
              </span>
              <span className="text-foreground">
                {formatAnswerValue(q.student_answer)}
              </span>
            </div>
            {!q.is_correct && (
              <div className="flex flex-wrap gap-x-2 px-3 py-2">
                <span className="shrink-0 text-xs font-semibold uppercase tracking-wide text-emerald-600">
                  Correct answer
                </span>
                <span className="font-medium text-emerald-700">
                  {formatAnswerValue(q.correct_answer)}
                </span>
              </div>
            )}
            {q.explanation && (
              <div className="flex flex-wrap gap-x-2 px-3 py-2">
                <span className="shrink-0 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Why
                </span>
                <span className="text-muted-foreground">{q.explanation}</span>
              </div>
            )}
          </div>
          <AiTutor questionId={q.id} />
        </div>
      ))}
    </div>
  );
}

/** "Save to revision" toggle — adds the question to the student's bookmark list. */
function BookmarkButton({ questionId }: { questionId: string }) {
  const { mutate: mutateCache } = useSWRConfig();
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  async function save() {
    if (saved || busy) return;
    setBusy(true);
    setFailed(false);
    try {
      await addBookmark(questionId);
      setSaved(true);
      await mutateCache(STUDENT_BOOKMARKS_KEY, undefined, { revalidate: false });
    } catch {
      setFailed(true);
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
      {saved ? "★ Saved" : failed ? "Retry save" : "☆ Revise"}
    </button>
  );
}

/** Score → a verdict word + accent colour (tuned to how well they did). */
function verdict(pct: number): { word: string; tone: string } {
  if (pct >= 90) return { word: "Outstanding!", tone: "#34d399" };
  if (pct >= 75) return { word: "Excellent!", tone: "#34d399" };
  if (pct >= 60) return { word: "Great job!", tone: "#7ae582" };
  if (pct >= 40) return { word: "Good effort", tone: "#e6a817" };
  return { word: "Keep practising", tone: "#60a5fa" };
}

/** Animated SVG progress ring with the percentage in the centre. */
function ScoreRing({ pct, tone }: { pct: number; tone: string }) {
  const r = 60;
  const circ = 2 * Math.PI * r;
  return (
    <div className="relative mx-auto h-[140px] w-[140px]">
      <svg width="140" height="140" viewBox="0 0 140 140">
        <circle
          cx="70"
          cy="70"
          r={r}
          fill="none"
          stroke="rgba(255,255,255,0.12)"
          strokeWidth="12"
        />
        <circle
          cx="70"
          cy="70"
          r={r}
          fill="none"
          stroke={tone}
          strokeWidth="12"
          strokeLinecap="round"
          strokeDasharray={circ}
          strokeDashoffset={circ * (1 - Math.min(100, Math.max(0, pct)) / 100)}
          transform="rotate(-90 70 70)"
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-[40px] font-extrabold leading-none" style={{ color: tone }}>
          {pct}%
        </span>
        <span className="mt-1 text-[10px] uppercase tracking-widest text-white/40">
          score
        </span>
      </div>
    </div>
  );
}

function StatTile({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="rounded-xl bg-white/[0.06] px-3 py-2 text-center">
      <div className="text-lg font-bold" style={{ color: color ?? "#ffffff" }}>
        {value}
      </div>
      <div className="text-[9px] font-semibold uppercase tracking-widest text-white/40">
        {label}
      </div>
    </div>
  );
}

/** Branded, detailed, downloadable score card + WhatsApp share. */
function ScoreCard({
  title,
  pct,
  correct,
  total,
  score,
  maxScore,
  onClose,
}: {
  title: string;
  pct: number;
  correct: number;
  total: number;
  score: number;
  maxScore: number;
  onClose: () => void;
}) {
  const cardRef = useRef<HTMLDivElement>(null);
  const v = verdict(pct);
  const wrong = Math.max(0, total - correct);
  const shareText = `I scored ${pct}% on "${title}" with ArivuPro — can you beat me?`;
  const waHref = `https://wa.me/?text=${encodeURIComponent(shareText + " " + (typeof window !== "undefined" ? window.location.origin : ""))}`;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="flex max-h-full animate-rise flex-col items-center gap-3 overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        {/* The card that gets captured as the shareable image */}
        <div
          ref={cardRef}
          className="w-[340px] max-w-full overflow-hidden rounded-3xl p-7 text-center text-white shadow-2xl"
          style={{ background: "linear-gradient(150deg,#0f1f17,#17402a 55%,#0f1f17)" }}
        >
          <div className="text-sm font-black tracking-tight">
            Arivu<span style={{ color: "#7ae582" }}>PRO</span>
          </div>
          <div className="mt-1 truncate text-[11px] uppercase tracking-widest text-white/40">
            {title}
          </div>

          <div className="mt-4">
            <ScoreRing pct={pct} tone={v.tone} />
          </div>

          <div className="mt-3 text-xl font-extrabold" style={{ color: v.tone }}>
            {v.word}
          </div>

          <div className="mt-5 grid grid-cols-2 gap-2">
            <StatTile label="Correct" value={String(correct)} color="#7ae582" />
            <StatTile label="Wrong" value={String(wrong)} color="#ff8a94" />
            <StatTile label="Score" value={`${score}/${maxScore}`} />
            <StatTile label="Accuracy" value={`${pct}%`} />
          </div>

          <div className="mt-5 text-[10px] tracking-wide text-white/30">
            arivupro.com · practise smarter
          </div>
        </div>

        {/* Actions — outside the captured card */}
        <div className="flex w-[340px] max-w-full gap-2">
          <button
            onClick={() =>
              cardRef.current &&
              downloadCardImage(cardRef.current, `arivupro-score-${pct}.png`)
            }
            className="flex-1 rounded-lg bg-white/10 px-3 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-white/20"
          >
            Download
          </button>
          <a
            href={waHref}
            target="_blank"
            rel="noopener noreferrer"
            className="flex-1 rounded-lg bg-[#25D366] px-3 py-2.5 text-center text-sm font-semibold text-white transition-transform hover:-translate-y-0.5"
          >
            WhatsApp
          </a>
        </div>
        <button onClick={onClose} className="text-xs text-white/50 hover:text-white/80">
          Close
        </button>
      </div>
    </div>
  );
}
