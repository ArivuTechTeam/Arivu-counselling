import { PageHeader } from "@/components/ui/page-header";
import { QuizSetList } from "@/components/teacher/quiz-set-list";

export default function ReviewQueuePage() {
  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6">
      <PageHeader
        title="Review queue"
        description="Quizzes waiting for you to review and publish."
      />
      <QuizSetList />
    </div>
  );
}
