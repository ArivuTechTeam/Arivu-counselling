"use client";

import { AttemptHistoryList } from "@/components/student/test-history";
import { ErrorCard } from "@/components/ui/error-card";
import { PageHeader } from "@/components/ui/page-header";
import { SkeletonList } from "@/components/ui/skeleton";
import { useStudentAttempts } from "@/lib/student-queries";

export default function TestHistoryPage() {
  const { data: attempts, error, mutate, hasMore, loadMore, isLoadingMore } = useStudentAttempts();

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Quiz history"
        description="Review completed quizzes, topic practice and mock exams in one place."
      />
      {error ? (
        <ErrorCard message={error.message} onRetry={() => void mutate()} />
      ) : attempts === undefined ? (
        <SkeletonList />
      ) : (
        <>
          <AttemptHistoryList items={attempts} emptyScope="all" />
          {hasMore && (
            <button
              type="button"
              onClick={() => void loadMore()}
              disabled={isLoadingMore}
              className="self-center rounded-lg border border-input px-4 py-2 text-sm font-medium hover:border-primary/50 disabled:opacity-60"
            >
              {isLoadingMore ? "Loading…" : "Load more history"}
            </button>
          )}
        </>
      )}
    </div>
  );
}
