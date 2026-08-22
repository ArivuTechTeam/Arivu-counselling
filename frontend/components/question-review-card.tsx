"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  QuestionPatch,
  ReviewQuestion,
  approveQuestion,
  editQuestion,
  regenerateQuestion,
  rejectQuestion,
} from "@/lib/api";

const CHOICE_TYPES = ["mcq_single", "mcq_multi", "true_false"];

function correctIds(q: ReviewQuestion): string[] {
  const a = q.correct_answer;
  if (Array.isArray(a)) return a.map(String);
  if (typeof a === "string") return [a];
  return [];
}

function formatAnswer(q: ReviewQuestion): string {
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

// Status tones from the design system: emerald = approved, rose = rejected,
// amber = needs_edit, warm-neutral = pending. Strings render exactly as the API
// returns them (lowercase, snake_cased) — no prettifying.
const STATUS_TONE: Record<string, string> = {
  approved: "bg-emerald-100 text-emerald-700",
  rejected: "bg-rose-100 text-rose-700",
  needs_edit: "bg-amber-100 text-amber-700",
  pending_review: "bg-muted text-muted-foreground",
};

function StatusBadge({ status }: { status: string }) {
  const tone = STATUS_TONE[status] ?? "bg-muted text-muted-foreground";
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${tone}`}>
      {status}
    </span>
  );
}

// Left-edge accent strip colour, keyed to review status (design-system tones).
const ACCENT: Record<string, string> = {
  approved: "#16a34a",
  rejected: "#f43f5e",
  needs_edit: "#f59e0b",
  pending_review: "#cbd5e1",
};

// Difficulty pill tones. Only the values the API actually emits.
const DIFFICULTY_TONE: Record<string, string> = {
  easy: "border-emerald-200 bg-emerald-50 text-emerald-700",
  medium: "border-amber-200 bg-amber-50 text-amber-700",
  hard: "border-rose-200 bg-rose-50 text-rose-700",
};

// Friendly labels for the snake_cased question types (display only).
const TYPE_LABEL: Record<string, string> = {
  mcq_single: "Single choice",
  mcq_multi: "Multiple choice",
  true_false: "True / False",
  numerical: "Numerical",
  fill_blank: "Fill in the blank",
  matching: "Matching",
};

function CheckIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <polyline points="20 6 9 17 4 12" />
    </svg>
  );
}

export function QuestionReviewCard({
  index,
  question,
  onChange,
}: {
  index: number;
  question: ReviewQuestion;
  onChange: (q: ReviewQuestion) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function run(label: string, fn: () => Promise<ReviewQuestion>) {
    setError(null);
    setBusy(label);
    try {
      onChange(await fn());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Action failed");
    } finally {
      setBusy(null);
    }
  }

  const correct = correctIds(question);

  const accent = ACCENT[question.review_status] ?? "#cbd5e1";

  return (
    <div className="relative overflow-hidden rounded-xl border bg-card pl-5 pr-4 py-4 text-sm shadow-sm transition-shadow hover:shadow-md">
      {/* status accent strip */}
      <span
        className="absolute inset-y-0 left-0 w-1.5"
        style={{ background: accent }}
        aria-hidden="true"
      />

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <span className="flex h-7 w-7 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary">
          {index + 1}
        </span>
        <span className="rounded-full border border-border bg-muted px-2.5 py-0.5 text-xs font-medium text-muted-foreground">
          {TYPE_LABEL[question.type] ?? question.type}
        </span>
        {question.difficulty && (
          <span
            className={`rounded-full border px-2.5 py-0.5 text-xs font-medium capitalize ${
              DIFFICULTY_TONE[question.difficulty] ??
              "border-border bg-muted text-muted-foreground"
            }`}
          >
            {question.difficulty}
          </span>
        )}
        {question.marks != null && (
          <span className="rounded-full border border-border bg-muted px-2.5 py-0.5 text-xs font-medium text-muted-foreground">
            {question.marks} {question.marks === 1 ? "mark" : "marks"}
          </span>
        )}
        <span className="ml-auto">
          <StatusBadge status={question.review_status} />
        </span>
      </div>

      {editing ? (
        <EditForm
          question={question}
          onCancel={() => setEditing(false)}
          onSaved={(q) => {
            onChange(q);
            setEditing(false);
          }}
        />
      ) : (
        <>
          <p className="mb-3 text-[15px] font-medium leading-relaxed text-foreground">
            {question.question_text}
          </p>
          {question.options && (
            <div className="mb-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
              {question.options.map((o) => {
                const isCorrect = correct.includes(o.id);
                return (
                  <div
                    key={o.id}
                    className={`flex items-center gap-2.5 rounded-lg border px-3 py-2.5 ${
                      isCorrect
                        ? "border-emerald-500 bg-emerald-50 text-emerald-800"
                        : "border-input bg-card text-foreground/80"
                    }`}
                  >
                    <span
                      className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-xs font-semibold uppercase ${
                        isCorrect
                          ? "bg-emerald-600 text-white"
                          : "bg-muted text-muted-foreground"
                      }`}
                    >
                      {o.id}
                    </span>
                    <span className="flex-1">{o.text}</span>
                    {isCorrect && (
                      <CheckIcon className="h-4 w-4 shrink-0 text-emerald-600" />
                    )}
                  </div>
                );
              })}
            </div>
          )}
          <p className="font-medium text-emerald-700">
            Answer: {formatAnswer(question)}
          </p>
          {question.explanation && (
            <p className="mt-1 text-muted-foreground">Why: {question.explanation}</p>
          )}

          <div className="mt-3 flex flex-wrap gap-2">
            <Button
              size="sm"
              onClick={() => run("approve", () => approveQuestion(question.id))}
              disabled={!!busy}
            >
              Approve
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => run("reject", () => rejectQuestion(question.id))}
              disabled={!!busy}
            >
              Reject
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => setEditing(true)}
              disabled={!!busy}
            >
              Edit
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() =>
                run("regen", () => regenerateQuestion(question.id))
              }
              disabled={!!busy}
            >
              {busy === "regen" ? "Regenerating…" : "Regenerate"}
            </Button>
          </div>
        </>
      )}

      {error && <p className="mt-2 text-red-600">{error}</p>}
    </div>
  );
}

