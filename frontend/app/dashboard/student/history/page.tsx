"use client";

import { AttemptHistoryList } from "@/components/student/test-history";
import { ErrorCard } from "@/components/ui/error-card";
import { PageHeader } from "@/components/ui/page-header";
import { SkeletonList } from "@/components/ui/skeleton";
import { useStudentAttempts } from "@/lib/student-queries";

export default function TestHistoryPage() {
  const { data: attempts, error, mutate } = useStudentAttempts();

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
        <AttemptHistoryList items={attempts} emptyScope="all" />
      )}
    </div>
  );
}
