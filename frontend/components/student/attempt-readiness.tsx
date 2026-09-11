"use client";

import { useEffect } from "react";

import { Button } from "@/components/ui/button";

type AttemptReadinessProps = {
  open: boolean;
  title: string;
  questionCount: number;
  requestedQuestionCount?: number;
  timeLimitMinutes?: number | null;
  timeDisplay?: string;
  attemptNumber?: number;
  maxAttempts?: number;
  warningText?: string;
  busy?: boolean;
  onCancel: () => void;
  onConfirm: () => void;
};

export function AttemptReadiness({
  open,
  title,
  questionCount,
  requestedQuestionCount,
  timeLimitMinutes,
  timeDisplay,
  attemptNumber,
  maxAttempts,
  warningText,
  busy = false,
  onCancel,
  onConfirm,
}: AttemptReadinessProps) {
  useEffect(() => {
    if (!open) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) onCancel();
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [busy, onCancel, open]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/45 p-4 backdrop-blur-[2px]"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !busy) onCancel();
      }}
    >
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby="attempt-readiness-title"
        className="w-full max-w-lg rounded-2xl border bg-card p-5 shadow-2xl sm:p-6"
      >
        <p className="text-xs font-semibold uppercase tracking-[0.18em] text-primary">
          Ready when you are
        </p>
        <h2 id="attempt-readiness-title" className="mt-2 text-xl font-bold">
          {title}
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Take a moment to settle in. Your attempt starts only after you confirm.
        </p>

        <div className="mt-5 grid grid-cols-2 gap-3">
          <ReadinessStat value={String(questionCount)} label="Questions" />
          <ReadinessStat
            value={
              timeDisplay ??
              (timeLimitMinutes ? `${timeLimitMinutes} min` : "Untimed")
            }
            label="Overall limit"
          />
        </div>

        <div className="mt-4 space-y-2 text-sm">
          {warningText ? (
            <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-amber-950">
              <p className="font-semibold">Please read before continuing</p>
              <p className="mt-1 text-xs leading-relaxed">{warningText}</p>
            </div>
          ) : null}
          {requestedQuestionCount && questionCount < requestedQuestionCount ? (
            <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-amber-950">
              <p className="font-semibold">
                {questionCount} matching questions are currently available.
              </p>
              <p className="mt-1 text-xs leading-relaxed">
                You requested {requestedQuestionCount}; this quiz will use every
                approved question matching your selection.
              </p>
            </div>
          ) : null}
          {attemptNumber && maxAttempts ? (
            <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-amber-950">
              <p className="font-semibold">
                This will use attempt {attemptNumber} of {maxAttempts}.
              </p>
              <p className="mt-1 text-xs leading-relaxed">
                If you navigate to another page after starting, this attempt ends
                immediately. Only answered work receives marks; unanswered
                questions score zero. Refreshing restores the same active attempt.
              </p>
            </div>
          ) : null}
          <Instruction>
            Answer every question before submitting early. If a timed attempt
            expires, your saved work submits automatically.
          </Instruction>
          <Instruction>
            Use the suggested pace on each question as a guide: choice questions
            are quicker, while numerical questions receive more time.
          </Instruction>
          <p className="px-1 text-xs leading-relaxed text-muted-foreground">
            Base guide: True/False 45 sec · Single choice 60 sec · Fill blank
            75 sec · Multiple choice 90 sec · Numerical 120 sec. Timed
            attempts scale these guides to fit the overall limit.
          </p>
          <Instruction>
            Your answers are saved as you work, so a refresh can restore your
            progress.
          </Instruction>
        </div>

        <div className="mt-6 flex justify-end gap-2 border-t pt-4">
          <Button variant="outline" onClick={onCancel} disabled={busy}>
            Not yet
          </Button>
          <Button onClick={onConfirm} disabled={busy} autoFocus>
            {busy
              ? "Starting…"
              : attemptNumber && maxAttempts
                ? `Use attempt ${attemptNumber} of ${maxAttempts} →`
                : "Start now →"}
          </Button>
        </div>
      </section>
    </div>
  );
}

function ReadinessStat({ value, label }: { value: string; label: string }) {
  return (
    <div className="rounded-xl border border-primary/15 bg-primary/[0.04] p-3 text-center">
      <p className="text-lg font-bold text-foreground">{value}</p>
      <p className="mt-0.5 text-xs text-muted-foreground">{label}</p>
    </div>
  );
}

function Instruction({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex gap-3 rounded-lg border p-3">
      <span className="mt-1 h-2 w-2 shrink-0 rounded-full bg-primary" />
      <p className="text-muted-foreground">{children}</p>
    </div>
  );
}
