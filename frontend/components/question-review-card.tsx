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

function StatusBadge({ status }: { status: string }) {
  const color =
    status === "approved"
      ? "bg-green-100 text-green-800"
      : status === "rejected"
        ? "bg-red-100 text-red-800"
        : status === "needs_edit"
          ? "bg-yellow-100 text-yellow-800"
          : "bg-gray-100 text-gray-700";
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${color}`}>
      {status}
    </span>
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

  return (
    <div className="rounded-md border p-4 text-sm">
      <div className="mb-2 flex items-center justify-between">
        <span className="font-medium">Q{index + 1}</span>
        <span className="flex items-center gap-2">
          <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs uppercase text-gray-700">
            {question.type}
          </span>
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
          <p className="mb-2">{question.question_text}</p>
          {question.options && (
            <ul className="mb-2 flex flex-col gap-1">
              {question.options.map((o) => (
                <li
                  key={o.id}
                  className={
                    correct.includes(o.id)
                      ? "text-green-700"
                      : "text-muted-foreground"
                  }
                >
                  <span className="font-mono">{o.id}.</span> {o.text}
                  {correct.includes(o.id) && " ✓"}
                </li>
              ))}
            </ul>
          )}
          <p className="text-green-700">Answer: {formatAnswer(question)}</p>
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
