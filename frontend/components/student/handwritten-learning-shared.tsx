"use client";

import Link from "next/link";
import type { ReactNode } from "react";

import type {
  EvaluationPaper,
  HandwrittenLevel,
  HandwrittenMistakeSeverity,
  HandwrittenRevisionPriority,
} from "@/lib/api";

// Pieces shared by the three handwritten learning pages (Mistake Library,
// Handwritten Revision, My Progress) so they look and behave the same.

const BASE = "/dashboard/student/handwritten-evaluation";

const TABS = [
  { key: "papers", label: "Exam Papers", href: BASE },
  { key: "submissions", label: "My Submissions", href: `${BASE}/submissions` },
  { key: "mistakes", label: "Mistake Library", href: `${BASE}/mistakes` },
  { key: "revision", label: "Handwritten Revision", href: `${BASE}/revision` },
  { key: "progress", label: "My Progress", href: `${BASE}/progress` },
] as const;

export type LearningTab = (typeof TABS)[number]["key"];

export function HandwrittenLearningNav({ active }: { active: LearningTab }) {
  return (
    <nav className="flex flex-wrap gap-2" aria-label="Handwritten evaluation">
      {TABS.map((tab) => (
        <Link
          key={tab.key}
          href={tab.href}
          aria-current={tab.key === active ? "page" : undefined}
          className={
            tab.key === active
              ? "rounded-full bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground"
              : "rounded-full border bg-card px-4 py-2 text-sm font-semibold text-muted-foreground transition hover:border-primary/40 hover:text-primary"
          }
        >
          {tab.label}
        </Link>
      ))}
    </nav>
  );
}

export function LearningHero({
  title,
  description,
  stats,
}: {
  title: string;
  description: string;
  stats?: ReactNode;
}) {
  return (
    <section className="relative overflow-hidden rounded-3xl bg-primary px-6 py-7 text-primary-foreground shadow-lg sm:px-8">
      <div className="absolute -right-12 -top-20 h-52 w-52 rounded-full bg-white/5" />
      <div className="relative flex flex-col gap-5 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h1 className="text-3xl font-black tracking-tight">{title}</h1>
          <p className="mt-1 text-sm text-white/75">{description}</p>
        </div>
        {stats ? <div className="flex flex-wrap items-center gap-2">{stats}</div> : null}
      </div>
    </section>
  );
}

export function HeroStat({ value, label }: { value: ReactNode; label: string }) {
  return (
    <span className="rounded-xl border border-white/20 bg-white/10 px-4 py-2 text-sm">
      <strong className="mr-1 text-lg">{value}</strong> {label}
    </span>
  );
}

// --- Subject filter ---------------------------------------------------------

export type SubjectOption = { id: string; name: string };

/** One entry per subject, taken from the papers the student can access. */
export function subjectOptionsFromPapers(papers: EvaluationPaper[]): SubjectOption[] {
  const byId = new Map<string, string>();
  for (const paper of papers) {
    if (!byId.has(paper.subject_id)) {
      byId.set(paper.subject_id, paper.subject_name || "Subject");
    }
  }
  return [...byId.entries()]
    .map(([id, name]) => ({ id, name }))
    .sort((a, b) => a.name.localeCompare(b.name));
}

export function SubjectSelect({
  subjects,
  value,
  onChange,
}: {
  subjects: SubjectOption[];
  value: string;
  onChange: (subjectId: string) => void;
}) {
  return (
    <select
      aria-label="Filter by subject"
      value={value}
      onChange={(event) => onChange(event.target.value)}
      className="min-h-10 rounded-full border bg-card px-4 text-sm font-semibold text-foreground"
    >
      <option value="">All subjects</option>
      {subjects.map((subject) => (
        <option key={subject.id} value={subject.id}>
          {subject.name}
        </option>
      ))}
    </select>
  );
}

