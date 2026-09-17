"use client";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorCard } from "@/components/ui/error-card";
import { PageHeader } from "@/components/ui/page-header";
import { SkeletonList } from "@/components/ui/skeleton";
import { usePlatformQuestionBank } from "@/lib/staff-queries";

function mixLabel(values: Record<string, number>) {
  const entries = Object.entries(values).sort((a, b) => b[1] - a[1]);
  if (entries.length === 0) return "No questions";
  return entries
    .slice(0, 3)
    .map(([name, count]) => `${name.replaceAll("_", " ")} ${count}`)
    .join(" · ");
}

export default function CoursesPage() {
  const { data = null, error, mutate } = usePlatformQuestionBank();

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Platform question bank"
        description="Review question coverage across every institution and course."
      />

      {error ? (
        <ErrorCard message={error.message} onRetry={() => void mutate()} />
      ) : data === null ? (
        <SkeletonList rows={5} />
      ) : data.courses.length === 0 ? (
        <EmptyState
          title="No course questions yet"
          message="Generated course questions will appear here with their review status."
        />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
            <Card>
              <CardContent className="p-5">
                <p className="text-2xl font-bold">{data.total}</p>
                <p className="mt-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Questions
                </p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="p-5">
                <p className="text-2xl font-bold">{data.courses.length}</p>
                <p className="mt-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Courses represented
                </p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="p-5">
                <p className="text-2xl font-bold">{data.uncategorised}</p>
                <p className="mt-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Uncategorised
                </p>
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardHeader>
              <CardTitle>Coverage by course</CardTitle>
              <CardDescription>
                Institution attribution and current content mix.
              </CardDescription>
            </CardHeader>
            <CardContent className="grid grid-cols-1 gap-3 lg:grid-cols-2">
              {data.courses.map((course, index) => (
                <article
                  key={`${course.tenant ?? "unknown"}-${course.course}-${index}`}
                  className="rounded-xl border bg-card p-4 shadow-sm"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <h2 className="font-semibold text-foreground">{course.course}</h2>
                      <p className="text-sm text-muted-foreground">
                        {course.tenant ?? "Unknown institution"}
                      </p>
                    </div>
                    <span className="rounded-full bg-brand-50 px-2.5 py-1 text-xs font-semibold text-brand-700">
                      {course.questions} questions
                    </span>
                  </div>
                  <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
                    <div className="rounded-lg bg-muted px-3 py-2">
                      <strong>{course.subjects}</strong>
                      <span className="ml-1 text-muted-foreground">subjects</span>
                    </div>
                    <div className="rounded-lg bg-muted px-3 py-2">
                      <strong>{course.chapters}</strong>
                      <span className="ml-1 text-muted-foreground">chapters</span>
                    </div>
                  </div>
                  <p className="mt-3 text-xs capitalize text-muted-foreground">
                    {mixLabel(course.types)}
                  </p>
                  <div className="mt-3 flex flex-wrap gap-1.5 text-[11px] font-medium">
                    <span className="rounded-full bg-emerald-50 px-2 py-1 text-emerald-700">
                      {course.review_status.approved} approved
                    </span>
                    <span className="rounded-full bg-amber-50 px-2 py-1 text-amber-700">
                      {course.review_status.pending_review} pending
                    </span>
                    <span className="rounded-full bg-orange-50 px-2 py-1 text-orange-700">
                      {course.review_status.needs_edit} needs edit
                    </span>
                    <span className="rounded-full bg-rose-50 px-2 py-1 text-rose-700">
                      {course.review_status.rejected} rejected
                    </span>
                  </div>
                </article>
              ))}
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}
