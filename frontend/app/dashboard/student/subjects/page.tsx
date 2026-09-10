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
import { ErrorCard } from "@/components/ui/error-card";
import { SkeletonCards } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty-state";
import { BookOpen } from "@/components/ui/icons";
import { StudentQuiz, startAttempt } from "@/lib/api";
import { variantLabel } from "@/lib/format";
import { useStudentQuizzes } from "@/lib/student-queries";

type TakeItem = {
  setId: string;
  title: string;
  variantId: string;
  variantType: string;
  questionCount: number;
  totalMarks?: number | null;
  attempted: boolean;
  bestPct?: number | null;
};
// subject -> chapter -> takeable quizzes
type Tree = Record<string, Record<string, TakeItem[]>>;

const NO_CHAPTER = "General";

function buildTree(quizzes: StudentQuiz[]): Tree {
  const tree: Tree = {};
  for (const q of quizzes) {
    const subject = q.subject_name || "Other";
    const chapter = q.chapter_name || NO_CHAPTER;
    for (const v of q.variants) {
      const item: TakeItem = {
        setId: q.id,
        title: q.title,
        variantId: v.id,
        variantType: v.variant_type,
        questionCount: v.question_count,
        totalMarks: v.total_marks,
        attempted: v.attempted,
        bestPct: v.best_pct,
      };
      tree[subject] ??= {};
      tree[subject][chapter] ??= [];
      tree[subject][chapter].push(item);
    }
  }
  return tree;
}

export default function StudentSubjectsPage() {
  const router = useRouter();
  const { data: quizzes = null, error: loadError, mutate } = useStudentQuizzes();
  const [actionError, setActionError] = useState<string | null>(null);
  const [starting, setStarting] = useState<string | null>(null);
  const [active, setActive] = useState<string | null>(null);

  const tree = useMemo(() => (quizzes ? buildTree(quizzes) : {}), [quizzes]);
  const subjects = Object.keys(tree).sort();

  async function start(variantId: string) {
    setStarting(variantId);
    setActionError(null);
    try {
      const { attempt_id } = await startAttempt(variantId);
      router.push(`/dashboard/student/attempt/${attempt_id}`);
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Could not start quiz");
      setStarting(null);
    }
  }

  const error = actionError ?? (loadError instanceof Error ? loadError.message : null);
  if (error)
    return (
      <div className="flex flex-col gap-6">
        <PageHeader
          title="Subjects"
          description="Browse your subjects and their chapters, then take a quiz."
        />
        <ErrorCard
          message={error}
          onRetry={loadError ? () => void mutate() : undefined}
        />
      </div>
    );

  // ---- Chapter view for one subject ----
  if (active && tree[active]) {
    const chapters = Object.entries(tree[active]).sort(([a], [b]) =>
      a.localeCompare(b),
    );
    return (
      <div className="flex flex-col gap-6">
        <button
          onClick={() => setActive(null)}
          className="w-fit text-sm font-medium text-muted-foreground hover:text-foreground"
        >
          ← Subjects
        </button>
        <PageHeader
          title={active}
          description="Pick a chapter and start a quiz."
        />
        {chapters.map(([chapter, items]) => (
          <Card key={chapter} className="animate-rise">
            <CardHeader>
              <CardTitle>{chapter}</CardTitle>
              <CardDescription>
                {items.length} quiz{items.length === 1 ? "" : "zes"} available.
              </CardDescription>
            </CardHeader>
            <CardContent className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              {items.map((i) => (
                <div
                  key={i.variantId}
                  className="flex flex-col justify-between gap-3 rounded-xl border p-4"
                >
                  <div>
                    <span className="inline-block rounded-full bg-primary/10 px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-primary">
                      {variantLabel(i.variantType)}
                    </span>
                    <p className="mt-2 font-semibold leading-snug text-foreground">
                      {i.title}
                    </p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {i.questionCount} question{i.questionCount === 1 ? "" : "s"}
                      {i.totalMarks ? ` · ${i.totalMarks} marks` : ""}
                      {i.attempted && i.bestPct != null ? ` · best ${i.bestPct}%` : ""}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => start(i.variantId)}
                    disabled={starting === i.variantId}
                    className="w-full rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground shadow-sm transition-colors hover:bg-primary/90 disabled:opacity-60"
                  >
                    {starting === i.variantId
                      ? "Starting…"
                      : i.attempted
                        ? "Retake"
                        : "Start quiz"}
                  </button>
                </div>
              ))}
            </CardContent>
          </Card>
        ))}
      </div>
    );
  }

  // ---- Subject list ----
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Subjects"
        description="Browse your subjects and their chapters, then take a quiz."
      />

      {quizzes === null ? (
        <SkeletonCards />
      ) : subjects.length === 0 ? (
        <EmptyState
          icon={<BookOpen />}
          title="No subjects yet"
          message="Quizzes will appear here once your teacher publishes one for your course. In the meantime, you can practise any time with a Smart Quiz."
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
            const chapterCount = Object.keys(tree[s]).length;
            const quizCount = Object.values(tree[s]).reduce(
              (a, items) => a + items.length,
              0,
            );
            return (
              <button
                key={s}
                onClick={() => setActive(s)}
                className="animate-rise flex flex-col items-start gap-1 rounded-2xl border bg-card p-5 text-left shadow-sm transition-all hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-md"
              >
                <span className="text-lg font-bold text-foreground">{s}</span>
                <span className="text-xs text-muted-foreground">
                  {chapterCount} chapter{chapterCount === 1 ? "" : "s"} · {quizCount}{" "}
                  quiz{quizCount === 1 ? "" : "zes"}
                </span>
                <span className="mt-2 text-xs font-medium text-primary">
                  Open →
                </span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
