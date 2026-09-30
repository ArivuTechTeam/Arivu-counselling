"use client";

import { useEffect, useMemo, useState } from "react";

import {
  Course,
  createEvaluationPaper,
  EvaluationPaper,
  listCourses,
  listEvaluationPapers,
} from "@/lib/api";


const field = "mt-1 h-11 w-full rounded-lg border border-input bg-background px-3 text-sm";

export function EvaluationPaperManager() {
  const [courses, setCourses] = useState<Course[]>([]);
  const [papers, setPapers] = useState<EvaluationPaper[]>([]);
  const [courseLevelId, setCourseLevelId] = useState("");
  const [subjectId, setSubjectId] = useState("");
  const [title, setTitle] = useState("");
  const [marks, setMarks] = useState(100);
  const [mcqMarks, setMcqMarks] = useState<number | "">("");
  const [questionPaper, setQuestionPaper] = useState<File | null>(null);
  const [suggestedAnswer, setSuggestedAnswer] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([listCourses(), listEvaluationPapers()])
      .then(([nextCourses, nextPapers]) => {
        setCourses(nextCourses);
        setPapers(nextPapers);
      })
      .catch((reason) => setError(reason instanceof Error ? reason.message : "Couldn't load evaluation papers."));
  }, []);

  const levels = useMemo(
    () => courses.flatMap((course) => (course.levels ?? []).map((level) => ({ ...level, course }))),
    [courses],
  );
  const level = levels.find((item) => item.id === courseLevelId);
  const subjects = (level?.course.subjects ?? []).filter(
    (subject) => subject.course_level_id === courseLevelId,
  );

  async function create() {
    if (!courseLevelId || !subjectId || !title.trim() || !questionPaper) {
      setError("Choose a course level, subject and question-paper file, and enter a title.");
      return;
    }
    if (mcqMarks !== "" && mcqMarks > marks) {
      setError("MCQ marks cannot exceed the paper's total marks.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const paper = await createEvaluationPaper({
        course_level_id: courseLevelId,
        subject_id: subjectId,
        title: title.trim(),
        total_marks: marks,
        mcq_marks: mcqMarks === "" ? null : mcqMarks,
        question_paper: questionPaper,
        suggested_answer: suggestedAnswer,
      });
      setPapers((current) => [paper, ...current]);
      setTitle("");
      setMcqMarks("");
      setQuestionPaper(null);
      setSuggestedAnswer(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Couldn't create the evaluation paper.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Handwritten evaluation</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Publish a standalone paper for enrolled students. Rubric generation and submitted-answer evaluation run in the background.
        </p>
      </div>
      {error ? <p role="alert" className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">{error}</p> : null}
      <section className="rounded-xl border bg-card p-5 shadow-sm">
        <h2 className="text-lg font-semibold">Create evaluation paper</h2>
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <label className="text-sm">Course level
            <select className={field} value={courseLevelId} onChange={(event) => { setCourseLevelId(event.target.value); setSubjectId(""); }}>
              <option value="">Choose…</option>
              {levels.map((item) => <option key={item.id} value={item.id}>{item.course.name} · {item.name}</option>)}
            </select>
          </label>
          <label className="text-sm">Subject
            <select className={field} value={subjectId} onChange={(event) => setSubjectId(event.target.value)}>
              <option value="">Choose…</option>
              {subjects.map((subject) => <option key={subject.id} value={subject.id}>{subject.name}</option>)}
            </select>
          </label>
          <label className="text-sm">Title
            <input className={field} value={title} maxLength={200} onChange={(event) => setTitle(event.target.value)} />
          </label>
          <label className="text-sm">Total marks
            <input className={field} type="number" min={0.5} step={0.5} value={marks} onChange={(event) => setMarks(Number(event.target.value))} />
          </label>
          <label className="text-sm">MCQ marks graded separately (optional)
            <input className={field} type="number" min={0} max={marks} step={0.5} value={mcqMarks} placeholder="None" onChange={(event) => setMcqMarks(event.target.value === "" ? "" : Number(event.target.value))} />
          </label>
          <label className="text-sm">Question paper (PDF, PNG or JPEG)
            <input className="mt-2 block w-full text-sm" type="file" accept="application/pdf,image/png,image/jpeg" onChange={(event) => setQuestionPaper(event.target.files?.[0] ?? null)} />
          </label>
          <label className="text-sm">Suggested answers (optional)
            <input className="mt-2 block w-full text-sm" type="file" accept="application/pdf,image/png,image/jpeg" onChange={(event) => setSuggestedAnswer(event.target.files?.[0] ?? null)} />
          </label>
        </div>
        <button type="button" disabled={busy} onClick={() => void create()} className="mt-5 h-11 rounded-lg bg-primary px-5 text-sm font-semibold text-primary-foreground disabled:opacity-50">
          {busy ? "Uploading…" : "Publish paper"}
        </button>
      </section>
      <section>
        <h2 className="mb-3 text-lg font-semibold">Published papers</h2>
        {papers.length === 0 ? <p className="text-sm text-muted-foreground">No evaluation papers yet.</p> : (
          <div className="space-y-2">
            {papers.map((paper) => <article key={paper.id} className="rounded-xl border bg-card p-4"><p className="font-medium">{paper.title}</p><p className="text-xs text-muted-foreground">{paper.total_marks} marks{paper.mcq_marks != null ? ` · ${paper.mcq_marks} MCQ marks excluded from descriptive grading` : ""} · Rubric {paper.rubric_status?.replaceAll("_", " ") ?? "not started"}</p></article>)}
          </div>
        )}
      </section>
    </div>
  );
}
