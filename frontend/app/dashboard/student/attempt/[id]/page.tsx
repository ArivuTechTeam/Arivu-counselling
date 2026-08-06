import { QuizAttempt } from "@/components/quiz-attempt";

export default function AttemptPage({ params }: { params: { id: string } }) {
  return (
    <main className="mx-auto max-w-2xl p-8">
      <QuizAttempt attemptId={params.id} />
    </main>
  );
}
