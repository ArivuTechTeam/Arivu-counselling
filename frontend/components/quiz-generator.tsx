"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  Course,
  DocumentOut,
  GenerateResponse,
  GeneratedQuestion,
  generateQuiz,
  listCourses,
  listDocuments,
} from "@/lib/api";

const QUESTION_TYPES = [
  { value: "mcq_single", label: "MCQ (single)" },
  { value: "mcq_multi", label: "MCQ (multiple)" },
  { value: "true_false", label: "True / False" },
  { value: "numerical", label: "Numerical" },
  { value: "fill_blank", label: "Fill in the blank" },
];

const selectClass =
  "h-9 rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm";

export function QuizGenerator() {
  const [documents, setDocuments] = useState<DocumentOut[]>([]);
  const [documentId, setDocumentId] = useState("");
  const [courses, setCourses] = useState<Course[]>([]);
  const [subjectId, setSubjectId] = useState("");
  const [numQuestions, setNumQuestions] = useState(5);
  const [types, setTypes] = useState<string[]>(["mcq_single", "true_false"]);
  const [level, setLevel] = useState("theory");
  const [difficulty, setDifficulty] = useState("medium");

  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<GenerateResponse | null>(null);

  // Only completed documents can be turned into quizzes.
  useEffect(() => {
    listDocuments()
      .then((docs) => setDocuments(docs.filter((d) => d.status === "completed")))
      .catch((e) => setError(e.message));
    listCourses()
      .then(setCourses)
      .catch(() => {});
  }, []);

  function toggleType(value: string) {
    setTypes((prev) =>
      prev.includes(value)
        ? prev.filter((t) => t !== value)
        : [...prev, value],
    );
  }

  async function handleGenerate() {
    setError(null);
    setResult(null);
    if (!documentId) {
      setError("Pick a document first.");
      return;
    }
    if (types.length === 0) {
      setError("Select at least one question type.");
      return;
    }
    setGenerating(true);
    try {
      const res = await generateQuiz({
        document_id: documentId,
        num_questions: numQuestions,
        question_types: types,
        cognitive_level: level,
        difficulty,
        subject_id: subjectId || undefined,
      });
      setResult(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Generation failed");
    } finally {
      setGenerating(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader>
          <CardTitle>Generate a quiz</CardTitle>
          <CardDescription>
            Pick an uploaded document and options. The AI drafts questions for
            you to review.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <label className="flex flex-col gap-1 text-sm">
            Document
            <select
              className={selectClass}
              value={documentId}
              onChange={(e) => setDocumentId(e.target.value)}
            >
              <option value="">Select a document…</option>
              {documents.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.original_filename}
                </option>
              ))}
            </select>
          </label>

          <label className="flex flex-col gap-1 text-sm">
            Subject (which students see this)
            <select
              className={selectClass}
              value={subjectId}
              onChange={(e) => setSubjectId(e.target.value)}
            >
              <option value="">No subject — teachers only</option>
              {courses.map((c) => (
                <optgroup key={c.id} label={c.name}>
                  {c.subjects.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name}
                    </option>
                  ))}
                </optgroup>
              ))}
            </select>
          </label>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <label className="flex flex-col gap-1 text-sm">
              Questions
              <select
                className={selectClass}
                value={numQuestions}
                onChange={(e) => setNumQuestions(Number(e.target.value))}
              >
                {[3, 5, 10, 15, 20].map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-sm">
              Cognitive level
              <select
                className={selectClass}
                value={level}
                onChange={(e) => setLevel(e.target.value)}
              >
                <option value="theory">Theory</option>
                <option value="practical">Practical</option>
                <option value="mixed">Mixed</option>
              </select>
            </label>
            <label className="flex flex-col gap-1 text-sm">
              Difficulty
              <select
                className={selectClass}
                value={difficulty}
                onChange={(e) => setDifficulty(e.target.value)}
              >
                <option value="easy">Easy</option>
                <option value="medium">Medium</option>
                <option value="hard">Hard</option>
              </select>
            </label>
          </div>

          <fieldset className="flex flex-col gap-2 text-sm">
            <span className="text-muted-foreground">Question types</span>
            <div className="flex flex-wrap gap-3">
              {QUESTION_TYPES.map((t) => (
                <label key={t.value} className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={types.includes(t.value)}
                    onChange={() => toggleType(t.value)}
                  />
                  {t.label}
                </label>
              ))}
            </div>
          </fieldset>

          <div>
            <Button onClick={handleGenerate} disabled={generating}>
              {generating ? "Generating… (20–40s)" : "Generate quiz"}
            </Button>
          </div>
          {error && <p className="text-sm text-red-600">{error}</p>}
        </CardContent>
      </Card>

      {result && (
        <Card>
          <CardHeader>
            <CardTitle>
              {result.questions.length} questions generated
            </CardTitle>
            <CardDescription>
              Drafted by {result.provider} · pending review
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <Link
              href={`/dashboard/teacher/quiz-sets/${result.quiz_set_id}`}
              className="text-sm font-medium underline"
            >
              Review &amp; publish this set →
            </Link>
            {result.questions.map((q, i) => (
              <QuestionCard key={q.id ?? i} index={i} q={q} />
            ))}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function QuestionCard({ index, q }: { index: number; q: GeneratedQuestion }) {
  return (
    <div className="rounded-md border p-4 text-sm">
      <div className="mb-2 flex items-center justify-between">
        <span className="font-medium">Q{index + 1}</span>
        <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs uppercase text-gray-700">
          {q.type}
        </span>
      </div>
      <p className="mb-2">{q.question_text}</p>
      {q.options && (
        <ul className="mb-2 flex flex-col gap-1 text-muted-foreground">
          {q.options.map((o) => (
            <li key={o.id}>
              <span className="font-mono">{o.id}.</span> {o.text}
            </li>
          ))}
        </ul>
      )}
      <p className="text-green-700">Answer: {formatAnswer(q)}</p>
      {q.explanation && (
        <p className="mt-1 text-muted-foreground">Why: {q.explanation}</p>
      )}
    </div>
  );
}

function formatAnswer(q: GeneratedQuestion): string {
  const a = q.correct_answer;
  if (Array.isArray(a)) return a.join(", ");
  if (a && typeof a === "object") {
    const obj = a as Record<string, unknown>;
    if ("value" in obj) {
      const tol = obj.tolerance ? ` (±${obj.tolerance})` : "";
      return `${obj.value}${tol}`;
    }
    if ("answers" in obj) return (obj.answers as string[]).join(" / ");
    return JSON.stringify(obj);
  }
  return String(a);
}
