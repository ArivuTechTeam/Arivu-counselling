"use client";

import type { HandwrittenAnalytics } from "@/lib/api";
import {
  useStudentHandwrittenAnalytics,
  useStudentHandwrittenPapers,
  useStudentHandwrittenWeakAreas,
} from "@/lib/student-queries";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorCard } from "@/components/ui/error-card";
import { MiniSparkline } from "@/components/ui/mini-sparkline";
import { Skeleton, SkeletonList } from "@/components/ui/skeleton";
import { TrendingUp } from "@/components/ui/icons";
import {
  formatCategory,
  formatMarks,
  HandwrittenLearningNav,
  LearningHero,
  LevelBadge,
  PriorityBadge,
  subjectOptionsFromPapers,
  type SubjectOption,
} from "@/components/student/handwritten-learning-shared";

const RECENT_ATTEMPTS = 5;

/**
 * Fit the sparkline to the student's own score range. The default 0-100 scale
 * makes a climb from 48% to 71% look almost flat.
 */
function trendRange(values: number[]): { min: number; max: number } {
  if (values.length < 2) return { min: 0, max: 100 };
  return {
    min: Math.max(0, Math.floor(Math.min(...values)) - 5),
    max: Math.min(100, Math.ceil(Math.max(...values)) + 5),
  };
}

function percent(value: number | string): string {
  return `${formatMarks(value)}%`;
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl bg-muted/50 px-4 py-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-0.5 text-xl font-extrabold">{value}</p>
    </div>
  );
}

function ImprovementRate({ rate }: { rate: number }) {
  const value = Number(rate) || 0;
  if (value === 0) {
    return <span className="text-sm text-muted-foreground">Holding steady</span>;
  }
  const improving = value > 0;
  return (
    <span
      className={`text-sm font-semibold ${
        improving ? "text-emerald-700 dark:text-emerald-300" : "text-red-700 dark:text-red-300"
      }`}
    >
      {improving ? "▲ +" : "▼ "}
      {formatMarks(value)} pts per attempt
    </span>
  );
}

