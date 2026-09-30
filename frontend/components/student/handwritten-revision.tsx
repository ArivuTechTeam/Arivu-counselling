"use client";

import { useState } from "react";

import type { HandwrittenRevisionItem } from "@/lib/api";
import {
  useStudentHandwrittenPapers,
  useStudentHandwrittenRevisionItems,
} from "@/lib/student-queries";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorCard } from "@/components/ui/error-card";
import { SkeletonList } from "@/components/ui/skeleton";
import { Trophy } from "@/components/ui/icons";
import {
  FilterPills,
  formatMarks,
  HandwrittenLearningNav,
  HeroStat,
  LearningHero,
  PRIORITY_RANK,
  PriorityBadge,
  SubjectSelect,
  subjectOptionsFromPapers,
  ToneBadge,
} from "@/components/student/handwritten-learning-shared";

type StateFilter = "unresolved" | "resolved" | "all";

const STATE_OPTIONS: { value: StateFilter; label: string }[] = [
  { value: "unresolved", label: "Unresolved" },
  { value: "resolved", label: "Resolved" },
  { value: "all", label: "All" },
];

// Left border colour repeats the priority badge so high items stand out in a long list.
const PRIORITY_BORDER = {
  high: "border-l-red-500",
  medium: "border-l-amber-500",
  low: "border-l-sky-400",
} as const;

function resolutionLabel(item: HandwrittenRevisionItem): string {
  if (!item.is_resolved) return "Unresolved";
  return item.resolution_source === "improved" ? "Resolved · improved" : "Resolved · reviewed";
}

function RevisionCard({
  item,
  subjectName,
}: {
  item: HandwrittenRevisionItem;
  subjectName: string | undefined;
}) {
  return (
    <article
      className={`rounded-2xl border border-l-4 bg-card p-5 shadow-sm ${
        PRIORITY_BORDER[item.priority] ?? PRIORITY_BORDER.low
      } ${item.is_resolved ? "opacity-75" : ""}`}
    >
      <div className="flex flex-wrap items-center gap-2">
        <PriorityBadge priority={item.priority} />
        <ToneBadge tone={item.is_resolved ? "emerald" : "amber"}>{resolutionLabel(item)}</ToneBadge>
        <span className="ml-auto text-sm font-bold text-destructive">
          {formatMarks(item.marks_at_risk)} marks at risk
        </span>
      </div>
      <h2 className="mt-3 font-bold leading-snug">{item.title}</h2>
      <p className="mt-0.5 text-xs text-muted-foreground">
        {subjectName ? `${subjectName} · ` : ""}
        {item.chapter}
      </p>
      {item.description ? (
        <p className="mt-2 text-sm text-muted-foreground">{item.description}</p>
      ) : null}
      <p className="mt-3 text-xs text-muted-foreground">
        Seen {item.occurrence_count} {item.occurrence_count === 1 ? "time" : "times"} across{" "}
        {item.source_count} {item.source_count === 1 ? "answer script" : "answer scripts"}
      </p>
    </article>
  );
}

export function HandwrittenRevision() {
  const [subjectId, setSubjectId] = useState("");
  const [state, setState] = useState<StateFilter>("unresolved");

  const papersQuery = useStudentHandwrittenPapers();
  const subjects = subjectOptionsFromPapers(papersQuery.data ?? []);
  const subjectNames = new Map(subjects.map((subject) => [subject.id, subject.name]));
  const revisionQuery = useStudentHandwrittenRevisionItems({
    subjectId: subjectId || undefined,
    resolved: state === "all" ? undefined : state === "resolved",
  });

  // Most urgent first: priority, then the marks still at stake.
  const items = revisionQuery.data
    ? [...revisionQuery.data].sort(
        (a, b) =>
          (PRIORITY_RANK[a.priority] ?? 3) - (PRIORITY_RANK[b.priority] ?? 3) ||
          Number(b.marks_at_risk) - Number(a.marks_at_risk),
      )
    : undefined;
  const marksAtRisk = (items ?? [])
    .filter((item) => !item.is_resolved)
    .reduce((sum, item) => sum + Number(item.marks_at_risk || 0), 0);
  const isFiltered = subjectId !== "" || state !== "unresolved";

  return (
    <div className="mx-auto w-full max-w-[1440px] space-y-6">
      <LearningHero
        title="Handwritten Revision"
        description="Topics from your answer scripts that cost you marks — work through them, most urgent first."
        stats={
          items ? (
            <>
              <HeroStat value={items.length} label="Items" />
              <HeroStat value={formatMarks(marksAtRisk)} label="Marks at risk" />
            </>
          ) : null
        }
      />

      <div className="flex flex-col gap-4">
        <HandwrittenLearningNav active="revision" />
        <div className="flex flex-wrap items-center gap-3">
          {subjects.length > 0 ? (
            <SubjectSelect subjects={subjects} value={subjectId} onChange={setSubjectId} />
          ) : null}
          <FilterPills
            label="Filter by status"
            options={STATE_OPTIONS}
            value={state}
            onChange={setState}
          />
        </div>
      </div>

      {revisionQuery.error ? (
        <ErrorCard
          title="We couldn't load your revision items"
          message={revisionQuery.error.message}
          onRetry={() => void revisionQuery.mutate()}
        />
      ) : items === undefined ? (
        <SkeletonList rows={4} />
      ) : items.length === 0 ? (
        <EmptyState
          icon={<Trophy size={22} />}
          title={isFiltered ? "No revision items match these filters" : "Nothing to revise right now"}
          message={
            isFiltered
              ? "Try a different subject or status."
              : "Topics that cost you marks will appear here after your answer scripts are evaluated."
          }
        />
      ) : (
        <div className="space-y-3">
          {items.map((item) => (
            <RevisionCard key={item.id} item={item} subjectName={subjectNames.get(item.subject_id)} />
          ))}
        </div>
      )}
    </div>
  );
}
