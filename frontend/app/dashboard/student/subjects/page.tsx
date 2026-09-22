"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { AttemptReadiness } from "@/components/student/attempt-readiness";
import { AttemptHistoryList } from "@/components/student/test-history";
import { ErrorCard } from "@/components/ui/error-card";
import { SkeletonCards, SkeletonList } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty-state";
import { BookOpen } from "@/components/ui/icons";
import { PracticeSubject, StudentQuiz, startAttempt } from "@/lib/api";
import { variantLabel } from "@/lib/format";
import {
  usePracticeSubjects,
  useStudentAttempts,
  useStudentQuizzes,
} from "@/lib/student-queries";
import { useSessionStorageState } from "@/lib/use-session-storage-state";

type TakeItem = {
  setId: string;
  subjectId: string;
  chapterId?: string | null;
  chapterName: string;
  title: string;
  variantId: string;
  variantType: string;
  questionCount: number;
  totalMarks?: number | null;
  timeLimit?: number | null;
  attempted: boolean;
  attemptCount: number;
  attemptLimit: number;
  attemptsRemaining: number;
  bestPct?: number | null;
};
type ChapterNode = { name: string; items: TakeItem[] };
type SubjectNode = { name: string; chapters: Record<string, ChapterNode> };
type Tree = Record<string, SubjectNode>;

const NO_CHAPTER = "General";

function buildTree(enrolledSubjects: PracticeSubject[], quizzes: StudentQuiz[]): Tree {
  const tree: Tree = {};
  for (const subject of enrolledSubjects) {
    tree[subject.id] = { name: subject.name, chapters: {} };
  }
  for (const q of quizzes) {
    const subjectId = q.subject_id || `name:${q.subject_name || "Other"}`;
    const subjectName = q.subject_name || "Other";
    const chapterId = q.chapter_id || `name:${q.chapter_name || NO_CHAPTER}`;
    const chapterName = q.chapter_name || NO_CHAPTER;
    for (const v of q.variants) {
      const item: TakeItem = {
        setId: q.id,
        subjectId,
        chapterId: q.chapter_id,
        chapterName,
        title: q.title,
        variantId: v.id,
        variantType: v.variant_type,
        questionCount: v.question_count,
        totalMarks: v.total_marks,
        timeLimit: v.time_limit_minutes,
        attempted: v.attempted,
        attemptCount: v.attempt_count,
        attemptLimit: v.attempt_limit,
        attemptsRemaining: v.attempts_remaining,
        bestPct: v.best_pct,
      };
      tree[subjectId] ??= { name: subjectName, chapters: {} };
      tree[subjectId].chapters[chapterId] ??= { name: chapterName, items: [] };
      tree[subjectId].chapters[chapterId].items.push(item);
    }
  }
  return tree;
}

