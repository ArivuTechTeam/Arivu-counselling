"use client";

import { variantLabel } from "@/lib/format";
import type { QuizSetDetail } from "@/lib/api";

type ReviewVariant = QuizSetDetail["variants"][number];

const STATUS_TONE: Record<string, string> = {
  approved:
    "border-emerald-200 bg-emerald-50 text-emerald-700 hover:border-emerald-400 hover:bg-emerald-100",
  rejected:
    "border-rose-200 bg-rose-50 text-rose-700 hover:border-rose-400 hover:bg-rose-100",
  needs_edit:
    "border-amber-200 bg-amber-50 text-amber-800 hover:border-amber-400 hover:bg-amber-100",
  pending_review:
    "border-transparent bg-muted text-muted-foreground hover:border-input hover:bg-accent",
};

const STATUS_DOT: Record<string, string> = {
  approved: "bg-emerald-500",
  rejected: "bg-rose-500",
  needs_edit: "bg-amber-400",
  pending_review: "bg-slate-300",
};

function Legend({ className, label }: { className: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
      <span className={`h-2 w-2 rounded-full ${className}`} aria-hidden="true" />
      {label}
    </span>
  );
}

export function QuestionReviewNavigator({
  variants,
  questionNumbers,
  totalQuestions,
  activeQuestionId,
  onNavigate,
}: {
  variants: ReviewVariant[];
  questionNumbers: Record<string, number>;
  totalQuestions: number;
  activeQuestionId: string | null;
  onNavigate: (questionId: string) => void;
}) {
  const visibleTotal = variants.reduce(
    (count, variant) => count + variant.questions.length,
    0,
  );
  const activePosition = activeQuestionId
    ? questionNumbers[activeQuestionId]
    : undefined;

  return (
    <aside className="w-full">
      <div className="overflow-hidden rounded-2xl border border-primary/10 bg-card shadow-sm">
        <div className="flex items-center justify-between gap-3 px-3.5 py-3">
          <div>
            <p className="text-sm font-semibold tracking-tight text-foreground">
              Question map
            </p>
            <p className="mt-0.5 text-[10px] text-muted-foreground">
              {visibleTotal === totalQuestions
                ? "Select a question to review"
                : `${visibleTotal} of ${totalQuestions} shown`}
            </p>
          </div>
          {activePosition && (
            <span className="shrink-0 rounded-full border border-primary/15 bg-primary/10 px-2.5 py-1 text-[11px] font-semibold tabular-nums text-primary">
              {activePosition} / {totalQuestions}
            </span>
          )}
        </div>

        <div className="max-h-[calc(100vh-21rem)] space-y-3 overflow-y-auto border-t px-3.5 py-3">
          {variants.map((variant) => (
            <div key={variant.id}>
              {variants.length > 1 && (
                <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                  {variantLabel(variant.variant_type)}
                </p>
              )}
              <div className="grid grid-cols-5 gap-1.5 sm:grid-cols-10 lg:grid-cols-5">
                {variant.questions.map((question) => {
                  const questionNumber = questionNumbers[question.id];
                  const active = question.id === activeQuestionId;
                  const tone =
                    STATUS_TONE[question.review_status] ??
                    STATUS_TONE.pending_review;
                  const dot =
                    STATUS_DOT[question.review_status] ??
                    STATUS_DOT.pending_review;
                  return (
                    <button
                      key={question.id}
                      type="button"
                      onClick={() => onNavigate(question.id)}
                      aria-label={`Go to question ${questionNumber}, ${question.review_status.replaceAll("_", " ")}`}
                      aria-current={active ? "step" : undefined}
                      title={`Question ${questionNumber} · ${question.review_status.replaceAll("_", " ")}`}
                      className={`relative flex aspect-square w-full max-w-9 min-w-0 items-center justify-center justify-self-center rounded-[10px] border text-xs font-semibold tabular-nums transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 ${
                        active
                          ? "border-primary bg-primary text-primary-foreground shadow-sm"
                          : tone
                      }`}
                    >
                      {questionNumber}
                      <span
                        className={`absolute bottom-1 right-1 h-1.5 w-1.5 rounded-full ring-1 ${
                          active ? "ring-primary" : "ring-white"
                        } ${dot}`}
                        aria-hidden="true"
                      />
                    </button>
                  );
                })}
              </div>
            </div>
          ))}
        </div>

        <div className="grid grid-cols-2 gap-x-2 gap-y-1.5 border-t bg-muted/25 px-3.5 py-2.5 text-[10px] text-muted-foreground">
          <Legend className="bg-emerald-500" label="Approved" />
          <Legend className="bg-muted" label="Pending" />
          <Legend className="bg-rose-500" label="Rejected" />
          <Legend className="bg-amber-400" label="Needs edit" />
        </div>
      </div>
    </aside>
  );
}
