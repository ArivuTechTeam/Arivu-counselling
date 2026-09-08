"use client";

import { useEffect, useMemo, useState } from "react";

import { QuestionPaperButtons } from "@/components/shared/pdf-buttons";
import { ChevronDown, X } from "@/components/ui/icons";
import { AdminQuizSet, TeacherAnalytics, TeacherAnalyticsDetail } from "@/lib/api";

type FacultySort = "attempts_desc" | "accuracy_desc" | "quizzes_desc" | "newest";

function accuracyTone(value: number) {
  if (value >= 70) return "text-emerald-700";
  if (value >= 40) return "text-amber-700";
  return "text-rose-700";
}

function health(teacher: TeacherAnalyticsDetail) {
  if (!teacher.is_active) return { label: "Low activity", tone: "bg-rose-100 text-rose-700", dot: "bg-rose-500" };
  if (teacher.total_attempts < 5) return { label: "Building engagement", tone: "bg-amber-100 text-amber-800", dot: "bg-amber-400" };
  return { label: "Active", tone: "bg-emerald-100 text-emerald-700", dot: "bg-emerald-500" };
}

export function FacultyAnalysisModal({
  analytics,
  quizzes,
  onClose,
  onFilterTeacher,
  onOpenQuiz,
}: {
  analytics: TeacherAnalytics;
  quizzes: AdminQuizSet[];
  onClose: () => void;
  onFilterTeacher: (teacherId: string) => void;
  onOpenQuiz: (quiz: AdminQuizSet) => void;
}) {
  const [sort, setSort] = useState<FacultySort>("attempts_desc");
  const [selectedTeacher, setSelectedTeacher] = useState<TeacherAnalyticsDetail | null>(null);

  useEffect(() => {
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [onClose]);

  const sortedTeachers = useMemo(() => [...analytics.teachers].sort((a, b) => {
    if (sort === "accuracy_desc") return b.avg_accuracy - a.avg_accuracy;
    if (sort === "quizzes_desc") return b.quiz_sets_created - a.quiz_sets_created;
    if (sort === "newest") return new Date(b.last_quiz_created ?? 0).getTime() - new Date(a.last_quiz_created ?? 0).getTime();
    return b.total_attempts - a.total_attempts;
  }), [analytics.teachers, sort]);

  const teacherQuizzes = selectedTeacher
    ? quizzes.filter((quiz) => quiz.teacher_id === selectedTeacher.teacher_id)
    : [];

  function viewTeacher(teacher: TeacherAnalyticsDetail) {
    setSelectedTeacher(teacher);
    onFilterTeacher(teacher.teacher_id);
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/55 p-3 sm:p-5" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <div role="dialog" aria-modal="true" aria-labelledby="faculty-analysis-title" className="animate-rise flex max-h-[92vh] w-full max-w-6xl flex-col overflow-hidden rounded-2xl border border-border bg-card shadow-2xl">
        <div className="flex items-start justify-between gap-4 border-b p-5 sm:p-6">
          <div>
            <p className="text-xs font-semibold uppercase tracking-widest text-primary">Institution insights</p>
            <h2 id="faculty-analysis-title" className="mt-1 text-xl font-bold text-foreground">
              {selectedTeacher ? selectedTeacher.teacher_name : "Faculty analysis dashboard"}
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">
              {selectedTeacher ? "Their quiz activity and student performance." : "Teacher activity, publishing consistency, engagement, and accuracy."}
            </p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close faculty analysis" className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-muted-foreground hover:bg-accent hover:text-foreground"><X size={19} /></button>
        </div>

        <div className="overflow-y-auto p-4 sm:p-6">
          {selectedTeacher ? (
            <div className="flex flex-col gap-5">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <button type="button" onClick={() => setSelectedTeacher(null)} className="inline-flex items-center gap-2 text-sm font-semibold text-primary hover:underline"><ChevronDown size={16} className="rotate-90" /> Back to faculty</button>
                <span className="text-sm text-muted-foreground">The main quiz list is now filtered to this teacher.</span>
              </div>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
                {[
                  ["Quiz sets", selectedTeacher.quiz_sets_created],
                  ["Published", selectedTeacher.quiz_sets_published],
                  ["Attempts", selectedTeacher.total_attempts],
                  ["Accuracy", selectedTeacher.total_attempts ? `${selectedTeacher.avg_accuracy}%` : "—"],
                  ["Last created", selectedTeacher.last_quiz_created ? new Date(selectedTeacher.last_quiz_created).toLocaleDateString() : "Never"],
                ].map(([label, value]) => <div key={label} className="rounded-xl border bg-secondary/25 p-4"><div className="text-lg font-bold text-foreground">{value}</div><div className="mt-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">{label}</div></div>)}
              </div>
              {teacherQuizzes.length === 0 ? (
                <div className="rounded-xl border border-dashed p-8 text-center text-sm text-muted-foreground">This teacher has not created a quiz yet.</div>
              ) : (
                <div className="overflow-x-auto rounded-xl border">
                  <table className="w-full min-w-[780px] text-sm">
                    <thead className="bg-secondary/40 text-left text-xs uppercase tracking-wide text-muted-foreground"><tr><th className="px-4 py-3 font-medium">Quiz</th><th className="px-3 py-3 text-right font-medium">Attempts</th><th className="px-3 py-3 text-right font-medium">Accuracy</th><th className="px-3 py-3 text-right font-medium">Questions</th><th className="px-3 py-3 font-medium">Created</th><th className="px-4 py-3 text-right font-medium">Actions</th></tr></thead>
                    <tbody>{teacherQuizzes.map((quiz) => <tr key={quiz.id} className="border-t"><td className="px-4 py-3"><button type="button" onClick={() => onOpenQuiz(quiz)} className="text-left"><span className="block font-semibold text-foreground hover:text-primary">{quiz.title}</span><span className="text-xs capitalize text-muted-foreground">{quiz.status} · {quiz.course || "No course"}</span></button></td><td className="px-3 py-3 text-right text-muted-foreground">{quiz.attempts_count}</td><td className={`px-3 py-3 text-right font-semibold ${quiz.attempts_count ? accuracyTone(quiz.avg_accuracy) : "text-muted-foreground"}`}>{quiz.attempts_count ? `${quiz.avg_accuracy}%` : "—"}</td><td className="px-3 py-3 text-right text-muted-foreground">{quiz.questions}</td><td className="whitespace-nowrap px-3 py-3 text-muted-foreground">{quiz.created_at ? new Date(quiz.created_at).toLocaleDateString() : "—"}</td><td className="px-4 py-3"><div className="flex justify-end gap-2"><button type="button" onClick={() => onOpenQuiz(quiz)} className="rounded-lg border px-3 py-1.5 text-xs font-semibold text-primary hover:bg-accent">Details</button><QuestionPaperButtons quizSetId={quiz.id} title={quiz.title} meta={[quiz.course, quiz.subject].filter(Boolean).join(" · ")} compact /></div></td></tr>)}</tbody>
                  </table>
                </div>
              )}
            </div>
          ) : (
            <div className="flex flex-col gap-5">
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
                {[
                  ["Teachers", analytics.summary.total_teachers],
                  ["Active 30 days", analytics.summary.active_teachers],
                  ["Avg accuracy", analytics.summary.total_attempts ? `${analytics.summary.avg_accuracy}%` : "—"],
                  ["Quiz sets", analytics.summary.total_quiz_sets],
                  ["Published", analytics.summary.total_published],
                  ["Attempts", analytics.summary.total_attempts],
                ].map(([label, value]) => <div key={label} className="rounded-xl border bg-secondary/25 p-4"><div className="text-xl font-bold text-foreground">{value}</div><div className="mt-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">{label}</div></div>)}
              </div>

              <div className="flex flex-wrap items-center justify-between gap-3"><div><h3 className="font-bold text-foreground">Faculty performance</h3><p className="text-sm text-muted-foreground">Select a teacher to inspect their quizzes.</p></div><select value={sort} onChange={(event) => setSort(event.target.value as FacultySort)} className="h-10 rounded-xl border border-input bg-background px-3 text-sm" aria-label="Sort faculty"><option value="attempts_desc">Most attempts</option><option value="accuracy_desc">Highest accuracy</option><option value="quizzes_desc">Most quizzes</option><option value="newest">Most recently active</option></select></div>
              <div className="overflow-x-auto rounded-xl border">
                <table className="w-full min-w-[760px] text-sm">
                  <thead className="bg-secondary/40 text-left text-xs uppercase tracking-wide text-muted-foreground"><tr><th className="px-4 py-3 font-medium">Teacher</th><th className="px-3 py-3 text-right font-medium">Quizzes</th><th className="px-3 py-3 text-right font-medium">Published</th><th className="px-3 py-3 text-right font-medium">Attempts</th><th className="px-3 py-3 text-right font-medium">Accuracy</th><th className="px-4 py-3 text-right font-medium">Action</th></tr></thead>
                  <tbody>{sortedTeachers.map((teacher) => { const state = health(teacher); return <tr key={teacher.teacher_id} className="border-t"><td className="px-4 py-3"><div className="flex items-center gap-3"><span className={`h-2.5 w-2.5 rounded-full ${state.dot}`} /><span><span className="block font-semibold text-foreground">{teacher.teacher_name}</span><span className="block text-xs text-muted-foreground">{teacher.course_names.join(", ") || "No quiz course yet"} · <span className={`rounded-full px-1.5 py-0.5 ${state.tone}`}>{state.label}</span></span></span></div></td><td className="px-3 py-3 text-right text-muted-foreground">{teacher.quiz_sets_created}</td><td className="px-3 py-3 text-right text-muted-foreground">{teacher.quiz_sets_published}</td><td className="px-3 py-3 text-right text-muted-foreground">{teacher.total_attempts}</td><td className={`px-3 py-3 text-right font-semibold ${teacher.total_attempts ? accuracyTone(teacher.avg_accuracy) : "text-muted-foreground"}`}>{teacher.total_attempts ? `${teacher.avg_accuracy}%` : "—"}</td><td className="px-4 py-3 text-right"><button type="button" onClick={() => viewTeacher(teacher)} className="font-semibold text-primary hover:underline">View quizzes →</button></td></tr>; })}</tbody>
                </table>
              </div>
              {sortedTeachers.length === 0 && <div className="rounded-xl border border-dashed p-8 text-center text-sm text-muted-foreground">No teachers have been added yet.</div>}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
