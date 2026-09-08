"use client";

import { BarChart3, ChevronDown, Users } from "@/components/ui/icons";
import { TeacherAnalytics } from "@/lib/api";

function accuracyTone(value: number) {
  if (value >= 70) return "text-emerald-700";
  if (value >= 40) return "text-amber-700";
  return "text-rose-700";
}

export function FacultyAnalysisCard({
  analytics,
  onOpen,
}: {
  analytics: TeacherAnalytics | null;
  onOpen: () => void;
}) {
  if (!analytics) {
    return <div className="h-64 animate-pulse rounded-2xl border bg-card" />;
  }

  const { summary, teachers } = analytics;
  return (
    <button
      type="button"
      onClick={onOpen}
      className="animate-rise w-full overflow-hidden rounded-2xl border border-emerald-200 bg-gradient-to-br from-white via-emerald-50/70 to-emerald-100/60 text-left shadow-sm transition hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
    >
      <div className="flex items-start justify-between gap-4 border-b border-emerald-200/70 p-5 sm:p-6">
        <div className="flex items-start gap-3">
          <span className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-primary text-primary-foreground">
            <Users size={22} />
          </span>
          <div>
            <p className="text-xs font-semibold uppercase tracking-widest text-primary">Faculty analysis</p>
            <h2 className="mt-1 text-xl font-bold text-foreground">Faculty performance</h2>
            <p className="mt-1 text-sm text-muted-foreground">Compare content activity, engagement, and student outcomes.</p>
          </div>
        </div>
        <span className="inline-flex shrink-0 items-center gap-2 rounded-full bg-white/80 px-3 py-2 text-xs font-semibold text-primary shadow-sm">
          Open analysis <ChevronDown size={15} className="-rotate-90" />
        </span>
      </div>

      <div className="grid grid-cols-2 gap-px bg-emerald-200/60 sm:grid-cols-3 lg:grid-cols-6">
        {[
          ["Teachers", summary.total_teachers],
          ["Active", summary.active_teachers],
          ["Avg accuracy", summary.total_attempts ? `${summary.avg_accuracy}%` : "—"],
          ["Quiz sets", summary.total_quiz_sets],
          ["Published", summary.total_published],
          ["Attempts", summary.total_attempts],
        ].map(([label, value]) => (
          <div key={label} className="bg-white/75 px-4 py-3">
            <div className="text-lg font-bold text-foreground">{value}</div>
            <div className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">{label}</div>
          </div>
        ))}
      </div>

      <div className="grid gap-2 p-4 sm:grid-cols-3 sm:p-5">
        {teachers.slice(0, 3).map((teacher) => (
          <div key={teacher.teacher_id} className="flex items-center gap-3 rounded-xl border border-emerald-100 bg-white/80 p-3">
            <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${teacher.is_active ? (teacher.total_attempts >= 5 ? "bg-emerald-500" : "bg-amber-400") : "bg-rose-500"}`} />
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm font-semibold text-foreground">{teacher.teacher_name}</span>
              <span className="block truncate text-xs text-muted-foreground">{teacher.course_names.join(", ") || "No quiz course yet"}</span>
            </span>
            <span className={`text-sm font-bold ${teacher.total_attempts ? accuracyTone(teacher.avg_accuracy) : "text-muted-foreground"}`}>
              {teacher.total_attempts ? `${teacher.avg_accuracy}%` : "—"}
            </span>
          </div>
        ))}
        {teachers.length === 0 && (
          <div className="col-span-full flex items-center gap-2 rounded-xl border border-dashed bg-white/70 p-4 text-sm text-muted-foreground">
            <BarChart3 size={18} /> Faculty metrics will appear after teachers are added.
          </div>
        )}
        {teachers.length > 3 && <p className="col-span-full text-xs font-semibold text-primary">+{teachers.length - 3} more teacher{teachers.length - 3 === 1 ? "" : "s"}</p>}
      </div>
    </button>
  );
}
