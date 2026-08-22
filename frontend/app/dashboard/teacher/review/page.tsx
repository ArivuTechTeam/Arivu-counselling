import { PageHeader } from "@/components/ui/page-header";
import { QuizSetList } from "@/components/quiz-set-list";

export default function ReviewQueuePage() {
  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6">
      <PageHeader
        title="Review queue"
        description="Generated quiz sets waiting for your review and publish."
      />
      <QuizSetList />
    </div>
  );
}
