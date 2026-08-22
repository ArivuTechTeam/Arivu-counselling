import Link from "next/link";

import { PageHeader } from "@/components/ui/page-header";
import { WeakAreaAnalysis } from "@/components/weak-area-analysis";

export default function WeakAreasPage() {
  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6">
      <Link
        href="/dashboard/student"
        className="text-sm text-muted-foreground transition-colors hover:text-primary"
      >
        ← Back to dashboard
      </Link>
      <PageHeader
        title="Weak-area analysis"
        description="Drill from subject to chapter to topic to see exactly where to focus."
      />
      <WeakAreaAnalysis />
    </div>
  );
}
