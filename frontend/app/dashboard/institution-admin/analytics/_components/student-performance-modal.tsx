"use client";

import { useState } from "react";

import { Dialog } from "@/components/ui/dialog";
import { X } from "@/components/ui/icons";
import { InstitutionAnalytics } from "@/lib/api";

type Student = InstitutionAnalytics["at_risk_students"][number];

export function StudentPerformanceModal({
  students,
  initialStudent,
  onClose,
}: {
  students: Student[];
  initialStudent?: Student | null;
  onClose: () => void;
}) {
  const [selected, setSelected] = useState<Student | null>(initialStudent ?? null);

  return (
    <Dialog
      onClose={onClose}
      ariaLabelledBy="student-performance-title"
      contentClassName="flex max-h-[88vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border bg-card shadow-2xl"
    >
        <header className="flex items-start justify-between gap-4 border-b p-5">
          <div>
            <p className="text-xs font-semibold uppercase tracking-widest text-rose-600">Needs attention</p>
            <h2 id="student-performance-title" className="mt-1 text-xl font-bold">{selected ? selected.name : "At-risk students"}</h2>
            <p className="mt-1 text-sm text-muted-foreground">{selected ? "Quiz-by-quiz performance for this student." : "Students averaging below 40%, weakest first."}</p>
          </div>
          <button type="button" aria-label="Close student details" onClick={onClose} className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-muted-foreground hover:bg-accent"><X size={18} /></button>
        </header>
        <div className="overflow-y-auto p-5">
          {selected ? (
            <div>
              <button type="button" onClick={() => setSelected(null)} className="mb-4 text-sm font-semibold text-primary hover:underline">← All at-risk students</button>
              <div className="mb-5 grid grid-cols-2 gap-3">
                <div className="rounded-xl border bg-secondary/30 p-4"><strong className="text-2xl text-rose-600">{selected.accuracy}%</strong><p className="mt-1 text-xs uppercase tracking-wide text-muted-foreground">Average accuracy</p></div>
                <div className="rounded-xl border bg-secondary/30 p-4"><strong className="text-2xl">{selected.attempts}</strong><p className="mt-1 text-xs uppercase tracking-wide text-muted-foreground">Attempts</p></div>
              </div>
              <div className="overflow-hidden rounded-xl border">
                {selected.quizzes.map((quiz) => (
                  <div key={quiz.quiz_set_id} className="grid gap-2 border-b p-4 last:border-0 sm:grid-cols-[1fr_auto_auto] sm:items-center">
                    <div><p className="font-semibold">{quiz.title}</p><p className="text-xs text-muted-foreground">Last attempted {quiz.last_attempted_at ? new Date(quiz.last_attempted_at).toLocaleDateString() : "—"}</p></div>
                    <span className="text-sm text-muted-foreground">{quiz.attempts} attempt{quiz.attempts === 1 ? "" : "s"}</span>
                    <strong className={quiz.accuracy < 40 ? "text-rose-600" : quiz.accuracy < 70 ? "text-amber-600" : "text-emerald-600"}>{quiz.accuracy}%</strong>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div className="flex flex-col gap-2">
              {students.map((student) => (
                <button key={student.student_id} type="button" onClick={() => setSelected(student)} className="grid gap-2 rounded-xl border p-4 text-left transition hover:border-primary/35 hover:bg-accent sm:grid-cols-[1fr_auto_auto] sm:items-center">
                  <div><p className="font-semibold">{student.name}</p><p className="text-xs text-muted-foreground">Worst quiz: {student.worst_quiz?.title ?? "No quiz details"}</p></div>
                  <span className="text-sm text-muted-foreground">{student.attempts} attempted</span>
                  <strong className="text-rose-600">{student.accuracy}% →</strong>
                </button>
              ))}
            </div>
          )}
        </div>
    </Dialog>
  );
}