function EditForm({
  question,
  onCancel,
  onSaved,
}: {
  question: ReviewQuestion;
  onCancel: () => void;
  onSaved: (q: ReviewQuestion) => void;
}) {
  const answer = question.correct_answer as Record<string, unknown> | string | string[];
  const [text, setText] = useState(question.question_text);
  const [explanation, setExplanation] = useState(question.explanation ?? "");
  const [options, setOptions] = useState(question.options ?? []);
  const [single, setSingle] = useState(
    typeof answer === "string" ? answer : "",
  );
  const [multi, setMulti] = useState<string[]>(
    Array.isArray(answer) ? (answer as string[]) : [],
  );
  const [numValue, setNumValue] = useState(
    answer && typeof answer === "object" && "value" in answer
      ? String((answer as Record<string, unknown>).value)
      : "",
  );
  const [numTol, setNumTol] = useState(
    answer && typeof answer === "object" && "tolerance" in answer
      ? String((answer as Record<string, unknown>).tolerance)
      : "0",
  );
  const [fill, setFill] = useState(
    answer && typeof answer === "object" && "answers" in answer
      ? ((answer as Record<string, unknown>).answers as string[]).join(", ")
      : "",
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function setOptionText(id: string, t: string) {
    setOptions((prev) => prev.map((o) => (o.id === id ? { ...o, text: t } : o)));
  }

  async function save() {
    setError(null);
    setBusy(true);
    try {
      const patch: QuestionPatch = { question_text: text, explanation };
      if (question.type === "mcq_single") {
        patch.options = options;
        patch.correct_answer = single;
      } else if (question.type === "mcq_multi") {
        patch.options = options;
        patch.correct_answer = multi;
      } else if (question.type === "true_false") {
        patch.correct_answer = single;
      } else if (question.type === "numerical") {
        patch.correct_answer = {
          value: Number(numValue),
          tolerance: Number(numTol || 0),
        };
      } else if (question.type === "fill_blank") {
        patch.correct_answer = {
          answers: fill.split(",").map((s) => s.trim()).filter(Boolean),
        };
      }
      onSaved(await editQuestion(question.id, patch));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setBusy(false);
    }
  }

  const isChoice = CHOICE_TYPES.includes(question.type);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col gap-1">
        <Label>Question text</Label>
        <textarea
          className="min-h-16 rounded-md border p-2 text-sm"
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
      </div>

      {isChoice &&
        options.map((o) => (
          <div key={o.id} className="flex items-center gap-2">
            <input
              type={question.type === "mcq_multi" ? "checkbox" : "radio"}
              name={`correct-${question.id}`}
              checked={
                question.type === "mcq_multi"
                  ? multi.includes(o.id)
                  : single === o.id
              }
              onChange={() =>
                question.type === "mcq_multi"
                  ? setMulti((p) =>
                      p.includes(o.id)
                        ? p.filter((x) => x !== o.id)
                        : [...p, o.id],
                    )
                  : setSingle(o.id)
              }
            />
            <span className="font-mono text-xs">{o.id}</span>
            <Input
              value={o.text}
              onChange={(e) => setOptionText(o.id, e.target.value)}
            />
          </div>
        ))}

      {question.type === "numerical" && (
        <div className="flex gap-3">
          <div className="flex flex-col gap-1">
            <Label>Value</Label>
            <Input value={numValue} onChange={(e) => setNumValue(e.target.value)} />
          </div>
          <div className="flex flex-col gap-1">
            <Label>Tolerance (±)</Label>
            <Input value={numTol} onChange={(e) => setNumTol(e.target.value)} />
          </div>
        </div>
      )}

      {question.type === "fill_blank" && (
        <div className="flex flex-col gap-1">
          <Label>Accepted answers (comma-separated)</Label>
          <Input value={fill} onChange={(e) => setFill(e.target.value)} />
        </div>
      )}

      <div className="flex flex-col gap-1">
        <Label>Explanation</Label>
        <textarea
          className="min-h-12 rounded-md border p-2 text-sm"
          value={explanation}
          onChange={(e) => setExplanation(e.target.value)}
        />
      </div>

      {error && <p className="text-red-600">{error}</p>}

      <div className="flex gap-2">
        <Button size="sm" onClick={save} disabled={busy}>
          {busy ? "Saving…" : "Save"}
        </Button>
        <Button size="sm" variant="outline" onClick={onCancel} disabled={busy}>
          Cancel
        </Button>
      </div>
    </div>
  );
}
