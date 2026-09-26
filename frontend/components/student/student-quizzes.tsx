"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { AttemptReadiness } from "@/components/student/attempt-readiness";
import { ErrorCard } from "@/components/ui/error-card";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { StudentQuiz, startAttempt } from "@/lib/api";
import { variantLabel } from "@/lib/format";
import { useStudentQuizzes } from "@/lib/student-queries";

// One takeable quiz = a variant plus the title of the set it belongs to.
type QuizItem = {
  setId: string;
  title: string;
  subjectName?: string | null;
  chapterName?: string | null;
  variantId: string;
  variantType: string;
  questionCount: number;
  totalMarks?: number | null;
  timeLimit?: number | null;
  attempted: boolean;
  attemptCount: number;
  attemptLimit: number;
  attemptsRemaining: number;
};

/** "Accounting · Depreciation" (subject · chapter), skipping any that are missing. */
function topicLine(i: QuizItem): string {
  return [i.subjectName, i.chapterName].filter(Boolean).join(" · ");
}

function flatten(quizzes: StudentQuiz[]): QuizItem[] {
  const items: QuizItem[] = [];
  for (const q of quizzes) {
    for (const v of q.variants) {
      items.push({
        setId: q.id,
        title: q.title,
        subjectName: q.subject_name,
        chapterName: q.chapter_name,
        variantId: v.id,
        variantType: v.variant_type,
        questionCount: v.question_count,
        totalMarks: v.total_marks,
        timeLimit: v.time_limit_minutes,
        attempted: v.attempted,
        attemptCount: v.attempt_count,
        attemptLimit: v.attempt_limit,
        attemptsRemaining: v.attempts_remaining,
      });
    }
  }
  return items;
}

export function StudentQuizzes() {
  const router = useRouter();
  const {
    data: quizzes = null,
    error: loadError,
    mutate,
    hasMore,
    loadMore,
    isLoadingMore,
  } = useStudentQuizzes();
  const [actionError, setActionError] = useState<string | null>(null);
  const [starting, setStarting] = useState<string | null>(null);
  const [pending, setPending] = useState<QuizItem | null>(null);

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

  const items = quizzes ? flatten(quizzes) : [];
  const toAttend = items.filter((i) => !i.attempted);
  const completed = items.filter((i) => i.attempted);
  const loaded = quizzes !== null;

  if (loadError) {
    return (
      <ErrorCard
        message={loadError.message}
        onRetry={() => void mutate()}
      />
    );
  }

  return (
    <div className="flex flex-col gap-6">
      {actionError && <p className="text-sm text-red-600">{actionError}</p>}

      {/* Quizzes to attend — the first thing a student should see */}
      <Card className="animate-rise">
        <CardHeader>
          <CardTitle>Quizzes to take</CardTitle>
          <CardDescription>
            {toAttend.length > 0
              ? `You have ${toAttend.length} loaded quiz${
                  toAttend.length === 1 ? "" : "zes"
                } waiting — pick one to start.`
              : "Quizzes assigned to your course appear here."}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {!loaded ? (
            <p className="text-sm text-muted-foreground">Loading…</p>
          ) : items.length === 0 ? (
            <div className="rounded-xl border border-dashed p-5">
              <p className="font-medium text-foreground">No teacher-published quizzes yet</p>
              <p className="mt-1 text-sm text-muted-foreground">
                You can still build a quiz from your subjects or practise by subject now.
              </p>
              <div className="mt-4 flex flex-wrap gap-2">
                <Button asChild size="sm">
                  <Link href="/dashboard/student/practice?mode=topic">Start Topic Practice</Link>
                </Button>
                <Button asChild size="sm" variant="outline">
                  <Link href="/dashboard/student/subjects">Practice by subject</Link>
                </Button>
              </div>
            </div>
          ) : toAttend.length === 0 ? (
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-dashed p-4">
              <p className="text-sm text-muted-foreground">
                No new quizzes right now. You can retake a previous quiz or practise a topic.
              </p>
              <Button asChild size="sm" variant="outline">
                <Link href="/dashboard/student/practice?mode=topic">Start Topic Practice</Link>
              </Button>
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              {toAttend.map((i) => (
                <div
                  key={i.variantId}
                  className="flex flex-col justify-between gap-3 rounded-xl border border-primary/20 bg-primary/[0.03] p-4 transition-shadow hover:shadow-md"
                >
                  <div>
                    <span className="inline-block rounded-full bg-primary/10 px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-primary">
                      {variantLabel(i.variantType)}
                    </span>
                    <p className="mt-2 font-semibold leading-snug text-foreground">
                      {i.title}
                    </p>
                    {topicLine(i) && (
                      <p className="mt-0.5 text-xs font-medium text-primary/80">
                        {topicLine(i)}
                      </p>
                    )}
                    <p className="mt-1 text-xs text-muted-foreground">
                      {i.questionCount} question{i.questionCount === 1 ? "" : "s"}
                      {i.totalMarks ? ` · ${i.totalMarks} marks` : ""}
                      {i.timeLimit ? ` · ${i.timeLimit} min` : ""}
                      {` · ${i.attemptsRemaining} of ${i.attemptLimit} attempts left`}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => setPending(i)}
                    disabled={starting === i.variantId || i.attemptsRemaining === 0}
                    className="group relative w-full overflow-hidden rounded-lg bg-primary px-4 py-2.5 text-sm font-semibold text-primary-foreground transition-all animate-cta-glow hover:-translate-y-0.5 hover:bg-primary/90 active:translate-y-0 disabled:cursor-not-allowed disabled:opacity-70"
                  >
                    {/* glossy top highlight */}
                    <span className="pointer-events-none absolute inset-x-0 top-0 h-1/2 rounded-t-lg bg-white/20" />
                    <span className="relative z-10 flex items-center justify-center gap-1">
                      {starting === i.variantId
                        ? "Starting…"
                        : i.attemptsRemaining === 0
                          ? "Attempt limit reached"
                          : "Start quiz"}
                      {starting !== i.variantId && (
                        <span className="transition-transform group-hover:translate-x-1">
                          →
                        </span>
                      )}
                    </span>
                  </button>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Previously opened — some attempts may have ended without an answer */}
      {completed.length > 0 && (
        <Card className="animate-rise" style={{ animationDelay: "60ms" }}>
          <CardHeader>
            <CardTitle>Quizzes you&apos;ve opened</CardTitle>
            <CardDescription>Try one again to finish it or improve your score.</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            {completed.map((i) => (
              <div
                key={i.variantId}
                className="flex items-center justify-between gap-3 rounded-lg border p-3"
              >
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-foreground">
                    {i.title}
                  </p>
                  <p className="truncate text-xs text-muted-foreground">
                    {topicLine(i) ? `${topicLine(i)} · ` : ""}
                    {variantLabel(i.variantType)}
                    {` · ${i.attemptsRemaining} attempt${i.attemptsRemaining === 1 ? "" : "s"} left`}
                  </p>
                </div>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => setPending(i)}
                  disabled={starting === i.variantId || i.attemptsRemaining === 0}
                >
                  {starting === i.variantId
                    ? "Starting…"
                    : i.attemptsRemaining === 0
                      ? "Limit reached"
                      : "Try again"}
                </Button>
              </div>
            ))}
          </CardContent>
        </Card>
      )}
      {loaded && hasMore && (
        <Button variant="outline" onClick={() => void loadMore()} disabled={isLoadingMore}>
          {isLoadingMore ? "Loading…" : "Load more quizzes"}
        </Button>
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
