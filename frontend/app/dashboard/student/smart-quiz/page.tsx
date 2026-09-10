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
import { ErrorCard } from "@/components/ui/error-card";
import { StudentQuiz, listStudentQuizzes, startPracticeSession } from "@/lib/api";

const COUNTS = [10, 15, 20, 30];
const DIFFICULTIES = [
  { value: "", label: "Any" },
  { value: "easy", label: "Easy" },
  { value: "medium", label: "Medium" },
  { value: "hard", label: "Hard" },
];

const fieldClass =
  "h-10 w-full rounded-md border border-input bg-background px-3 text-sm shadow-sm focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20";

export default function SmartQuizPage() {
  const router = useRouter();
  const [quizzes, setQuizzes] = useState<StudentQuiz[] | null>(null);
  const [subjectId, setSubjectId] = useState("");
  const [count, setCount] = useState(15);
  const [difficulty, setDifficulty] = useState("");
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function loadSubjects() {
    setError(null);
    setQuizzes(null);
    listStudentQuizzes()
      .then(setQuizzes)
      .catch((e) => setError(e.message));
  }

  useEffect(loadSubjects, []);

  // Unique subjects the student has content in.
  const subjects = useMemo(() => {
    const map = new Map<string, string>();
    for (const q of quizzes ?? []) {
      if (q.subject_id && q.subject_name) map.set(q.subject_id, q.subject_name);
    }
    return Array.from(map, ([id, name]) => ({ id, name }));
  }, [quizzes]);

  const loadingSubjects = quizzes === null;

  async function start() {
    setStarting(true);
    setError(null);
    try {
      const { session_id } = await startPracticeSession({
        mode: "smart",
        subject_id: subjectId || null,
        count,
        difficulty: difficulty || null,
      });
      router.push(`/dashboard/student/practice/${session_id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not start the quiz.");
      setStarting(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Smart Quiz"
        description="A fresh, random quiz from your syllabus — practise any time, no waiting for a teacher."
      />

      <Card className="animate-rise">
        <CardHeader>
          <CardTitle>Build your quiz</CardTitle>
          <CardDescription>
            Questions are picked at random from your teacher-approved question
            bank.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <label className="flex flex-col gap-1.5 text-sm font-medium">
              Subject
              <select
                className={fieldClass}
                value={subjectId}
                onChange={(e) => setSubjectId(e.target.value)}
                disabled={loadingSubjects}
              >
                <option value="">
                  {loadingSubjects ? "Loading subjects…" : "All my subjects"}
                </option>
                {subjects.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
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
            <label className="flex flex-col gap-1.5 text-sm font-medium">
              Difficulty
              <select
                className={fieldClass}
                value={difficulty}
                onChange={(e) => setDifficulty(e.target.value)}
              >
                {DIFFICULTIES.map((d) => (
                  <option key={d.value} value={d.value}>
                    {d.label}
                  </option>
                ))}
              </select>
            </label>
          </div>

          {error && (
            <ErrorCard
              message={error}
              onRetry={quizzes === null ? loadSubjects : undefined}
              className="text-left"
            />
          )}

          <div>
            <button
              onClick={start}
              disabled={starting}
              className="rounded-lg bg-primary px-6 py-2.5 text-sm font-semibold text-primary-foreground shadow-sm transition-colors hover:bg-primary/90 disabled:opacity-60"
            >
              {starting ? "Starting…" : "Start Smart Quiz →"}
            </button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
