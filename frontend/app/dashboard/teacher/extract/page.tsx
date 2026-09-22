import Link from "next/link";

import { QuizExtractor } from "@/components/teacher/quiz-extractor";
import { FacultyTasks } from "@/components/teacher/faculty-tasks";
import { PageHeader } from "@/components/ui/page-header";

export default function ExtractPage() {
  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-5">
      <PageHeader
        title="Import an existing quiz"
        description="Upload a finished question paper or quiz image. We’ll extract its questions into a draft for you to verify and publish."
        actions={
          <Link
            href="/dashboard/teacher/generate"
            className="rounded-lg border border-input bg-card px-3 py-2 text-sm font-medium hover:bg-accent"
          >
            Create from study material instead
          </Link>
        }
      />
      <FacultyTasks />
      <QuizExtractor />
    </div>
  );
}
