import Link from "next/link";

import { MockExamPanel } from "@/components/student/mock-exam-panel";
import { TopicPracticePanel } from "@/components/student/topic-practice-panel";
import { Clock, Zap } from "@/components/ui/icons";
import { PageHeader } from "@/components/ui/page-header";

type SearchParams = { mode?: string | string[]; institution?: string | string[] };

export default function PracticeAndMockPage({
  searchParams,
}: {
  searchParams?: SearchParams;
}) {
  const mode = searchParams?.mode === "mock" ? "mock" : "topic";
  const institution = typeof searchParams?.institution === "string"
    ? searchParams.institution
    : null;
  const modeHref = (nextMode: "topic" | "mock") => {
    const params = new URLSearchParams({ mode: nextMode });
    if (institution) params.set("institution", institution);
    return `/dashboard/student/practice?${params.toString()}`;
  };

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
      <PageHeader
        title="Practice & Mock Tests"
        description="Choose focused practice or prepare under exam conditions. Both use your institution’s approved questions."
      />

      <nav aria-label="Choose practice mode" className="grid gap-3 sm:grid-cols-2">
        <Link
          href={modeHref("topic")}
          aria-current={mode === "topic" ? "page" : undefined}
          className={`flex min-h-28 items-start gap-4 rounded-xl border p-5 text-left shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
            mode === "topic"
              ? "border-primary bg-primary/[0.06]"
              : "bg-card hover:border-primary/40 hover:bg-accent/30"
          }`}
        >
          <span className="rounded-lg bg-primary/10 p-2.5 text-primary"><Zap size={20} /></span>
          <span>
            <span className="block text-base font-semibold">Topic Practice</span>
            <span className="mt-1 block text-sm text-muted-foreground">
              Pick a subject, question count and difficulty. Untimed, with no wrong-answer penalty.
            </span>
          </span>
        </Link>
        <Link
          href={modeHref("mock")}
          aria-current={mode === "mock" ? "page" : undefined}
          className={`flex min-h-28 items-start gap-4 rounded-xl border p-5 text-left shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
            mode === "mock"
              ? "border-primary bg-primary/[0.06]"
              : "bg-card hover:border-primary/40 hover:bg-accent/30"
          }`}
        >
          <span className="rounded-lg bg-primary/10 p-2.5 text-primary"><Clock size={20} /></span>
          <span>
            <span className="block text-base font-semibold">Mock Exam</span>
            <span className="mt-1 block text-sm text-muted-foreground">
              Follow your institution’s exam pattern, time limit and marking rules.
            </span>
          </span>
        </Link>
      </nav>

      <section aria-label={mode === "mock" ? "Mock exam setup" : "Topic practice setup"}>
        {mode === "mock" ? <MockExamPanel /> : <TopicPracticePanel />}
      </section>
    </div>
  );
}
