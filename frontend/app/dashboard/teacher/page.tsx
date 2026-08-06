import { DocumentUpload } from "@/components/document-upload";
import { QuizGenerator } from "@/components/quiz-generator";
import { QuizSetList } from "@/components/quiz-set-list";

export default function TeacherDashboard() {
  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6">
      <DocumentUpload />
      <QuizGenerator />
      <QuizSetList />
    </div>
  );
}
