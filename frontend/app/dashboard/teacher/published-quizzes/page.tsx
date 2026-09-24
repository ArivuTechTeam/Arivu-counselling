"use client";

import Link from "next/link";
import { useState } from "react";

import { AssignBatchesDialog } from "@/components/teacher/assign-batches-dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorCard } from "@/components/ui/error-card";
import { PageHeader } from "@/components/ui/page-header";
import { SkeletonList } from "@/components/ui/skeleton";
import { Inbox } from "@/components/ui/icons";
import { QuestionPaperButtons } from "@/components/shared/pdf-buttons";
import { useTeacherPublishedQuizzes } from "@/lib/staff-queries";
import { useDashboardIdentity } from "@/components/shared/dashboard-identity-context";

function dateLabel(value: string | null) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

export default function PublishedQuizzesPage() {
  const { features } = useDashboardIdentity();
  const { data, error, mutate } = useTeacherPublishedQuizzes();
  const quizzes = data?.quizzes ?? [];
  const [assignQuiz, setAssignQuiz] = useState<{ id: string; title: string } | null>(null);
  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-6">
      <PageHeader title="Published quizzes" description="Monitor attendance and results for every quiz your students can take." />
      {error ? <ErrorCard message={error.message} onRetry={() => void mutate()} /> : !data ? <SkeletonList rows={5} /> : quizzes.length === 0 ? (
        <EmptyState icon={<Inbox />} title="No published quizzes" message="Publish a reviewed quiz to start monitoring student performance." action={<Link href="/dashboard/teacher/review" className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground">Open review queue</Link>} />
      ) : (
        <div className="grid gap-4">
          {quizzes.map((quiz) => (
            <article key={quiz.id} className="rounded-2xl border bg-card p-5 shadow-sm">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                  <p className="text-lg font-semibold tracking-tight">{quiz.title}</p>
                  <p className="mt-1 text-sm text-muted-foreground">{quiz.subject} · Published {dateLabel(quiz.published_at)}</p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  {/* Reuse the same paper generator as the review flow so a
                      published quiz can still be printed/reused. Read-only:
                      it only reads the approved questions, never mutates a
                      released paper. */}
                  <QuestionPaperButtons
                    quizSetId={quiz.id}
                    title={quiz.title}
                    meta={`${quiz.subject} · Published ${dateLabel(quiz.published_at)}`}
                    compact
                  />
                  <Link href={`/dashboard/teacher/performance/${quiz.id}`} className="rounded-lg border border-input px-3 py-2 text-sm font-medium hover:border-primary/50 hover:text-primary">View performance →</Link>
                  {features.batches && <button
                    type="button"
                    onClick={() => setAssignQuiz({ id: quiz.id, title: quiz.title })}
                    className="rounded-lg border border-input px-3 py-2 text-sm font-medium hover:border-primary/50 hover:text-primary"
                  >
                    Assign to batches
                  </button>}
                </div>
              </div>
              <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
                <Metric label="Eligible" value={quiz.eligible_students} />
                <Metric label="Completed" value={quiz.completed_students} tone="text-emerald-600" />
                <Metric label="Not started" value={quiz.not_started_students} />
                <Metric label="Attempts" value={quiz.total_attempts} />
                <Metric label="Average" value={`${quiz.average_accuracy}%`} tone="text-primary" />
                <Metric label="Last activity" value={dateLabel(quiz.last_activity)} />
              </div>
              <p className="mt-4 text-xs text-muted-foreground">Highest {quiz.highest_accuracy}% · Lowest {quiz.lowest_accuracy}%</p>
            </article>
          ))}
        </div>
      )}
      {features.batches && assignQuiz && (
        <AssignBatchesDialog
          quizSetId={assignQuiz.id}
          quizTitle={assignQuiz.title}
          onClose={() => setAssignQuiz(null)}
        />
      )}
    </div>
  );
}

function Metric({ label, value, tone = "" }: { label: string; value: string | number; tone?: string }) {
  return <div className="rounded-xl bg-muted/50 p-3"><p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">{label}</p><p className={`mt-1 text-lg font-semibold ${tone}`}>{value}</p></div>;
}
