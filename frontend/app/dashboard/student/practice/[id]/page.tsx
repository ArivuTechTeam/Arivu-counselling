import { QuizAttempt } from "@/components/quiz-attempt";

export default function PracticePage({ params }: { params: { id: string } }) {
  return (
    <main className="mx-auto max-w-5xl p-6 md:p-8">
      <QuizAttempt attemptId={params.id} source="practice" />
    </main>
  );
}
