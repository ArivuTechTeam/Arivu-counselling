"use client";

import Link from "next/link";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { InstitutionAnalytics } from "@/lib/api";

type Teacher = InstitutionAnalytics["teacher_activity"][number];

function relativeDate(value: string | null) {
  if (!value) return "Never active";
  const days = Math.max(0, Math.floor((Date.now() - Date.parse(value)) / 86_400_000));
  if (days === 0) return "Today";
  if (days === 1) return "Yesterday";
  return `${days} days ago`;
}

function activeThisWeek(value: string | null) {
  if (!value) return false;
  return Date.now() - Date.parse(value) <= 7 * 86_400_000;
}

export function TeacherActivityCard({
  teachers,
  onSelect,
}: {
  teachers: Teacher[];
  onSelect: (teacher: Teacher) => void;
}) {
  const active = [...teachers]
    .filter((teacher) => activeThisWeek(teacher.last_quiz_created))
    .sort((a, b) => b.attempts - a.attempts)
    .slice(0, 3);
  const inactive = teachers
    .filter((teacher) => !activeThisWeek(teacher.last_quiz_created))
    .sort(
      (a, b) =>
        Date.parse(b.last_quiz_created ?? "1970-01-01") -
        Date.parse(a.last_quiz_created ?? "1970-01-01"),
    )
    .slice(0, 2);

  return (
    <Card>
      <CardHeader className="gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <CardTitle>Teacher activity</CardTitle>
          <CardDescription>Content, engagement, and the last quiz created.</CardDescription>
        </div>
        <Link href="/dashboard/institution-admin/quizzes" className="text-sm font-semibold text-primary hover:underline">
          View faculty →
        </Link>
      </CardHeader>
      <CardContent className="space-y-2">
        {active.map((teacher) => (
          <button
            key={teacher.teacher_id}
            type="button"
            onClick={() => onSelect(teacher)}
            className="grid w-full gap-3 rounded-xl border p-3 text-left transition hover:border-primary/35 hover:bg-accent sm:grid-cols-[1fr_auto] sm:items-center"
          >
            <span className="min-w-0">
              <span className="flex items-center gap-2">
                <span className="h-2.5 w-2.5 rounded-full bg-emerald-500" />
                <strong className="truncate text-sm">{teacher.name}</strong>
              </span>
              <span className="mt-1 block text-xs text-muted-foreground">
                {teacher.quiz_sets} sets · {teacher.published} published · {teacher.attempts} attempts
              </span>
            </span>
            <span className="text-right">
              <strong className={teacher.accuracy >= 70 ? "text-emerald-700" : teacher.accuracy >= 40 ? "text-amber-700" : "text-rose-700"}>
                {teacher.attempts ? `${teacher.accuracy}%` : "—"}
              </strong>
              <span className="block text-[11px] text-muted-foreground">
                {relativeDate(teacher.last_quiz_created)} →
              </span>
            </span>
          </button>
        ))}
        {active.length === 0 && (
          <p className="rounded-xl border border-dashed p-4 text-sm text-muted-foreground">
            No teacher has created a quiz yet.
          </p>
        )}
        {inactive.map((teacher) => (
          <button
            key={teacher.teacher_id}
            type="button"
            onClick={() => onSelect(teacher)}
            className="flex w-full items-center justify-between gap-3 rounded-xl border border-amber-200 bg-amber-50 p-3 text-left hover:bg-amber-100/70"
          >
            <span>
              <strong className="block text-sm">{teacher.name}</strong>
              <span className="text-xs text-amber-800">
                Last quiz: {relativeDate(teacher.last_quiz_created)}
              </span>
            </span>
            <span className="text-xs font-semibold text-amber-800">Check teacher →</span>
          </button>
        ))}
      </CardContent>
    </Card>
  );
}
