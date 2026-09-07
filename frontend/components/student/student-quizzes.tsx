"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { StudentQuiz, listStudentQuizzes, startAttempt } from "@/lib/api";
import { variantLabel } from "@/lib/format";

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
  bestPct?: number | null;
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
        bestPct: v.best_pct,
      });
    }
  }
  return items;
}

export function StudentQuizzes() {
  const router = useRouter();
  const [quizzes, setQuizzes] = useState<StudentQuiz[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState<string | null>(null);

  useEffect(() => {
    listStudentQuizzes()
      .then(setQuizzes)
      .catch((e) => setError(e.message));
  }, []);

  async function start(variantId: string) {
    setStarting(variantId);
    setError(null);
    try {
      const { attempt_id } = await startAttempt(variantId);
      router.push(`/dashboard/student/attempt/${attempt_id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not start quiz");
      setStarting(null);
    }
  }

  const items = quizzes ? flatten(quizzes) : [];
  const toAttend = items.filter((i) => !i.attempted);
  const completed = items.filter((i) => i.attempted);
  const loaded = quizzes !== null;

  return (
    <div className="flex flex-col gap-6">
      {error && <p className="text-sm text-red-600">{error}</p>}

      {/* Quizzes to attend — the first thing a student should see */}
      <Card className="animate-rise">
        <CardHeader>
          <CardTitle>Quizzes to take</CardTitle>
          <CardDescription>
            {toAttend.length > 0
              ? `You have ${toAttend.length} quiz${
                  toAttend.length === 1 ? "" : "zes"
                } waiting — pick one to start.`
              : "Quizzes assigned to your course appear here."}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {!loaded ? (
            <p className="text-sm text-muted-foreground">Loading…</p>
          ) : items.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No quizzes available yet — check back once your teacher publishes one.
            </p>
          ) : toAttend.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              You&apos;re all caught up — no new quizzes to take right now.
            </p>
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
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => start(i.variantId)}
                    disabled={starting === i.variantId}
                    className="group relative w-full overflow-hidden rounded-lg bg-gradient-to-b from-[#219256] to-[#15603d] px-4 py-2.5 text-sm font-semibold text-white transition-all animate-cta-glow hover:-translate-y-0.5 active:translate-y-0 disabled:cursor-not-allowed disabled:opacity-70"
                  >
                    {/* glossy top highlight */}
                    <span className="pointer-events-none absolute inset-x-0 top-0 h-1/2 rounded-t-lg bg-white/20" />
                    {/* sweeping sheen */}
                    <span className="pointer-events-none absolute inset-y-0 left-0 w-1/3 animate-shine bg-gradient-to-r from-transparent via-white/40 to-transparent" />
                    <span className="relative z-10 flex items-center justify-center gap-1">
                      {starting === i.variantId ? "Starting…" : "Start quiz"}
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

      {/* Completed — retake to improve the score */}
      {completed.length > 0 && (
        <Card className="animate-rise" style={{ animationDelay: "60ms" }}>
          <CardHeader>
            <CardTitle>Completed quizzes</CardTitle>
            <CardDescription>Retake any quiz to improve your score.</CardDescription>
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
                    {i.bestPct != null ? ` · best ${i.bestPct}%` : ""}
                  </p>
                </div>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => start(i.variantId)}
                  disabled={starting === i.variantId}
                >
                  {starting === i.variantId ? "Starting…" : "Retake"}
                </Button>
              </div>
            ))}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
