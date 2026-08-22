import { QuizAttempt } from "@/components/quiz-attempt";

export default function AttemptPage({ params }: { params: { id: string } }) {
  return (
    <main className="mx-auto max-w-5xl p-6 md:p-8">
      <QuizAttempt attemptId={params.id} />
    </main>
  );
}