export function FilterPills<T extends string>({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: { value: T; label: string }[];
  value: T;
  onChange: (value: T) => void;
}) {
  return (
    <div role="group" aria-label={label} className="flex max-w-full gap-2 overflow-x-auto pb-1">
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          aria-pressed={option.value === value}
          onClick={() => onChange(option.value)}
          className={`shrink-0 rounded-full px-4 py-2 text-sm font-semibold ${
            option.value === value
              ? "bg-primary text-primary-foreground"
              : "border bg-card text-muted-foreground hover:border-primary/35 hover:text-primary"
          }`}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

// --- Badges -----------------------------------------------------------------
// Every badge carries a text label, so colour is never the only signal.

const TONES = {
  red: "border-red-300 bg-red-50 text-red-700 dark:border-red-900 dark:bg-red-950/35 dark:text-red-300",
  amber: "border-amber-300 bg-amber-50 text-amber-700 dark:border-amber-900 dark:bg-amber-950/35 dark:text-amber-300",
  sky: "border-sky-300 bg-sky-50 text-sky-700 dark:border-sky-900 dark:bg-sky-950/35 dark:text-sky-300",
  emerald: "border-emerald-300 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950/35 dark:text-emerald-300",
  violet: "border-violet-300 bg-violet-50 text-violet-700 dark:border-violet-900 dark:bg-violet-950/35 dark:text-violet-300",
  slate: "border-slate-300 bg-slate-50 text-slate-700 dark:border-slate-700 dark:bg-slate-900/40 dark:text-slate-300",
} as const;

type Tone = keyof typeof TONES;

export function ToneBadge({ tone, children }: { tone: Tone; children: ReactNode }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-bold ${TONES[tone]}`}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current" />
      {children}
    </span>
  );
}

const SEVERITY: Record<HandwrittenMistakeSeverity, { tone: Tone; label: string }> = {
  major: { tone: "red", label: "Major" },
  moderate: { tone: "amber", label: "Moderate" },
  minor: { tone: "slate", label: "Minor" },
};

export function SeverityBadge({ severity }: { severity: HandwrittenMistakeSeverity }) {
  const { tone, label } = SEVERITY[severity] ?? SEVERITY.minor;
  return <ToneBadge tone={tone}>{label}</ToneBadge>;
}

const PRIORITY: Record<HandwrittenRevisionPriority, { tone: Tone; label: string }> = {
  high: { tone: "red", label: "High priority" },
  medium: { tone: "amber", label: "Medium priority" },
  low: { tone: "sky", label: "Low priority" },
};

export function PriorityBadge({ priority }: { priority: HandwrittenRevisionPriority }) {
  const { tone, label } = PRIORITY[priority] ?? PRIORITY.low;
  return <ToneBadge tone={tone}>{label}</ToneBadge>;
}

/** Sort order for revision items: high first. */
export const PRIORITY_RANK: Record<HandwrittenRevisionPriority, number> = {
  high: 0,
  medium: 1,
  low: 2,
};

export const LEVELS: { value: HandwrittenLevel; label: string; tone: Tone }[] = [
  { value: "beginner", label: "Beginner", tone: "slate" },
  { value: "improving", label: "Improving", tone: "amber" },
  { value: "proficient", label: "Proficient", tone: "sky" },
  { value: "advanced", label: "Advanced", tone: "emerald" },
  { value: "exam_ready", label: "Exam ready", tone: "violet" },
];

/** Level badge plus a five-step meter showing how far along the ladder the student is. */
export function LevelBadge({ level }: { level: HandwrittenLevel }) {
  const index = Math.max(0, LEVELS.findIndex((entry) => entry.value === level));
  const entry = LEVELS[index];
  return (
    <div className="flex items-center gap-3">
      <ToneBadge tone={entry.tone}>{entry.label}</ToneBadge>
      <div
        className="flex gap-1"
        role="img"
        aria-label={`Level ${index + 1} of ${LEVELS.length}`}
      >
        {LEVELS.map((step, stepIndex) => (
          <span
            key={step.value}
            className={`h-1.5 w-5 rounded-full ${
              stepIndex <= index ? "bg-primary" : "bg-muted"
            }`}
          />
        ))}
      </div>
    </div>
  );
}

// --- Formatting -------------------------------------------------------------

/** "step_loss" -> "Step loss" */
export function formatCategory(category: string): string {
  const text = category.replace(/_/g, " ").trim();
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** Marks come back as numeric strings or numbers; show at most one decimal. */
export function formatMarks(value: number | string | null | undefined): string {
  const number = Number(value ?? 0);
  return Number.isFinite(number) ? String(Math.round(number * 10) / 10) : "0";
}