export default function StudentSubjectsPage() {
  const router = useRouter();
  const { data: quizzes = null, error: loadError, mutate } = useStudentQuizzes();
  const {
    data: enrolledSubjects,
    error: subjectsError,
    mutate: mutateSubjects,
  } = usePracticeSubjects();
  const [actionError, setActionError] = useState<string | null>(null);
  const [starting, setStarting] = useState<string | null>(null);
  const [active, setActive] = useSessionStorageState<string | null>(
    "student-subjects-active-subject",
    null,
    (value): value is string | null => value === null || typeof value === "string",
  );
  const [activeTab, setActiveTab] = useSessionStorageState<"available" | "history">(
    "student-subjects-tab",
    "available",
    (value): value is "available" | "history" =>
      value === "available" || value === "history",
  );
  const [pending, setPending] = useState<TakeItem | null>(null);
  const {
    data: attempts,
    error: attemptsError,
    mutate: mutateAttempts,
  } = useStudentAttempts(active !== null && activeTab === "history");

  const tree = useMemo(
    () => (quizzes && enrolledSubjects ? buildTree(enrolledSubjects, quizzes) : {}),
    [enrolledSubjects, quizzes],
  );
  const subjects = Object.keys(tree).sort((a, b) =>
    tree[a].name.localeCompare(tree[b].name),
  );

  async function start() {
    if (!pending) return;
    setStarting(pending.variantId);
    setActionError(null);
    try {
      const { attempt_id } = await startAttempt(pending.variantId);
      router.push(`/dashboard/student/attempt/${attempt_id}`);
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Could not start quiz");
      setStarting(null);
    }
  }

  function takeCard(item: TakeItem, actionLabel: "Start quiz" | "Retake") {
    return (
      <div
        key={item.variantId}
        className="flex flex-col justify-between gap-3 rounded-xl border p-4"
      >
        <div>
          <span className="inline-block rounded-full bg-primary/10 px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-primary">
            {variantLabel(item.variantType)}
          </span>
          <p className="mt-2 font-semibold leading-snug text-foreground">
            {item.title}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            {item.questionCount} question{item.questionCount === 1 ? "" : "s"}
            {item.totalMarks ? ` · ${item.totalMarks} marks` : ""}
            {item.timeLimit ? ` · ${item.timeLimit} min` : ""}
            {item.attempted && item.bestPct != null ? ` · best ${item.bestPct}%` : ""}
            {` · ${item.attemptsRemaining} of ${item.attemptLimit} attempts left`}
          </p>
        </div>
        <button
          type="button"
          onClick={() => setPending(item)}
          disabled={starting === item.variantId || item.attemptsRemaining === 0}
          className="w-full rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground shadow-sm transition-colors hover:bg-primary/90 disabled:opacity-60"
        >
          {starting === item.variantId
            ? "Starting…"
            : item.attemptsRemaining === 0
              ? "Attempt limit reached"
              : actionLabel}
        </button>
      </div>
    );
  }

  const error = actionError
    ?? (loadError instanceof Error ? loadError.message : null)
    ?? (subjectsError instanceof Error ? subjectsError.message : null);
  if (error)
    return (
      <div className="flex flex-col gap-6">
        <PageHeader
          title="Take Quiz"
          description="Choose a subject, then start an available quiz."
        />
        <ErrorCard
          message={error}
          onRetry={loadError || subjectsError ? () => {
            void mutate();
            void mutateSubjects();
          } : undefined}
        />
      </div>
    );

  // ---- Chapter view for one subject ----
  if (active && tree[active]) {
    const subject = tree[active];
    const chapters = Object.entries(subject.chapters).sort(([, a], [, b]) =>
      a.name.localeCompare(b.name),
    );
    const subjectItems = chapters.flatMap(([, chapter]) => chapter.items);
    const unattempted = subjectItems.filter((item) => !item.attempted);
    const retakes = subjectItems.filter(
      (item) => item.attempted && item.attemptsRemaining > 0,
    );
    const subjectAttempts = (attempts ?? []).filter(
      (attempt) => attempt.subject_id === active,
    );
    const chapterNames = Object.fromEntries(
      chapters
        .filter(([chapterId]) => !chapterId.startsWith("name:"))
        .map(([chapterId, chapter]) => [chapterId, chapter.name]),
    );
    return (
      <div className="flex flex-col gap-6">
        <button
          onClick={() => {
            setActive(null);
            setActiveTab("available");
          }}
          className="w-fit text-sm font-medium text-muted-foreground hover:text-foreground"
        >
          ← All subjects
        </button>
        <PageHeader
          title={subject.name}
          description="Start a new quiz or review your previous results for this subject."
        />

        <div
          role="tablist"
          aria-label={`${subject.name} quizzes`}
          className="flex w-full gap-1 rounded-xl border bg-card p-1 sm:w-fit"
        >
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === "available"}
            onClick={() => setActiveTab("available")}
            className={`flex flex-1 items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-semibold transition-colors sm:flex-none ${
              activeTab === "available"
                ? "bg-primary text-primary-foreground shadow-sm"
                : "text-muted-foreground hover:bg-muted hover:text-foreground"
            }`}
          >
            Yet to Attempt
            <span className="rounded-full bg-current/10 px-1.5 py-0.5 text-[11px]">
              {unattempted.length}
            </span>
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === "history"}
            onClick={() => setActiveTab("history")}
            className={`flex flex-1 items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-semibold transition-colors sm:flex-none ${
              activeTab === "history"
                ? "bg-primary text-primary-foreground shadow-sm"
                : "text-muted-foreground hover:bg-muted hover:text-foreground"
            }`}
          >
            History
            <span className="rounded-full bg-current/10 px-1.5 py-0.5 text-[11px]">
              {attempts === undefined ? "…" : subjectAttempts.length}
            </span>
          </button>
        </div>

        {activeTab === "available" ? (
          subjectItems.length === 0 ? (
            <EmptyState
              title="No published quizzes yet"
              message={`Your ${subject.name} subject is ready. Quizzes will appear here after a teacher publishes them.`}
            />
          ) : unattempted.length === 0 ? (
            <EmptyState
              title="You're up to date"
              message="You have attempted every published quiz in this subject. Open History to review results or use an available retake."
            />
          ) : (
            chapters.map(([chapterId, chapter]) => {
              const items = chapter.items.filter((item) => !item.attempted);
              if (items.length === 0) return null;
              return (
                <Card key={chapterId} className="animate-rise">
                  <CardHeader>
                    <CardTitle>{chapter.name}</CardTitle>
                    <CardDescription>
                      {items.length} quiz{items.length === 1 ? "" : "zes"} not attempted.
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                    {items.map((item) => takeCard(item, "Start quiz"))}
                  </CardContent>
                </Card>
              );
            })
          )
        ) : (
          <div className="flex flex-col gap-6">
            {attemptsError ? (
              <ErrorCard
                message={attemptsError.message}
                onRetry={() => void mutateAttempts()}
              />
            ) : attempts === undefined ? (
              <SkeletonList />
            ) : (
              <AttemptHistoryList
                items={subjectAttempts}
                chapterNames={chapterNames}
              />
            )}

            {retakes.length > 0 && (
              <Card>
                <CardHeader>
                  <CardTitle>Available retakes</CardTitle>
                  <CardDescription>
                    Improve a previous result while attempts remain.
                  </CardDescription>
                </CardHeader>
                <CardContent className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  {retakes.map((item) => takeCard(item, "Retake"))}
                </CardContent>
              </Card>
            )}
          </div>
        )}
        <AttemptReadiness
          open={pending !== null}
          title={pending?.title ?? "Quiz"}
          questionCount={pending?.questionCount ?? 0}
          timeLimitMinutes={pending?.timeLimit}
          attemptNumber={pending ? pending.attemptCount + 1 : undefined}
          maxAttempts={pending?.attemptLimit}
          busy={starting !== null}
          onCancel={() => setPending(null)}
          onConfirm={() => void start()}
        />
      </div>
    );
  }

  // ---- Subject list ----
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Take Quiz"
        description="Choose a subject to see quizzes you can take and your past results."
      />

      {quizzes === null || enrolledSubjects === undefined ? (
        <SkeletonCards />
      ) : subjects.length === 0 ? (
        <EmptyState
          icon={<BookOpen />}
          title="No subjects assigned yet"
          message="Choose a course and level during signup, or ask your institution administrator to correct your enrollment."
          action={
            <button
              onClick={() => router.push("/dashboard/student/smart-quiz")}
              className="rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground shadow-sm transition-colors hover:bg-primary/90"
            >
              Try a Smart Quiz
            </button>
          }
        />
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {subjects.map((s) => {
            const subject = tree[s];
            const chapterCount = Object.keys(subject.chapters).length;
            const quizCount = Object.values(subject.chapters).reduce(
              (total, chapter) => total + chapter.items.length,
              0,
            );
            return (
              <button
                key={s}
                onClick={() => {
                  setActive(s);
                  setActiveTab("available");
                }}
                className="animate-rise flex flex-col items-start gap-1 rounded-2xl border bg-card p-5 text-left shadow-sm transition-all hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-md"
              >
                <span className="text-lg font-bold text-foreground">
                  {subject.name}
                </span>
                <span className="text-xs text-muted-foreground">
                  {chapterCount} chapter{chapterCount === 1 ? "" : "s"} · {quizCount}{" "}
                  quiz{quizCount === 1 ? "" : "zes"}
                </span>
                <span className="mt-2 text-xs font-medium text-primary">
                  Choose subject →
                </span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
