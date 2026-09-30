"use client";

import { useEffect, useMemo, useState } from "react";

import { useDashboardIdentity } from "@/components/shared/dashboard-identity-context";
import {
  Course,
  GeneratedPaper,
  getGeneratedPaper,
  listChapters,
  listCourses,
  listGeneratedPapers,
  startGeneratedPaper,
} from "@/lib/api";

const input = "h-11 w-full rounded-lg border border-input bg-background px-3 text-sm";
const questionTypes = ["mcq_single", "mcq_multi", "true_false", "numerical", "fill_blank", "descriptive"];

export function ExamPaperGenerator() {
  const { institution } = useDashboardIdentity();
  const [courses, setCourses] = useState<Course[]>([]);
  const [courseLevelId, setCourseLevelId] = useState("");
  const [subjectId, setSubjectId] = useState("");
  const [chapters, setChapters] = useState<{ id: string; name: string }[]>([]);
  const [chapterIds, setChapterIds] = useState<string[]>([]);
  const [types, setTypes] = useState<string[]>([]);
  const [mode, setMode] = useState<"exact_mark" | "candidate_ai">("exact_mark");
  const [marks, setMarks] = useState(100);
  const [count, setCount] = useState(20);
  const [history, setHistory] = useState<GeneratedPaper[]>([]);
  const [active, setActive] = useState<GeneratedPaper | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listCourses().then(setCourses).catch((reason) => setError(reason instanceof Error ? reason.message : "Couldn't load courses."));
  }, []);

  const levels = useMemo(
    () => courses.flatMap((course) => (course.levels ?? []).map((level) => ({ ...level, course }))),
    [courses],
  );
  const selectedLevel = levels.find((level) => level.id === courseLevelId);
  const subjects = (selectedLevel?.course.subjects ?? []).filter(
    (subject) => subject.course_level_id === courseLevelId,
  );

  useEffect(() => {
    if (!subjectId) {
      setChapters([]);
      return;
    }
    listChapters(subjectId).then(setChapters).catch(() => setChapters([]));
  }, [subjectId]);

  useEffect(() => {
    if (!courseLevelId) {
      setHistory([]);
      return;
    }
    listGeneratedPapers(courseLevelId).then(setHistory).catch(() => setHistory([]));
  }, [courseLevelId]);

  async function poll(id: string) {
    for (let attempt = 0; attempt < 150; attempt += 1) {
      const paper = await getGeneratedPaper(id);
      setActive(paper);
      setHistory((current) => [paper, ...current.filter((item) => item.id !== paper.id)]);
      if (paper.status === "ready" || paper.status === "failed") return paper;
      await new Promise((resolve) => window.setTimeout(resolve, 2000));
    }
    throw new Error("Paper generation is still running. It remains available in your history.");
  }

  async function generate() {
    if (!courseLevelId || !subjectId) {
      setError("Choose a course level and subject.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const queued = await startGeneratedPaper({
        request_key: crypto.randomUUID(),
        course_level_id: courseLevelId,
        subject_id: subjectId,
        mode,
        requested_total_marks: marks,
        question_count: count,
        chapter_ids: chapterIds,
        question_types: types,
      });
      await poll(queued.generated_paper_id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Couldn't generate the paper.");
    } finally {
      setBusy(false);
    }
  }

  async function download(paper: GeneratedPaper, withAnswers: boolean) {
    if (!paper.paper_payload) return;
    const [{ downloadPdf, slug }, { GeneratedExamPaperDoc }] = await Promise.all([
      import("@/lib/pdf/download"),
      import("@/lib/pdf/documents"),
    ]);
    const title = paper.paper_payload.paper || "exam-paper";
    await downloadPdf(
      <GeneratedExamPaperDoc payload={paper.paper_payload} branding={institution} withAnswers={withAnswers} />,
      `${slug(title)}${withAnswers ? "-answer-key" : ""}`,
    );
  }

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Generate exam paper</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Build a tenant-scoped paper from approved PYQ, MTP and RTP questions. Exact mode guarantees the requested mark total before formatting.
        </p>
      </div>
      {error ? <p role="alert" className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">{error}</p> : null}
      <div className="rounded-xl border bg-card p-5 shadow-sm">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <label className="text-xs text-muted-foreground">Course level
            <select className={input} value={courseLevelId} onChange={(event) => { setCourseLevelId(event.target.value); setSubjectId(""); setChapterIds([]); }}>
              <option value="">Choose…</option>
              {levels.map((level) => <option key={level.id} value={level.id}>{level.course.name} · {level.name}</option>)}
            </select>
          </label>
          <label className="text-xs text-muted-foreground">Subject
            <select className={input} value={subjectId} onChange={(event) => { setSubjectId(event.target.value); setChapterIds([]); }}>
              <option value="">Choose…</option>
              {subjects.map((subject) => <option key={subject.id} value={subject.id}>{subject.name}</option>)}
            </select>
          </label>
          <label className="text-xs text-muted-foreground">Total marks
            <input className={input} type="number" min={0.5} max={1000} step={0.5} value={marks} onChange={(event) => setMarks(Number(event.target.value))} />
          </label>
          <label className="text-xs text-muted-foreground">Preferred question count
            <input className={input} type="number" min={1} max={50} value={count} onChange={(event) => setCount(Number(event.target.value))} />
          </label>
        </div>
        <fieldset className="mt-4">
          <legend className="text-xs font-medium text-muted-foreground">Selection mode</legend>
          <div className="mt-2 flex flex-wrap gap-4 text-sm">
            <label><input type="radio" checked={mode === "exact_mark"} onChange={() => setMode("exact_mark")} /> Deterministic exact marks</label>
            <label><input type="radio" checked={mode === "candidate_ai"} onChange={() => setMode("candidate_ai")} /> AI-assisted selection</label>
          </div>
        </fieldset>
        {chapters.length ? <fieldset className="mt-4"><legend className="text-xs font-medium text-muted-foreground">Chapters (optional)</legend><div className="mt-2 flex flex-wrap gap-3">{chapters.map((chapter) => <label key={chapter.id} className="text-sm"><input type="checkbox" checked={chapterIds.includes(chapter.id)} onChange={() => setChapterIds((current) => current.includes(chapter.id) ? current.filter((id) => id !== chapter.id) : [...current, chapter.id])} /> {chapter.name}</label>)}</div></fieldset> : null}
        <fieldset className="mt-4"><legend className="text-xs font-medium text-muted-foreground">Question types (optional)</legend><div className="mt-2 flex flex-wrap gap-3">{questionTypes.map((type) => <label key={type} className="text-sm"><input type="checkbox" checked={types.includes(type)} onChange={() => setTypes((current) => current.includes(type) ? current.filter((item) => item !== type) : [...current, type])} /> {type.replaceAll("_", " ")}</label>)}</div></fieldset>
        <button type="button" disabled={busy} onClick={() => void generate()} className="mt-5 h-11 rounded-lg bg-primary px-5 text-sm font-semibold text-primary-foreground disabled:opacity-50">{busy ? "Generating…" : "Generate paper"}</button>
      </div>
      {active ? <PaperResult paper={active} onDownload={download} /> : null}
      <div>
        <h2 className="mb-3 text-lg font-semibold">History</h2>
        {!courseLevelId ? <p className="text-sm text-muted-foreground">Choose a course level to see its history.</p> : history.length === 0 ? <p className="text-sm text-muted-foreground">No generated papers yet.</p> : <div className="space-y-2">{history.map((paper) => <PaperResult key={paper.id} paper={paper} onDownload={download} compact />)}</div>}
      </div>
    </div>
  );
}

function PaperResult({ paper, onDownload, compact = false }: { paper: GeneratedPaper; onDownload: (paper: GeneratedPaper, answers: boolean) => Promise<void>; compact?: boolean }) {
  return <div className="rounded-xl border bg-card p-4 shadow-sm">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div><p className="font-medium">{paper.requested_total_marks} marks · {paper.mode === "exact_mark" ? "Exact selection" : "AI-assisted"}</p><p className="text-xs text-muted-foreground">{new Date(paper.created_at).toLocaleString()} · {paper.status}</p></div>
      {paper.status === "ready" && paper.paper_payload ? <div className="flex gap-2"><button className="rounded-md border px-3 py-1.5 text-xs" onClick={() => void onDownload(paper, false)}>Question paper</button><button className="rounded-md border px-3 py-1.5 text-xs" onClick={() => void onDownload(paper, true)}>Answer key</button></div> : null}
    </div>
    {!compact && paper.status === "processing" ? <p className="mt-2 text-sm text-muted-foreground">The worker is selecting and formatting questions…</p> : null}
    {paper.status === "failed" ? <p className="mt-2 text-sm text-destructive">{paper.error_message || "Generation failed. Adjust the filters or mark total and try again."}</p> : null}
  </div>;
}
