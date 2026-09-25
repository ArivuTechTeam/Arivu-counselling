"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { SparkBurst } from "@/components/ui/spark-burst";
import { formatAnswerValue, statusLabel, typeLabel } from "@/lib/format";
import {
  DocumentFigure,
  QuestionPatch,
  ReviewQuestion,
  approveQuestion,
  editQuestion,
  regenerateQuestion,
  rejectQuestion,
  setQuestionFigure,
} from "@/lib/api";

const CHOICE_TYPES = ["mcq_single", "mcq_multi", "true_false", "assertion_reason", "mrm"];
const MULTI_SELECT_TYPES = ["mcq_multi", "mrm"];
const editDraftKey = (questionId: string) => `teacher-question-edit:${questionId}`;

// Shared textarea styling so edit fields match the read-view inputs, with a
// proper brand focus ring.
const TEXTAREA_CLASS =
  "w-full rounded-md border border-input bg-background p-2.5 text-sm shadow-sm transition-colors focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20";

function correctIds(q: ReviewQuestion): string[] {
  const a = q.correct_answer;
  if (Array.isArray(a)) return a.map(String);
  if (typeof a === "string") return [a];
  return [];
}

// Status tones from the design system: emerald = approved, rose = rejected,
// amber = needs_edit, warm-neutral = pending. The tone is keyed off the raw
// token; the label users see goes through statusLabel().
const STATUS_TONE: Record<string, string> = {
  approved: "bg-emerald-100 text-emerald-700",
  rejected: "bg-rose-100 text-rose-700",
  needs_edit: "bg-amber-100 text-amber-700",
  pending_review: "bg-muted text-muted-foreground",
};

