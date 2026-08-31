"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import { StudentQuiz, createChallenge, listStudentQuizzes } from "@/lib/api";

const COUNTS = [5, 10, 15];
const fieldClass =
  "h-10 w-full rounded-md border border-input bg-background px-3 text-sm shadow-sm focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20";

export default function ChallengePage() {
  const router = useRouter();
  const [quizzes, setQuizzes] = useState<StudentQuiz[] | null>(null);
  const [subjectId, setSubjectId] = useState("");
  const [count, setCount] = useState(10);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [subjectsError, setSubjectsError] = useState(false);

  useEffect(() => {
    listStudentQuizzes()
      .then(setQuizzes)
      .catch(() => {
        setSubjectsError(true);
        setQuizzes([]);
      });
  }, []);

  const subjects = useMemo(() => {
    const map = new Map<string, string>();
    for (const q of quizzes ?? []) {
      if (q.subject_id && q.subject_name) map.set(q.subject_id, q.subject_name);
    }
    return Array.from(map, ([id, name]) => ({ id, name }));
  }, [quizzes]);

  async function create() {
    setBusy(true);
    setError(null);
    try {
      const { session_id } = await createChallenge({
        subject_id: subjectId || null,
        count,
      });
      router.push(`/dashboard/student/practice/${session_id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not start the challenge.");
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Challenge a Friend"
        description="Pick a quiz, play it, then share the link. Whoever from your class scores highest tops the leaderboard."
      />

      {/* Hero */}
      <div className="animate-rise relative overflow-hidden rounded-2xl bg-gradient-to-br from-[#1a6942] via-[#15603d] to-[#0f4e33] p-6 text-white shadow-lg sm:p-8">
        <div className="pointer-events-none absolute -right-10 -top-12 h-44 w-44 rounded-full bg-white/10 blur-2xl" />
        <p className="text-[11px] font-semibold uppercase tracking-widest text-white/70">
          How it works
        </p>
        <div className="relative mt-3 grid gap-3 sm:grid-cols-3">
          {[
            ["1", "Build & play", "Create a random quiz and take it yourself first."],
            ["2", "Share the link", "Send it to classmates on WhatsApp."],
            ["3", "Top the board", "Everyone takes the same questions — highest score wins."],
          ].map(([n, t, d]) => (
            <div key={n} className="rounded-xl bg-white/10 p-4">
              <div className="flex h-7 w-7 items-center justify-center rounded-full bg-white/20 text-sm font-bold">
                {n}
              </div>
              <p className="mt-2 text-sm font-semibold">{t}</p>
              <p className="mt-1 text-xs text-white/70">{d}</p>
            </div>
          ))}
        </div>
      </div>

      {/* Build form */}
      <Card className="animate-rise">
        <CardHeader>
          <CardTitle>Create your challenge</CardTitle>
          <CardDescription>
            Random questions from your teacher-approved bank — same for everyone
            who plays.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <label className="flex flex-col gap-1.5 text-sm font-medium">
              Subject
              {quizzes === null ? (
                <Skeleton className="h-10 w-full rounded-md" />
              ) : (
                <select
                  className={fieldClass}
                  value={subjectId}
                  onChange={(e) => setSubjectId(e.target.value)}
                  disabled={subjectsError}
                >
                  <option value="">All my subjects</option>
                  {subjects.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name}
                    </option>
                  ))}
                </select>
              )}
              {subjectsError && (
                <span className="text-xs font-normal text-destructive">
                  Couldn&apos;t load subjects — you can still play across all of
                  them.
                </span>
              )}
            </label>
            <label className="flex flex-col gap-1.5 text-sm font-medium">
              Questions
              <select
                className={fieldClass}
                value={count}
                onChange={(e) => setCount(Number(e.target.value))}
              >
                {COUNTS.map((n) => (
                  <option key={n} value={n}>
                    {n} questions
                  </option>
                ))}
              </select>
            </label>
          </div>

          {error && (
            <p className="rounded-lg border border-destructive/20 bg-destructive/5 px-3 py-2 text-sm text-destructive">
              {error}
            </p>
          )}

          <div>
            <button
              onClick={create}
              disabled={busy}
              className="rounded-lg bg-gradient-to-b from-[#219256] to-[#15603d] px-6 py-2.5 text-sm font-semibold text-white shadow-sm transition-transform hover:-translate-y-0.5 disabled:opacity-60"
            >
              {busy ? "Setting up…" : "Create & play →"}
            </button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
