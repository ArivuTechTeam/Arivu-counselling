"use client";

import { ChevronDown } from "@/components/ui/icons";
import { TeacherAnalyticsDetail } from "@/lib/api";

function accuracyTone(value: number) {
  if (value >= 70) return "text-emerald-700";
  if (value >= 40) return "text-amber-700";
  return "text-rose-700";
}

function activity(teacher: TeacherAnalyticsDetail) {
  if (!teacher.is_active) {
    return { label: "Low activity", badge: "bg-rose-100 text-rose-700", dot: "bg-rose-500" };
  }
  if (teacher.total_attempts < 5) {
    return { label: "Building engagement", badge: "bg-amber-100 text-amber-800", dot: "bg-amber-400" };
  }
  return {
    label: "Active",
    badge: "bg-emerald-100 text-emerald-700",
    dot: "bg-emerald-500",
  };
}

export function FacultyAnalysisCard({
  teacher,
  onOpen,
}: {
  teacher: TeacherAnalyticsDetail;
  onOpen: () => void;
}) {
  const state = activity(teacher);
  const initials = teacher.teacher_name
    .split(" ")
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("") || "T";

  return (
    <button
      type="button"
      onClick={onOpen}
      className="animate-rise w-full overflow-hidden rounded-2xl border border-border bg-card text-left shadow-sm transition hover:-translate-y-0.5 hover:border-primary/35 hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
    >
      <div className="flex items-start justify-between gap-4 p-5">
        <div className="flex min-w-0 items-center gap-3">
          <span className="inline-flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-sm font-bold text-primary">
            {initials}
          </span>
          <span className="min-w-0">
            <span className="block truncate text-base font-bold text-foreground">
              {teacher.teacher_name}
            </span>
            <span className="mt-1 block truncate text-sm text-muted-foreground">
              {teacher.course_names.join(", ") || "No quiz course yet"}
            </span>
          </span>
        </div>
        <span className={`inline-flex shrink-0 items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold ${state.badge}`}>
          <span className={`h-2 w-2 rounded-full ${state.dot}`} />
          {state.label}
        </span>
      </div>

      <div className="grid grid-cols-4 divide-x border-y bg-secondary/25 py-3 text-center">
        <span>
          <span className="block text-lg font-bold text-foreground">{teacher.quiz_sets_created}</span>
          <span className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Quizzes</span>
        </span>
        <span>
          <span className="block text-lg font-bold text-foreground">{teacher.quiz_sets_published}</span>
          <span className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Published</span>
        </span>
        <span>
          <span className="block text-lg font-bold text-foreground">{teacher.total_attempts}</span>
          <span className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Attempts</span>
        </span>
        <span>
          <span className={`block text-lg font-bold ${teacher.total_attempts ? accuracyTone(teacher.avg_accuracy) : "text-muted-foreground"}`}>
            {teacher.total_attempts ? `${teacher.avg_accuracy}%` : "—"}
          </span>
          <span className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Accuracy</span>
        </span>
      </div>

      <div className="flex items-center justify-between gap-3 px-5 py-3 text-xs">
        <span className="text-muted-foreground">
          Last quiz: {teacher.last_quiz_created ? new Date(teacher.last_quiz_created).toLocaleDateString() : "Not created yet"}
        </span>
        <span className="inline-flex items-center gap-1.5 font-semibold text-primary">
          View quizzes <ChevronDown size={15} className="-rotate-90" />
        </span>
      </div>
    </button>
  );
}