function StatusBadge({ status, pop }: { status: string; pop?: boolean }) {
  const tone = STATUS_TONE[status] ?? "bg-muted text-muted-foreground";
  return (
    <span
      className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium transition-colors duration-300 ${tone} ${
        pop ? "animate-badge-pop" : ""
      }`}
    >
      {statusLabel(status)}
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

const VERIFICATION_TONE: Record<string, string> = {
  verified: "border-emerald-200 bg-emerald-50 text-emerald-700",
  needs_teacher_review: "border-amber-200 bg-amber-50 text-amber-800",
  unsupported: "border-rose-200 bg-rose-50 text-rose-700",
  ambiguous: "border-orange-200 bg-orange-50 text-orange-800",
};

const VERIFICATION_LABEL: Record<string, string> = {
  verified: "Evidence verified",
  needs_teacher_review: "Check evidence",
  unsupported: "AI review flag",
  ambiguous: "Ambiguous",
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

// Figure attach/confirm/swap/remove (Phase 2). The teacher review queue is the
// correctness gate: the AI best-effort links a source-document figure, and the
// teacher confirms it (by leaving it and approving), swaps it, or removes it.
function FigureControls({
  question,
  documentFigures,
  onChange,
}: {
  question: ReviewQuestion;
  documentFigures: DocumentFigure[];
  onChange: (q: ReviewQuestion) => void;
}) {
  const [picking, setPicking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const current = question.figure ?? null;
  // Nothing to show when the source document has no figures and none is attached.
  if (!current && documentFigures.length === 0) return null;

  async function apply(figureId: string | null) {
    setError(null);
    setBusy(true);
    try {
      onChange(await setQuestionFigure(question.id, figureId));
      setPicking(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not update the figure.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mb-3 rounded-lg border border-input bg-muted/20 p-3">
      {current ? (
        <div className="flex flex-col gap-2 sm:flex-row sm:items-start">
          {current.url && (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={current.url}
              alt={current.label ?? "Attached figure"}
              className="h-28 w-auto shrink-0 rounded-md border bg-white object-contain"
            />
          )}
          <div className="min-w-0 flex-1">
            <p className="text-xs font-semibold text-foreground">
              {current.label ?? "Figure"}
              {current.page != null && (
                <span className="ml-1 font-normal text-muted-foreground">
                  (source page {current.page})
                </span>
              )}
            </p>
            {current.caption && (
              <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">
                {current.caption}
              </p>
            )}
            <div className="mt-2 flex flex-wrap gap-2">
              <Button
                size="sm"
                variant="outline"
                onClick={() => setPicking((p) => !p)}
                disabled={busy || documentFigures.length === 0}
              >
                {picking ? "Close" : "Change figure"}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => apply(null)}
                disabled={busy}
              >
                {busy ? "Removing…" : "Remove"}
              </Button>
            </div>
          </div>
        </div>
      ) : (
        <div className="flex items-center justify-between gap-2">
          <p className="text-xs text-muted-foreground">
            This question may need a figure from the source document.
          </p>
          <Button
            size="sm"
            variant="outline"
            onClick={() => setPicking((p) => !p)}
            disabled={busy}
          >
            {picking ? "Close" : "Add figure"}
          </Button>
        </div>
      )}

      {picking && (
        <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3">
          {documentFigures.map((figure) => {
            const selected = figure.id === question.figure_id;
            return (
              <button
                key={figure.id}
                type="button"
                onClick={() => apply(figure.id)}
                disabled={busy}
                className={`flex flex-col items-center gap-1 rounded-md border p-1.5 text-left transition-colors hover:border-primary ${
                  selected ? "border-primary ring-2 ring-primary/20" : "border-input"
                }`}
                title={figure.caption ?? figure.label ?? undefined}
              >
                {figure.url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={figure.url}
                    alt={figure.label ?? "Figure"}
                    className="h-20 w-full rounded bg-white object-contain"
                  />
                ) : (
                  <span className="flex h-20 w-full items-center justify-center rounded bg-muted text-[10px] text-muted-foreground">
                    No preview
                  </span>
                )}
                <span className="w-full truncate text-[11px] font-medium text-foreground">
                  {figure.label ?? "Figure"}
                  {figure.page != null ? ` · p${figure.page}` : ""}
                </span>
              </button>
            );
          })}
        </div>
      )}

      {error && <p className="mt-2 text-xs text-destructive">{error}</p>}
    </div>
  );
}

export function QuestionReviewCard({
  index,
  question,
  onChange,
  documentFigures = [],
}: {
  index: number;
  question: ReviewQuestion;
  onChange: (q: ReviewQuestion) => void;
  documentFigures?: DocumentFigure[];
}) {
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Drives the one-shot in-card feedback: sparks on approve, a red shake on
  // reject. Cleared after the animation so a later action can replay it.
  const [celebrate, setCelebrate] = useState(false);
  const [flash, setFlash] = useState<null | "approve" | "reject">(null);

  useEffect(() => {
    try {
      window.sessionStorage.removeItem(editDraftKey(question.id));
    } catch {
      // Editing still works without refresh restoration.
    }
  }, [question.id]);

  function closeEditor() {
    try {
      window.sessionStorage.removeItem(editDraftKey(question.id));
    } catch {
      // Nothing else is required when storage is unavailable.
    }
    setEditing(false);
  }

  async function run(label: string, fn: () => Promise<ReviewQuestion>) {
    setError(null);
    setBusy(label);
    try {
      onChange(await fn());
      if (label === "approve") {
        setFlash("approve");
        setCelebrate(true);
        window.setTimeout(() => setCelebrate(false), 800);
        window.setTimeout(() => setFlash(null), 1000);
      } else if (label === "reject") {
        setFlash("reject");
        window.setTimeout(() => setFlash(null), 900);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Action failed");
    } finally {
      setBusy(null);
    }
  }

  const correct = correctIds(question);

  const accent = ACCENT[question.review_status] ?? "#cbd5e1";
  const isApproved = question.review_status === "approved";
  const isRejected = question.review_status === "rejected";
  const flashClass =
    flash === "approve"
      ? "animate-approve"
      : flash === "reject"
        ? "animate-reject"
        : "";

  return (
    <div
      className={`relative overflow-hidden rounded-xl border bg-card pl-5 pr-4 py-4 text-sm shadow-sm transition-shadow hover:shadow-md ${flashClass}`}
    >
      {/* status accent strip */}
      <span
        className="absolute inset-y-0 left-0 w-1.5 transition-colors duration-500"
        style={{ backgroundColor: accent }}
        aria-hidden="true"
      />

      {celebrate && <SparkBurst />}

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <span className="flex h-7 w-7 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary">
          {index + 1}
        </span>
        <span className="rounded-full border border-border bg-muted px-2.5 py-0.5 text-xs font-medium text-muted-foreground">
          {typeLabel(question.type)}
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
        {question.paper_type && (
          <span className="rounded-full border border-amber-300 bg-amber-50 px-2.5 py-0.5 text-xs font-semibold uppercase text-amber-700">
            {question.paper_type}
            {question.paper_year ? ` · ${question.paper_year}` : ""}
            {question.paper_exam ? ` · ${question.paper_exam}` : ""}
          </span>
        )}
        <span className="ml-auto">
          <StatusBadge status={question.review_status} pop={flash !== null} />
        </span>
      </div>

      {editing && !question.release_locked ? (
        <EditForm
          question={question}
          onCancel={closeEditor}
          onSaved={(q) => {
            onChange(q);
            closeEditor();
          }}
        />
      ) : (
        <>
          <p className="mb-3 text-[15px] font-medium leading-relaxed text-foreground">
            {question.question_text}
          </p>
          {question.type === "descriptive" && question.model_answer && (
            <div className="mb-3 rounded-lg border border-input bg-muted/30 p-3 text-sm">
              <p className="mb-1 text-xs font-semibold uppercase text-muted-foreground">Model answer</p>
              <p className="whitespace-pre-wrap text-foreground/90">{question.model_answer}</p>
            </div>
          )}
          <fieldset disabled={question.release_locked}><FigureControls
            question={question}
            documentFigures={documentFigures}
            onChange={onChange}
          /></fieldset>
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
                      {question.type === "true_false"
                        ? o.id === "true"
                          ? "✓"
                          : "×"
                        : o.id}
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
            Answer: {formatAnswerValue(question.correct_answer)}
          </p>
          {question.explanation && (
            <p className="mt-1 text-muted-foreground">Why: {question.explanation}</p>
          )}

          {(question.source_excerpt || question.verification_status) && (
            <details className="mt-3 rounded-lg border border-input bg-muted/25 p-3">
              <summary className="cursor-pointer text-xs text-muted-foreground">Source and AI checks (optional)</summary>
              <div className="flex flex-wrap items-center gap-2">
                <p className="text-xs font-semibold text-foreground">Source evidence</p>
                {question.verification_status && (
                  <span
                    className={`rounded-full border px-2 py-0.5 text-[11px] font-medium ${
                      VERIFICATION_TONE[question.verification_status] ??
                      "border-input bg-muted text-muted-foreground"
                    }`}
                  >
                    {VERIFICATION_LABEL[question.verification_status] ??
                      question.verification_status.replaceAll("_", " ")}
                  </span>
                )}
                {question.source_page_start != null && (
                  <span className="text-[11px] text-muted-foreground">
                    Page {question.source_page_start}
                    {question.source_page_end != null &&
                    question.source_page_end !== question.source_page_start
                      ? `–${question.source_page_end}`
                      : ""}
                  </span>
                )}
                {question.grounding_confidence != null && (
                  <span className="text-[11px] text-muted-foreground">
                    {Math.round(question.grounding_confidence * 100)}% grounding
                  </span>
                )}
              </div>
              {question.source_excerpt && (
                <blockquote className="mt-2 border-l-2 border-primary/30 pl-3 text-xs leading-relaxed text-muted-foreground">
                  “{question.source_excerpt}”
                </blockquote>
              )}
              {!!question.verification_warnings?.length && (
                <ul className="mt-2 space-y-1 text-xs text-amber-800">
                  {question.verification_warnings.map((warning, warningIndex) => (
                    <li key={`${warning}-${warningIndex}`}>• {warning}</li>
                  ))}
                </ul>
              )}
            </details>
          )}

          {question.release_locked && <p className="mt-3 text-sm text-muted-foreground">Released question. Duplicate this quiz to make changes.</p>}
          <fieldset disabled={question.release_locked} className="mt-3 flex flex-wrap gap-2">
            <Button
              size="sm"
              onClick={() => run("approve", () => approveQuestion(question.id))}
              disabled={!!busy || isApproved}
              className={
                isApproved
                  ? "bg-emerald-600 text-white hover:bg-emerald-600 disabled:opacity-100"
                  : ""
              }
            >
              {isApproved ? (
                <span className="flex items-center gap-1.5">
                  <CheckIcon className="h-3.5 w-3.5" /> Approved
                </span>
              ) : busy === "approve" ? (
                "Approving…"
              ) : (
                "Approve"
              )}
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => run("reject", () => rejectQuestion(question.id))}
              disabled={!!busy || isRejected}
              className={
                isRejected
                  ? "border-rose-300 bg-rose-50 text-rose-700 hover:bg-rose-50 disabled:opacity-100"
                  : ""
              }
            >
              {isRejected ? "Rejected" : busy === "reject" ? "Rejecting…" : "Reject"}
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
          </fieldset>
        </>
      )}

      {error && <p className="mt-2 text-destructive">{error}</p>}
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
      if (question.type === "mcq_single" || question.type === "assertion_reason") {
        patch.options = options;
        patch.correct_answer = single;
      } else if (question.type === "mcq_multi" || question.type === "mrm") {
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
      onSaved(await editQuestion(question.id, patch, question.content_version));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setBusy(false);
    }
  }

  const isChoice = CHOICE_TYPES.includes(question.type);
  const isMultiSelect = MULTI_SELECT_TYPES.includes(question.type);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col gap-1">
        <Label>Question text</Label>
        <textarea
          className={`min-h-16 ${TEXTAREA_CLASS}`}
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
      </div>

      {isChoice &&
        options.map((o) => (
          <div key={o.id} className="flex items-center gap-2">
            <input
              type={isMultiSelect ? "checkbox" : "radio"}
              name={`correct-${question.id}`}
              checked={
                isMultiSelect ? multi.includes(o.id) : single === o.id
              }
              onChange={() =>
                isMultiSelect
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
            <Label>Allowed margin of error (±)</Label>
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

      {question.type === "matching" && (
        <div className="flex flex-col gap-1">
          <Label>Correct matches</Label>
          <div className="rounded-md border border-input bg-muted/30 p-2.5 text-sm">
            {(() => {
              const opts = (question.options ?? []) as {
                id: string;
                text: string;
                side?: string;
              }[];
              const textById: Record<string, string> = Object.fromEntries(
                opts.map((o) => [o.id, o.text]),
              );
              const pairs =
                answer && typeof answer === "object" && "pairs" in answer
                  ? ((answer as { pairs?: Record<string, string> }).pairs ?? {})
                  : {};
              const entries = Object.entries(pairs);
              if (!entries.length)
                return <span className="text-muted-foreground">No pairs.</span>;
              return (
                <ul className="flex flex-col gap-1">
                  {entries.map(([l, r]) => (
                    <li key={l}>
                      {textById[l] ?? l} → {textById[r] ?? r}
                    </li>
                  ))}
                </ul>
              );
            })()}
            <p className="mt-2 text-xs text-muted-foreground">
              Edit the wording and explanation here; the matched pairs are set at
              generation. Use Reject &amp; regenerate to change the pairs.
            </p>
          </div>
        </div>
      )}

      <div className="flex flex-col gap-1">
        <Label>Explanation</Label>
        <textarea
          className={`min-h-12 ${TEXTAREA_CLASS}`}
          value={explanation}
          onChange={(e) => setExplanation(e.target.value)}
        />
      </div>

      {error && <p className="text-sm text-destructive">{error}</p>}

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
