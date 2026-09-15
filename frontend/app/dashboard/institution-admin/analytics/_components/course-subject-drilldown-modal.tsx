"use client";

import { useMemo, useState } from "react";

import { Dialog } from "@/components/ui/dialog";
import { ChevronDown, X } from "@/components/ui/icons";
import { AdminQuizSet, Course } from "@/lib/api";

function accuracyTone(value: number) {
  if (value >= 70) return "text-emerald-700";
  if (value >= 40) return "text-amber-700";
  return "text-rose-700";
}

export function CourseSubjectDrilldownModal({
  course,
  quizzes,
  onClose,
  onSelectQuiz,
}: {
  course: Course;
  quizzes: AdminQuizSet[];
  onClose: () => void;
  onSelectQuiz: (quiz: AdminQuizSet) => void;
}) {
  const [subjectId, setSubjectId] = useState<string | null>(null);

  const subjects = useMemo(() => {
    const values = new Map(course.subjects.map((subject) => [subject.id, subject.name]));
    for (const quiz of quizzes) {
      if (quiz.subject_id && !values.has(quiz.subject_id)) {
        values.set(quiz.subject_id, quiz.subject || "Unnamed subject");
      }
    }
    return Array.from(values, ([id, name]) => ({ id, name })).sort((a, b) =>
      a.name.localeCompare(b.name),
    );
  }, [course.subjects, quizzes]);

  const selectedSubject = subjects.find((subject) => subject.id === subjectId);
  const subjectQuizzes = useMemo(
    () =>
      quizzes
        .filter((quiz) => quiz.subject_id === subjectId)
        .sort(
          (a, b) =>
            b.attempts_count - a.attempts_count ||
            a.avg_accuracy - b.avg_accuracy,
        ),
    [quizzes, subjectId],
  );

  return (
    <Dialog
      onClose={onClose}
      ariaLabelledBy="course-subject-drilldown-title"
      overlayClassName="fixed inset-0 z-40 flex items-center justify-center bg-black/55 p-4"
      contentClassName="animate-rise flex max-h-[86vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-border bg-card shadow-2xl"
    >
        <div className="flex items-start justify-between gap-4 border-b p-5">
          <div className="min-w-0">
            {selectedSubject ? (
              <button
                type="button"
                onClick={() => setSubjectId(null)}
                className="mb-2 inline-flex items-center gap-1 text-xs font-semibold text-primary hover:underline"
              >
                <ChevronDown size={14} className="rotate-90" /> Back to {course.name} subjects
              </button>
            ) : (
              <p className="text-xs font-semibold uppercase tracking-widest text-primary">Course</p>
            )}
            <h2 id="course-subject-drilldown-title" className="truncate text-lg font-bold text-foreground">
              {selectedSubject ? selectedSubject.name : course.name}
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">
              {selectedSubject
                ? "Select a quiz to inspect its performance."
                : "Select a subject to see its quizzes and performance."}
            </p>
          </div>
          <button
            type="button"
            aria-label="Close course drill-down"
            onClick={onClose}
            className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-muted-foreground hover:bg-accent hover:text-foreground"
          >
            <X size={18} />
          </button>
        </div>

        <div className="overflow-y-auto p-5">
          {!selectedSubject ? (
            subjects.length === 0 ? (
              <div className="rounded-xl border border-dashed p-8 text-center text-sm text-muted-foreground">
                This course does not have any subjects yet.
              </div>
            ) : (
              <div className="grid gap-3 sm:grid-cols-2">
                {subjects.map((subject) => {
                  const rows = quizzes.filter((quiz) => quiz.subject_id === subject.id);
                  const attempts = rows.reduce((total, quiz) => total + quiz.attempts_count, 0);
                  const pending = rows.reduce(
                    (total, quiz) =>
                      total + quiz.review_status.pending + quiz.review_status.needs_edit,
                    0,
                  );
                  return (
                    <button
                      key={subject.id}
                      type="button"
                      onClick={() => setSubjectId(subject.id)}
                      className="rounded-xl border p-4 text-left transition hover:border-primary/35 hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
                    >
                      <span className="flex items-start justify-between gap-3">
                        <span className="min-w-0">
                          <span className="block truncate font-semibold text-foreground">{subject.name}</span>
                          <span className="mt-1 block text-xs text-muted-foreground">
                            {rows.length} quiz{rows.length === 1 ? "" : "zes"} · {attempts} attempt{attempts === 1 ? "" : "s"}
                          </span>
                        </span>
                        <span className="shrink-0 font-semibold text-primary">View →</span>
                      </span>
                      <span className="mt-3 flex items-center justify-between border-t pt-3 text-xs">
                        <span className="text-muted-foreground">
                          {rows.filter((quiz) => quiz.status === "published").length} published
                        </span>
                        <span className={pending ? "font-semibold text-amber-700" : "text-muted-foreground"}>
                          {pending ? `${pending} awaiting review` : "Review clear"}
                        </span>
                      </span>
                    </button>
                  );
                })}
              </div>
            )
          ) : subjectQuizzes.length === 0 ? (
            <div className="rounded-xl border border-dashed p-8 text-center text-sm text-muted-foreground">
              No quizzes have been created for this subject yet.
            </div>
          ) : (
            <div className="flex flex-col gap-2">
              {subjectQuizzes.map((quiz) => (
                <button
                  key={quiz.id}
                  type="button"
                  onClick={() => onSelectQuiz(quiz)}
                  className="grid gap-3 rounded-xl border p-4 text-left transition hover:border-primary/35 hover:bg-accent sm:grid-cols-[minmax(0,1fr)_90px_90px_100px] sm:items-center"
                >
                  <span className="min-w-0">
                    <span className="block truncate font-semibold text-foreground">{quiz.title}</span>
                    <span className="block truncate text-xs capitalize text-muted-foreground">{quiz.status}</span>
                  </span>
                  <span className="text-sm text-muted-foreground sm:text-right">{quiz.attempts_count} attempts</span>
                  <span className={`text-sm font-semibold sm:text-right ${quiz.attempts_count ? accuracyTone(quiz.avg_accuracy) : "text-muted-foreground"}`}>
                    {quiz.attempts_count ? `${quiz.avg_accuracy}%` : "—"}
                  </span>
                  <span className="text-xs font-semibold text-primary sm:text-right">View quiz →</span>
                </button>
              ))}
            </div>
          )}
        </div>
    </Dialog>
  );
}
