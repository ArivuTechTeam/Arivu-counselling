import { QuizAttempt } from "@/components/student/quiz-attempt";

export default async function PracticePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <main className="mx-auto w-full max-w-[1440px] p-3 sm:p-4 xl:p-5">
      <QuizAttempt attemptId={id} source="practice" />
    </main>
  );
}
