import Link from "next/link";

import { BlueprintGenerator } from "@/components/teacher/blueprint-generator";
import { FacultyTasks } from "@/components/teacher/faculty-tasks";
import { PageHeader } from "@/components/ui/page-header";

export default function GeneratePage() {
  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-5">
      <PageHeader
        title="Create a quiz from study material"
        description="Upload a PDF or DOCX, choose its subject and chapter, then review the draft, assign batches, and publish."
        actions={
          <Link
            href="/dashboard/teacher/extract"
            className="rounded-lg border border-input bg-card px-3 py-2 text-sm font-medium hover:bg-accent"
          >
            Import an existing quiz instead
          </Link>
        }
      />
      <FacultyTasks />
      <BlueprintGenerator />
    </div>
  );
}
