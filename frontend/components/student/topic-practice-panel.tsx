"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import useSWR from "swr";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { AttemptReadiness } from "@/components/student/attempt-readiness";
import { ErrorCard } from "@/components/ui/error-card";
import { ApiRequestError, listPracticeChapters, previewPracticeSession, startPracticeSession, type StartPracticeInput } from "@/lib/api";
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

export function TopicPracticePanel() {
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
  const [chapterId, setChapterId] = useSessionStorageState(
    "student-topic-practice-chapter",
    "",
    (value): value is string => typeof value === "string",
  );
  const selectedSubjectId = subjects?.some((subject) => subject.id === subjectId)
    ? subjectId
    : "";
  const { data: chapters, error: chaptersError } = useSWR(
    selectedSubjectId ? ["student-practice-chapters", selectedSubjectId] : null,
    () => listPracticeChapters(selectedSubjectId),
  );
  const selectedChapterId = chapters?.some((chapter) => chapter.id === chapterId)
    ? chapterId
    : "";
  const [difficulty, setDifficulty] = useSessionStorageState(
    "student-smart-quiz-difficulty",
    "",
    (value): value is string =>
      typeof value === "string" && DIFFICULTIES.some((item) => item.value === value),
  );
  const [starting, setStarting] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [availableCount, setAvailableCount] = useState<number | null>(null);
  const [preparedInput, setPreparedInput] = useState<StartPracticeInput | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [errorReason, setErrorReason] = useState<string | null>(null);
  const [showReadiness, setShowReadiness] = useState(false);

  const loadingSubjects = subjects === undefined;

  const input = {
    mode: "smart",
    subject_id: selectedChapterId ? null : selectedSubjectId || null,
    chapter_id: selectedChapterId || null,
    count,
    difficulty: difficulty || null,
  };

  async function prepare() {
    const selection = { ...input };
    setPreviewing(true);
    setPreparedInput(null);
    setError(null);
    setErrorReason(null);
    try {
      const preview = await previewPracticeSession(selection);
      setAvailableCount(preview.question_count);
      setPreparedInput(selection);
      setShowReadiness(true);
    } catch (e) {
      setPreparedInput(null);
      setErrorReason(e instanceof ApiRequestError ? e.reason : null);
      setError(e instanceof Error ? e.message : "Could not prepare the quiz.");
    } finally {
      setPreviewing(false);
    }
  }

  async function start() {
    if (!preparedInput) return;
    setStarting(true);
    setError(null);
    setErrorReason(null);
    try {
      const { session_id } = await startPracticeSession(preparedInput);
      router.push(`/dashboard/student/practice/${session_id}`);
    } catch (e) {
      setErrorReason(e instanceof ApiRequestError ? e.reason : null);
      setError(e instanceof Error ? e.message : "Could not start the quiz.");
      setStarting(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <Card className="animate-rise">
        <CardHeader>
          <CardTitle>Build your topic practice</CardTitle>
          <CardDescription>
            Questions are picked at random from your teacher-approved question
            bank.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <fieldset
            disabled={previewing || showReadiness || starting}
            className="grid grid-cols-1 gap-4 disabled:opacity-70 sm:grid-cols-2 lg:grid-cols-4"
          >
            <label className="flex flex-col gap-1.5 text-sm font-medium">
              Subject
              <select
                className={fieldClass}
                value={selectedSubjectId}
                onChange={(e) => {
                  setSubjectId(e.target.value);
                  setChapterId("");
                }}
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
              Chapter (optional)
              <select
                className={fieldClass}
                value={selectedChapterId}
                onChange={(e) => setChapterId(e.target.value)}
                disabled={!selectedSubjectId || !chapters || !!chaptersError}
              >
                <option value="">
                  {!selectedSubjectId ? "Choose a subject first" : "All chapters"}
                </option>
                {(chapters ?? []).map((chapter) => (
                  <option key={chapter.id} value={chapter.id}>{chapter.name}</option>
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
          </fieldset>

          {error && (
            <ErrorCard
              title={errorReason === "no_questions_available" ? "No questions match your selection" : "Practice couldn't be prepared"}
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

          {chaptersError && (
            <ErrorCard message="Chapters could not be loaded. Choose another subject or try again." />
          )}

          <div>
            <button
              onClick={() => void prepare()}
              disabled={starting || previewing || loadingSubjects || !!subjectsError || !!chaptersError || (!!selectedSubjectId && !chapters)}
              className="rounded-lg bg-primary px-6 py-2.5 text-sm font-semibold text-primary-foreground shadow-sm transition-colors hover:bg-primary/90 disabled:opacity-60"
            >
              {previewing ? "Checking questions…" : "Review practice →"}
            </button>
          </div>
        </CardContent>
      </Card>
      <AttemptReadiness
        open={showReadiness}
        title="Topic Practice"
        questionCount={availableCount ?? preparedInput?.count ?? count}
        requestedQuestionCount={preparedInput?.count ?? count}
        busy={starting}
        onCancel={() => {
          setShowReadiness(false);
          setAvailableCount(null);
          setPreparedInput(null);
        }}
        onConfirm={() => void start()}
      />
    </div>
  );
}
