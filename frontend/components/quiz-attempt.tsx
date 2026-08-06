"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  AttemptResult,
  AttemptState,
  ResultQuestion,
  TakingQuestion,
  getAttempt,
  submitAttempt,
} from "@/lib/api";

export function QuizAttempt({ attemptId }: { attemptId: string }) {
  const [state, setState] = useState<AttemptState | null>(null);
  const [answers, setAnswers] = useState<Record<string, unknown>>({});
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    getAttempt(attemptId)
      .then(setState)
      .catch((e) => setError(e.message));
  }, [attemptId]);

  if (error) return <p className="text-red-600">{error}</p>;
  if (!state) return <p className="text-muted-foreground">Loading…</p>;

  if (state.status === "graded") {
    return <Results result={state as AttemptResult} />;
  }

  const questions = (state as { questions: TakingQuestion[] }).questions;

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

  async function handleSubmit() {
    setSubmitting(true);
    setError(null);
    try {
      const payload = questions.map((q) => {
        let val = answers[q.id];
        if (q.type === "numerical" && val !== undefined && val !== "") {
          val = Number(val);
        }
        return { question_id: q.id, student_answer: val ?? null };
      });
      setState(await submitAttempt(attemptId, payload));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Submit failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      {questions.map((q, i) => (
        <div key={q.id} className="rounded-md border p-4 text-sm">
          <p className="mb-2 font-medium">
            Q{i + 1}. {q.question_text}
          </p>
          <QuestionInput
            q={q}
            value={answers[q.id]}
            onChange={(v) => setAnswer(q.id, v)}
            onToggleMulti={(id) => toggleMulti(q.id, id)}
          />
        </div>
      ))}
      {error && <p className="text-red-600">{error}</p>}
      <div>
        <Button onClick={handleSubmit} disabled={submitting}>
          {submitting ? "Submitting…" : "Submit quiz"}
        </Button>
      </div>
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
      <div className="flex flex-col gap-1">
        {(q.options || []).map((o) => (
          <label key={o.id} className="flex items-center gap-2">
            <input
              type="radio"
              name={q.id}
              checked={value === o.id}
              onChange={() => onChange(o.id)}
            />
            {o.text}
          </label>
        ))}
      </div>
    );
  }
  if (q.type === "mcq_multi") {
    const arr = Array.isArray(value) ? (value as string[]) : [];
    return (
      <div className="flex flex-col gap-1">
        {(q.options || []).map((o) => (
          <label key={o.id} className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={arr.includes(o.id)}
              onChange={() => onToggleMulti(o.id)}
            />
            {o.text}
          </label>
        ))}
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
  return (
    <div className="flex flex-col gap-4">
      <div className="rounded-md border bg-muted/40 p-4">
        <p className="text-lg font-semibold">
          Score: {result.total_score} / {result.max_score}
        </p>
      </div>
      {result.results.map((q, i) => (
        <div
          key={q.id}
          className={`rounded-md border p-4 text-sm ${
            q.is_correct ? "border-green-300" : "border-red-300"
          }`}
        >
          <div className="mb-1 flex items-center justify-between">
            <span className="font-medium">Q{i + 1}</span>
            <span className={q.is_correct ? "text-green-700" : "text-red-700"}>
              {q.is_correct ? "✓ Correct" : "✗ Incorrect"}
            </span>
          </div>
          <p className="mb-1">{q.question_text}</p>
          <p className="text-muted-foreground">
            Your answer: {formatVal(q.student_answer)}
          </p>
          {!q.is_correct && (
            <p className="text-green-700">Correct: {formatAnswer(q)}</p>
          )}
          {q.explanation && (
            <p className="mt-1 text-muted-foreground">Why: {q.explanation}</p>
          )}
        </div>
      ))}
      <div>
        <Link href="/dashboard/student" className="text-sm underline">
          ← Back to quizzes
        </Link>
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
