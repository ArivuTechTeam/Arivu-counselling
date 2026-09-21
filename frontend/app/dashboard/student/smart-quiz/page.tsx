"use client";

import { useState } from "react";
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
import { ErrorCard } from "@/components/ui/error-card";
import { previewPracticeSession, startPracticeSession } from "@/lib/api";
import { usePracticeSubjects } from "@/lib/student-queries";
import { useSessionStorageState } from "@/lib/use-session-storage-state";

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
  const { data: subjects, error: subjectsError, mutate } = usePracticeSubjects();
  const [subjectId, setSubjectId] = useSessionStorageState(
    "student-smart-quiz-subject",
    "",
    (value): value is string => typeof value === "string",
  );
  const [count, setCount] = useSessionStorageState(
    "student-smart-quiz-count",
    15,
    (value): value is number => typeof value === "number" && COUNTS.includes(value),
  );
  const [difficulty, setDifficulty] = useSessionStorageState(
    "student-smart-quiz-difficulty",
    "",
    (value): value is string =>
      typeof value === "string" && DIFFICULTIES.some((item) => item.value === value),
  );
  const [starting, setStarting] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [availableCount, setAvailableCount] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showReadiness, setShowReadiness] = useState(false);

  const loadingSubjects = subjects === undefined;

  const input = {
    mode: "smart",
    subject_id: subjectId || null,
    count,
    difficulty: difficulty || null,
  };

  async function prepare() {
    setPreviewing(true);
    setError(null);
    try {
      const preview = await previewPracticeSession(input);
      setAvailableCount(preview.question_count);
      setShowReadiness(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not prepare the quiz.");
    } finally {
      setPreviewing(false);
    }
  }

  async function start() {
    setStarting(true);
    setError(null);
    try {
      const { session_id } = await startPracticeSession(input);
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
                {(subjects ?? []).map((s) => (
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
              onRetry={subjectsError ? () => void mutate() : undefined}
              className="text-left"
            />
          )}

          {subjectsError && !error && (
            <ErrorCard
              message={subjectsError.message}
              onRetry={() => void mutate()}
              className="text-left"
            />
          )}

          <div>
            <button
              onClick={() => void prepare()}
              disabled={starting || previewing || loadingSubjects || !!subjectsError}
              className="rounded-lg bg-primary px-6 py-2.5 text-sm font-semibold text-primary-foreground shadow-sm transition-colors hover:bg-primary/90 disabled:opacity-60"
            >
              {previewing ? "Checking questions…" : "Start Smart Quiz →"}
            </button>
          </div>
        </CardContent>
      </Card>
      <AttemptReadiness
        open={showReadiness}
        title="Smart Quiz"
        questionCount={availableCount ?? count}
        requestedQuestionCount={count}
        busy={starting}
        onCancel={() => {
          setShowReadiness(false);
          setAvailableCount(null);
        }}
        onConfirm={() => void start()}
      />
    </div>
  );
}