function AnalyticsBody({ analytics }: { analytics: HandwrittenAnalytics }) {
  const history = Array.isArray(analytics.score_history) ? analytics.score_history : [];
  const values = history.map((point) => Number(point.percentage));
  const rate = Number(analytics.improvement_rate) || 0;
  const { min, max } = trendRange(values);
  const tone = rate > 0 ? "emerald" : rate < 0 ? "rose" : "primary";
  const recent = history.slice(-RECENT_ATTEMPTS).reverse();

  return (
    <div className="space-y-4">
      <LevelBadge level={analytics.current_level} />
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Attempts" value={String(analytics.total_attempts)} />
        <Stat label="Average" value={percent(analytics.avg_percentage)} />
        <Stat label="Best" value={percent(analytics.best_percentage)} />
        <Stat label="Latest" value={percent(analytics.latest_percentage)} />
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border px-4 py-3">
        <div>
          <p className="text-xs text-muted-foreground">Score trend</p>
          <ImprovementRate rate={rate} />
        </div>
        <MiniSparkline values={values} tone={tone} min={min} max={max} width={180} height={52} />
      </div>
      {recent.length > 0 ? (
        <ul className="divide-y rounded-xl border text-sm" aria-label="Recent attempts">
          {recent.map((point) => (
            <li key={point.evaluation_id} className="flex justify-between px-4 py-2">
              <span className="text-muted-foreground">{point.date || "—"}</span>
              <span className="font-semibold">{percent(point.percentage)}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function SubjectProgressCard({ subject }: { subject: SubjectOption }) {
  const query = useStudentHandwrittenAnalytics(subject.id);
  const analytics = query.data;

  return (
    <section className="rounded-2xl border bg-card p-5 shadow-sm" aria-label={`${subject.name} progress`}>
      <h2 className="mb-4 text-lg font-bold">{subject.name}</h2>
      {query.error ? (
        <ErrorCard
          title={`We couldn't load ${subject.name} progress`}
          message={query.error.message}
          onRetry={() => void query.mutate()}
        />
      ) : analytics === undefined ? (
        <Skeleton className="h-40 w-full rounded-xl" />
      ) : analytics === null ? (
        <p className="text-sm text-muted-foreground">
          No evaluated answer scripts for this subject yet.
        </p>
      ) : (
        <AnalyticsBody analytics={analytics} />
      )}
    </section>
  );
}

// Computed live by the backend from current mistakes and unresolved revision items.
function WeakAreasPanel({ subjects }: { subjects: SubjectOption[] }) {
  const query = useStudentHandwrittenWeakAreas();
  const subjectNames = new Map(subjects.map((subject) => [subject.id, subject.name]));
  const data = query.data;

  return (
    <section className="rounded-2xl border bg-card p-5 shadow-sm" aria-label="Weak areas">
      <h2 className="text-lg font-bold">Weak areas</h2>
      <p className="mb-4 text-sm text-muted-foreground">
        Where you are losing the most marks right now.
      </p>
      {query.error ? (
        <ErrorCard
          title="We couldn't load your weak areas"
          message={query.error.message}
          onRetry={() => void query.mutate()}
        />
      ) : data === undefined ? (
        <SkeletonList rows={3} />
      ) : data.weak_chapters.length === 0 && data.mistake_patterns.length === 0 ? (
        <p className="text-sm text-muted-foreground">No weak areas found — nothing is costing you marks.</p>
      ) : (
        <div className="grid gap-6 md:grid-cols-2">
          <div>
            <h3 className="mb-2 text-sm font-semibold">Chapters to revise</h3>
            <ul className="space-y-2">
              {data.weak_chapters.slice(0, 5).map((chapter) => (
                <li
                  key={`${chapter.subject_id}-${chapter.chapter}-${chapter.title}`}
                  className="rounded-xl border px-4 py-3"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <PriorityBadge priority={chapter.priority} />
                    <span className="ml-auto text-sm font-bold text-destructive">
                      {formatMarks(chapter.marks_at_risk)} marks at risk
                    </span>
                  </div>
                  <p className="mt-2 text-sm font-semibold">{chapter.title}</p>
                  <p className="text-xs text-muted-foreground">
                    {subjectNames.get(chapter.subject_id) ?? "Subject"} · {chapter.chapter}
                  </p>
                </li>
              ))}
            </ul>
          </div>
          <div>
            <h3 className="mb-2 text-sm font-semibold">Mistake patterns</h3>
            <ul className="space-y-2">
              {data.mistake_patterns.slice(0, 5).map((pattern) => (
                <li
                  key={pattern.category}
                  className="flex items-center justify-between rounded-xl border px-4 py-3 text-sm"
                >
                  <span className="font-semibold">{formatCategory(pattern.category)}</span>
                  <span className="text-muted-foreground">
                    {pattern.count} {pattern.count === 1 ? "mistake" : "mistakes"} ·{" "}
                    <span className="font-bold text-destructive">
                      −{formatMarks(pattern.total_marks_lost)}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}
    </section>
  );
}

export function HandwrittenProgress() {
  const papersQuery = useStudentHandwrittenPapers();
  const subjects = subjectOptionsFromPapers(papersQuery.data ?? []);

  return (
    <div className="mx-auto w-full max-w-[1440px] space-y-6">
      <LearningHero
        title="My Progress"
        description="How your handwritten answer scripts are scoring, subject by subject."
      />
      <HandwrittenLearningNav active="progress" />

      {papersQuery.error ? (
        <ErrorCard
          title="We couldn't load your subjects"
          message={papersQuery.error.message}
          onRetry={() => void papersQuery.mutate()}
        />
      ) : papersQuery.data === undefined ? (
        <SkeletonList rows={3} />
      ) : subjects.length === 0 ? (
        <EmptyState
          icon={<TrendingUp size={22} />}
          title="No progress to show yet"
          message="Submit a handwritten answer script and your scores and level will build up here."
        />
      ) : (
        <>
          <div className="grid items-start gap-4 lg:grid-cols-2">
            {subjects.map((subject) => (
              <SubjectProgressCard key={subject.id} subject={subject} />
            ))}
          </div>
          <WeakAreasPanel subjects={subjects} />
        </>
      )}
    </div>
  );
}
