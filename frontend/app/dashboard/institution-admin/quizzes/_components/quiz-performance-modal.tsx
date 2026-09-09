"use client";

import { useEffect, useState } from "react";

import { ErrorCard } from "@/components/ui/error-card";
import { X } from "@/components/ui/icons";
import { SkeletonList } from "@/components/ui/skeleton";
import {
  AdminQuizSet,
  AdminQuizSetDetail,
  getAdminQuizSetDetail,
} from "@/lib/api";

function label(value: string) {
  return value.replaceAll("_", " ").replace(/\b\w/g, (character) => character.toUpperCase());
}

function accuracyTone(value: number) {
  if (value >= 70) return "text-emerald-700";
  if (value >= 40) return "text-amber-700";
  return "text-rose-700";
}

export function QuizPerformanceModal({
  quiz,
  onClose,
}: {
  quiz: AdminQuizSet;
  onClose: () => void;
}) {
  const [detail, setDetail] = useState<AdminQuizSetDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  function load() {
    setError(null);
    setDetail(null);
    getAdminQuizSetDetail(quiz.id).then(setDetail).catch((reason) => setError(reason.message));
  }

  useEffect(load, [quiz.id]);
  useEffect(() => {
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/55 p-4"
      onMouseDown={(event) => event.target === event.currentTarget && onClose()}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="quiz-performance-title"
        className="animate-rise flex max-h-[90vh] w-full max-w-4xl flex-col overflow-hidden rounded-2xl border border-border bg-card shadow-2xl"
      >
        <div className="flex items-start justify-between gap-4 border-b p-5 sm:p-6">
          <div className="min-w-0">
            <p className="text-xs font-semibold uppercase tracking-widest text-primary">Quiz performance</p>
            <h2 id="quiz-performance-title" className="mt-1 truncate text-xl font-bold text-foreground">{quiz.title}</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              {[quiz.course, quiz.subject, quiz.teacher].filter(Boolean).join(" · ") || "Institution quiz"}
            </p>
          </div>
          <button type="button" aria-label="Close quiz details" onClick={onClose} className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-muted-foreground hover:bg-accent hover:text-foreground"><X size={19} /></button>
        </div>

        <div className="overflow-y-auto p-5 sm:p-6">
          {error ? (
            <ErrorCard message={error} onRetry={load} />
          ) : detail === null ? (
            <SkeletonList rows={5} />
          ) : (
            <div className="flex flex-col gap-6">
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                {[
                  ["Attempts", detail.quiz.attempts_count],
                  ["Average accuracy", detail.quiz.attempts_count ? `${detail.quiz.avg_accuracy}%` : "—"],
                  ["Questions", detail.quiz.questions],
                  ["Pending review", detail.quiz.review_status.pending + detail.quiz.review_status.needs_edit],
                ].map(([name, value]) => (
                  <div key={name} className="rounded-xl border bg-secondary/25 p-4">
                    <div className="text-xl font-bold text-foreground">{value}</div>
                    <div className="mt-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{name}</div>
                  </div>
                ))}
              </div>

              <div className="grid gap-5 lg:grid-cols-2">
                <section className="rounded-xl border p-4">
                  <h3 className="font-bold text-foreground">Question breakdown</h3>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {Object.entries(detail.question_breakdown.by_type).map(([name, count]) => (
                      <span key={name} className="rounded-full bg-primary/10 px-3 py-1 text-xs font-semibold text-primary">{label(name)} · {count}</span>
                    ))}
                    {Object.entries(detail.question_breakdown.by_difficulty).map(([name, count]) => (
                      <span key={name} className="rounded-full bg-secondary px-3 py-1 text-xs font-semibold text-muted-foreground">{label(name)} · {count}</span>
                    ))}
                    {detail.quiz.questions === 0 && <p className="text-sm text-muted-foreground">No questions in this quiz.</p>}
                  </div>
                </section>

                <section className="rounded-xl border p-4">
                  <h3 className="font-bold text-foreground">Questions students are struggling with</h3>
                  {detail.weak_questions.length === 0 ? (
                    <p className="mt-3 text-sm text-muted-foreground">No answered questions to compare yet.</p>
                  ) : (
                    <div className="mt-3 flex flex-col gap-2">
                      {detail.weak_questions.map((question) => (
                        <div key={question.question_id} className="rounded-lg bg-secondary/35 p-3">
                          <p className="line-clamp-2 text-sm text-foreground">{question.question_text}</p>
                          <p className={`mt-1 text-xs font-semibold ${accuracyTone(question.accuracy)}`}>{question.accuracy}% correct · {question.answered} answer{question.answered === 1 ? "" : "s"}</p>
                        </div>
                      ))}
                    </div>
                  )}
                </section>
              </div>

              <section>
                <div className="flex items-end justify-between gap-3">
                  <div>
                    <h3 className="font-bold text-foreground">Student performance</h3>
                    <p className="text-sm text-muted-foreground">Graded submissions, newest first.</p>
                  </div>
                  <span className="text-xs text-muted-foreground">{detail.student_performance.length} submission{detail.student_performance.length === 1 ? "" : "s"}</span>
                </div>
                {detail.student_performance.length === 0 ? (
                  <div className="mt-3 rounded-xl border border-dashed p-6 text-center text-sm text-muted-foreground">No graded attempts yet.</div>
                ) : (
                  <div className="mt-3 max-h-72 overflow-auto rounded-xl border">
                    <table className="w-full text-sm">
                      <thead className="sticky top-0 bg-card text-left text-xs uppercase tracking-wide text-muted-foreground">
                        <tr><th className="px-3 py-2 font-medium">Student</th><th className="px-3 py-2 text-right font-medium">Score</th><th className="px-3 py-2 text-right font-medium">Accuracy</th><th className="px-3 py-2 text-right font-medium">Submitted</th></tr>
                      </thead>
                      <tbody>
                        {detail.student_performance.map((attempt) => (
                          <tr key={attempt.attempt_id} className="border-t">
                            <td className="px-3 py-2.5 font-medium text-foreground">{attempt.student_name}</td>
                            <td className="px-3 py-2.5 text-right text-muted-foreground">{attempt.score}/{attempt.max_score || "—"}</td>
                            <td className={`px-3 py-2.5 text-right font-semibold ${accuracyTone(attempt.accuracy)}`}>{attempt.max_score ? `${attempt.accuracy}%` : "—"}</td>
                            <td className="whitespace-nowrap px-3 py-2.5 text-right text-muted-foreground">{attempt.submitted_at ? new Date(attempt.submitted_at).toLocaleDateString() : "—"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
