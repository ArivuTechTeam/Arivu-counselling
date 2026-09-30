"use client";

import Link from "next/link";
import { useState } from "react";

import {
  type HandwrittenMistake,
  type HandwrittenMistakeSeverity,
} from "@/lib/api";
import {
  useStudentHandwrittenMistakes,
  useStudentHandwrittenPapers,
} from "@/lib/student-queries";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorCard } from "@/components/ui/error-card";
import { SkeletonList } from "@/components/ui/skeleton";
import { Inbox } from "@/components/ui/icons";
import {
  FilterPills,
  formatCategory,
  formatMarks,
  HandwrittenLearningNav,
  HeroStat,
  LearningHero,
  SeverityBadge,
  SubjectSelect,
  subjectOptionsFromPapers,
  ToneBadge,
} from "@/components/student/handwritten-learning-shared";

type SeverityFilter = "all" | HandwrittenMistakeSeverity;

const SEVERITY_OPTIONS: { value: SeverityFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "major", label: "Major" },
  { value: "moderate", label: "Moderate" },
  { value: "minor", label: "Minor" },
];

const REPORT_BASE = "/dashboard/student/handwritten-evaluation/submissions";

/** "Business Law · Mock Test 1" with a link to the full report when the submission is known. */
function MistakeSource({
  mistake,
  subjectName,
}: {
  mistake: HandwrittenMistake;
  subjectName: string | undefined;
}) {
  const source = [subjectName, mistake.paper_title].filter(Boolean).join(" · ");
  if (!source) return null;
  return (
    <p className="mt-1 flex flex-wrap items-center gap-x-3 text-xs text-muted-foreground">
      <span>From: {source}</span>
      {mistake.submission_id ? (
        <Link
          href={`${REPORT_BASE}/${mistake.submission_id}`}
          className="font-semibold text-primary hover:underline"
        >
          View report
        </Link>
      ) : null}
    </p>
  );
}

function MistakeCard({
  mistake,
  subjectName,
}: {
  mistake: HandwrittenMistake;
  subjectName: string | undefined;
}) {
  return (
    <article className="rounded-2xl border bg-card p-5 shadow-sm">
      <div className="flex flex-wrap items-center gap-2">
        <SeverityBadge severity={mistake.severity} />
        <span className="rounded-full bg-muted px-3 py-1 text-xs font-semibold text-muted-foreground">
          {formatCategory(mistake.category)}
        </span>
        {mistake.is_recurring ? <ToneBadge tone="amber">Recurring</ToneBadge> : null}
        <span className="ml-auto text-sm font-bold text-destructive">
          −{formatMarks(mistake.marks_lost)} marks
        </span>
      </div>
      <p className="mt-3 font-semibold leading-snug">{mistake.description}</p>
      {mistake.suggestion ? (
        <p className="mt-2 rounded-lg bg-primary/5 px-3 py-2 text-sm text-muted-foreground">
          <span className="font-semibold text-foreground">How to improve: </span>
          {mistake.suggestion}
        </p>
      ) : null}
      <p className="mt-3 text-xs text-muted-foreground">Chapter: {mistake.chapter_name}</p>
      <MistakeSource mistake={mistake} subjectName={subjectName} />
    </article>
  );
}

export function HandwrittenMistakes() {
  const [subjectId, setSubjectId] = useState("");
  const [severity, setSeverity] = useState<SeverityFilter>("all");

  const papersQuery = useStudentHandwrittenPapers();
  const subjects = subjectOptionsFromPapers(papersQuery.data ?? []);
  const subjectNames = new Map(subjects.map((subject) => [subject.id, subject.name]));
  const mistakesQuery = useStudentHandwrittenMistakes({
    subjectId: subjectId || undefined,
    severity: severity === "all" ? undefined : severity,
  });

  const mistakes = mistakesQuery.data;
  const totalLost = (mistakes ?? []).reduce((sum, item) => sum + Number(item.marks_lost || 0), 0);
  const isFiltered = subjectId !== "" || severity !== "all";

  return (
    <div className="mx-auto w-full max-w-[1440px] space-y-6">
      <LearningHero
        title="Mistake Library"
        description="Every mark you lost in your evaluated answer scripts, with how to fix it."
        stats={
          mistakes ? (
            <>
              <HeroStat value={mistakes.length} label="Mistakes" />
              <HeroStat value={formatMarks(totalLost)} label="Marks lost" />
            </>
          ) : null
        }
      />

      <div className="flex flex-col gap-4">
        <HandwrittenLearningNav active="mistakes" />
        <div className="flex flex-wrap items-center gap-3">
          {subjects.length > 0 ? (
            <SubjectSelect subjects={subjects} value={subjectId} onChange={setSubjectId} />
          ) : null}
          <FilterPills
            label="Filter by severity"
            options={SEVERITY_OPTIONS}
            value={severity}
            onChange={setSeverity}
          />
        </div>
      </div>

      {mistakesQuery.error ? (
        <ErrorCard
          title="We couldn't load your mistakes"
          message={mistakesQuery.error.message}
          onRetry={() => void mistakesQuery.mutate()}
        />
      ) : mistakes === undefined ? (
        <SkeletonList rows={4} />
      ) : mistakes.length === 0 ? (
        <EmptyState
          icon={<Inbox size={22} />}
          title={isFiltered ? "No mistakes match these filters" : "No mistakes recorded yet"}
          message={
            isFiltered
              ? "Try a different subject or severity."
              : "Once an answer script is evaluated, the marks you lost show up here."
          }
        />
      ) : (
        <div className="space-y-3">
          {mistakes.map((mistake) => (
            <MistakeCard
              key={mistake.id}
              mistake={mistake}
              subjectName={mistake.subject_id ? subjectNames.get(mistake.subject_id) : undefined}
            />
          ))}
        </div>
      )}
    </div>
  );
}
