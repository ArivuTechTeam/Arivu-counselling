"use client";

import Link from "next/link";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { InstitutionAnalytics } from "@/lib/api";

type Course = InstitutionAnalytics["course_perf"][number];

function tone(accuracy: number) {
  if (accuracy >= 70) return "bg-emerald-500";
  if (accuracy >= 40) return "bg-amber-500";
  return "bg-rose-500";
}

function CourseRow({ course, onClick }: { course: Course; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="w-full rounded-xl border p-3 text-left transition hover:border-primary/35 hover:bg-accent"
    >
      <span className="flex items-center justify-between gap-3">
        <span className="flex min-w-0 items-center gap-2">
          <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${tone(course.accuracy)}`} />
          <strong className="truncate text-sm">{course.name}</strong>
        </span>
        <strong className={course.accuracy >= 70 ? "text-emerald-700" : course.accuracy >= 40 ? "text-amber-700" : "text-rose-700"}>
          {course.attempts ? `${course.accuracy}%` : "—"}
        </strong>
      </span>
      <span className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
        <span>{course.students} students</span>
        <span>{course.attempts} attempts</span>
        <span>{course.published} published</span>
        {course.pending_review > 0 && (
          <span className="font-semibold text-amber-700">
            {course.pending_review} pending review
          </span>
        )}
      </span>
    </button>
  );
}

export function CourseHealthCard({
  courses,
  onSelect,
}: {
  courses: Course[];
  onSelect: (course: Course) => void;
}) {
  const withAttempts = courses.filter((course) => course.attempts > 0);
  const healthy = [...withAttempts]
    .filter((course) => course.accuracy >= 70)
    .sort((a, b) => b.accuracy - a.accuracy)
    .slice(0, 3);
  const problems = [...courses]
    .filter((course) => course.accuracy < 70 || course.pending_review > 0)
    .sort((a, b) => a.accuracy - b.accuracy || b.pending_review - a.pending_review)
    .slice(0, 2);

  return (
    <Card>
      <CardHeader className="gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <CardTitle>Course health</CardTitle>
          <CardDescription>Strong courses and the areas that need attention.</CardDescription>
        </div>
        <Link href="/dashboard/institution-admin/analytics#course-performance" className="text-sm font-semibold text-primary hover:underline">
          View all →
        </Link>
      </CardHeader>
      <CardContent className="grid gap-5 md:grid-cols-2">
        <section>
          <p className="mb-3 text-[11px] font-bold uppercase tracking-widest text-emerald-700">
            Healthy courses
          </p>
          <div className="space-y-2">
            {healthy.length ? healthy.map((course) => (
              <CourseRow key={course.course_id} course={course} onClick={() => onSelect(course)} />
            )) : <p className="rounded-xl border border-dashed p-4 text-sm text-muted-foreground">No course has reached 70% accuracy yet.</p>}
          </div>
        </section>
        <section>
          <p className="mb-3 text-[11px] font-bold uppercase tracking-widest text-rose-700">
            Courses needing help
          </p>
          <div className="space-y-2">
            {problems.length ? problems.map((course) => (
              <CourseRow key={course.course_id} course={course} onClick={() => onSelect(course)} />
            )) : <p className="rounded-xl border border-dashed p-4 text-sm text-muted-foreground">No course warnings right now.</p>}
          </div>
        </section>
      </CardContent>
    </Card>
  );
}
