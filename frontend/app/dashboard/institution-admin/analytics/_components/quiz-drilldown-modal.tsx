"use client";

import { useEffect } from "react";

import { X } from "@/components/ui/icons";
import { AdminQuizSet } from "@/lib/api";

function accuracyTone(value: number) {
  if (value >= 70) return "text-emerald-700";
  if (value >= 40) return "text-amber-700";
  return "text-rose-700";
}

export function QuizDrilldownModal({
  title,
  description,
  quizzes,
  onClose,
  onSelect,
}: {
  title: string;
  description: string;
  quizzes: AdminQuizSet[];
  onClose: () => void;
  onSelect: (quiz: AdminQuizSet) => void;
}) {
  useEffect(() => {
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/55 p-4" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <div role="dialog" aria-modal="true" aria-labelledby="analytics-drilldown-title" className="animate-rise flex max-h-[86vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-border bg-card shadow-2xl">
        <div className="flex items-start justify-between gap-4 border-b p-5">
          <div><h2 id="analytics-drilldown-title" className="text-lg font-bold text-foreground">{title}</h2><p className="mt-1 text-sm text-muted-foreground">{description}</p></div>
          <button type="button" aria-label="Close drill-down" onClick={onClose} className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-muted-foreground hover:bg-accent hover:text-foreground"><X size={18} /></button>
        </div>
        <div className="overflow-y-auto p-5">
          {quizzes.length === 0 ? (
            <div className="rounded-xl border border-dashed p-8 text-center text-sm text-muted-foreground">No quizzes match this selection.</div>
          ) : (
            <div className="flex flex-col gap-2">
              {quizzes.map((quiz) => (
                <button key={quiz.id} type="button" onClick={() => onSelect(quiz)} className="grid gap-3 rounded-xl border p-4 text-left transition hover:border-primary/35 hover:bg-accent sm:grid-cols-[minmax(0,1fr)_90px_90px_130px] sm:items-center">
                  <span className="min-w-0"><span className="block truncate font-semibold text-foreground">{quiz.title}</span><span className="block truncate text-xs text-muted-foreground">{[quiz.course, quiz.teacher, quiz.status].filter(Boolean).join(" · ")}</span></span>
                  <span className="text-sm text-muted-foreground sm:text-right">{quiz.attempts_count} attempts</span>
                  <span className={`text-sm font-semibold sm:text-right ${quiz.attempts_count ? accuracyTone(quiz.avg_accuracy) : "text-muted-foreground"}`}>{quiz.attempts_count ? `${quiz.avg_accuracy}%` : "—"}</span>
                  <span className="text-xs text-muted-foreground sm:text-right">Last attempt<br />{quiz.last_attempted_at ? new Date(quiz.last_attempted_at).toLocaleDateString() : "None"}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
