import { QuizAttempt } from "@/components/student/quiz-attempt";

export default function AttemptPage({ params }: { params: { id: string } }) {
  return (
    <main className="mx-auto w-full max-w-[1440px] p-3 sm:p-4 xl:p-5">
      <QuizAttempt attemptId={params.id} />
    </main>
  );
}
