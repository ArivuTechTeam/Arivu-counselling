import { QuizExtractor } from "@/components/teacher/quiz-extractor";
import { FacultyTasks } from "@/components/teacher/faculty-tasks";

export default function ExtractPage() {
  return (
    <div className="mx-auto max-w-3xl">
      <FacultyTasks />
      <QuizExtractor />
    </div>
  );
}
