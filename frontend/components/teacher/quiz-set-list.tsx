"use client";

import Link from "next/link";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorCard } from "@/components/ui/error-card";
import { Inbox } from "@/components/ui/icons";
import { SkeletonList } from "@/components/ui/skeleton";
import { statusLabel } from "@/lib/format";
import { useTeacherQuizSets } from "@/lib/staff-queries";

const SET_TONE: Record<string, string> = {
  published: "border-emerald-200 bg-emerald-50 text-emerald-700",
  draft: "border-border bg-muted/70 text-muted-foreground",
  archived: "border-border bg-muted/70 text-muted-foreground",
};

export function QuizSetList() {
  const { data: sets = null, error, mutate } = useTeacherQuizSets();

  return (
    <Card className="overflow-hidden rounded-2xl border-primary/10 shadow-sm">
      <CardHeader className="space-y-1 border-b bg-muted/15 p-5 sm:p-6">
        <CardTitle className="text-2xl tracking-tight">Your quizzes</CardTitle>
        <CardDescription>Review and publish generated quizzes.</CardDescription>
      </CardHeader>
      <CardContent className={sets && sets.length > 0 ? "p-0" : "p-5 sm:p-6"}>
        {error ? (
          <ErrorCard message={error.message} onRetry={() => void mutate()} />
        ) : sets === null ? (
          <SkeletonList />
        ) : sets.length === 0 ? (
          <EmptyState
            icon={<Inbox />}
            title="No quizzes yet"
            message="Generate your first quiz to get started."
            action={
              <Link
                href="/dashboard/teacher/generate"
                className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground shadow-sm transition-colors hover:bg-primary/90"
              >
                Create a quiz
              </Link>
            }
          />
        ) : (
          <div className="divide-y divide-border">
            {sets.map((s) => (
              <Link
                key={s.id}
                href={`/dashboard/teacher/review/${s.id}`}
                className="group flex items-center justify-between gap-4 bg-card px-5 py-5 text-sm transition-colors hover:bg-primary/[0.035] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring sm:px-6"
              >
                <div className="min-w-0">
                  <p className="truncate text-base font-semibold tracking-tight text-foreground transition-colors group-hover:text-primary">
                    {s.title}
                  </p>
                  <p className="mt-1 text-[13px] text-muted-foreground">
                    Created {new Date(s.created_at).toLocaleDateString()}
                  </p>
                </div>
                <span className="flex shrink-0 items-center gap-3">
                  <span
                    className={`rounded-full border px-3 py-1.5 text-xs font-medium ${
                      SET_TONE[s.status] ?? "bg-muted text-muted-foreground"
                    }`}
                  >
                    {statusLabel(s.status)}
                  </span>
                  <span className="flex h-9 w-9 items-center justify-center rounded-full bg-muted text-base text-muted-foreground transition-all group-hover:translate-x-0.5 group-hover:bg-primary group-hover:text-primary-foreground">
                    →
                  </span>
                </span>
              </Link>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
