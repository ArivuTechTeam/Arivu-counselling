"use client";

import { useEffect, useMemo, useRef, useState, type RefObject } from "react";

import { Dialog } from "@/components/ui/dialog";
import {
  AlertTriangle,
  BookOpen,
  Check,
  ChevronDown,
  FileText,
  Inbox,
  Pencil,
  Plus,
  RefreshCw,
  Trash,
  X,
} from "@/components/ui/icons";
import {
  Course,
  createEvaluationPaper,
  deleteEvaluationPaper,
  EvaluationPaper,
  getEvaluationPaper,
  listCourses,
  listEvaluationPapers,
  updateEvaluationPaper,
} from "@/lib/api";

import { EvaluationPaperExtractedDialog } from "./evaluation-paper-extracted-dialog";

const field = "mt-1.5 h-11 w-full rounded-xl border border-input bg-background px-3 text-sm outline-none transition focus:border-primary focus:ring-2 focus:ring-primary/15";

function replacePaper(papers: EvaluationPaper[], next: EvaluationPaper) {
  return papers.map((paper) => paper.id === next.id ? { ...paper, ...next } : paper);
}

function statusLabel(status?: EvaluationPaper["rubric_status"]) {
  if (status === "ready") return "Rubric ready";
  if (status === "failed") return "Rubric failed";
  if (status === "extracting") return "Extracting files";
  if (status === "generating") return "Generating rubric";
  return "Rubric queued";
}

function monthLabel(value?: string) {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleDateString(undefined, { month: "short", year: "numeric" });
}

function FilePicker({
  id,
  label,
  hint,
  required,
  file,
  inputRef,
  onChange,
}: {
  id: string;
  label: string;
  hint: string;
  required?: boolean;
  file: File | null;
  inputRef: RefObject<HTMLInputElement | null>;
  onChange: (file: File | null) => void;
}) {
  return (
    <div>
      <label htmlFor={id} className="text-sm font-semibold">
        {label}{required ? <span className="text-destructive"> *</span> : null}
      </label>
      <label htmlFor={id} className="mt-1.5 flex min-h-24 cursor-pointer items-center gap-3 rounded-xl border border-dashed border-input bg-muted/25 px-4 py-3 transition hover:border-primary/50 hover:bg-primary/[0.03]">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
          <FileText size={19} />
        </span>
        <span className="min-w-0">
          <span className="block truncate text-sm font-semibold">{file?.name ?? "Choose a PDF or image"}</span>
          <span className="mt-0.5 block text-xs leading-5 text-muted-foreground">{file ? `${(file.size / 1024 / 1024).toFixed(1)} MB` : hint}</span>
        </span>
      </label>
      <input ref={inputRef} id={id} className="sr-only" type="file" accept="application/pdf,image/png,image/jpeg" onChange={(event) => onChange(event.target.files?.[0] ?? null)} />
    </div>
  );
}

function PaperCard({
  paper,
  busyAction,
  onOpenPdf,
  onExtracted,
  onToggleActive,
  onEdit,
  onDelete,
}: {
  paper: EvaluationPaper;
  busyAction: string | null;
  onOpenPdf: (paper: EvaluationPaper, kind: "question" | "answer") => void;
  onExtracted: (paper: EvaluationPaper) => void;
  onToggleActive: (paper: EvaluationPaper) => void;
  onEdit: (paper: EvaluationPaper) => void;
  onDelete: (paper: EvaluationPaper) => void;
}) {
  const busy = busyAction === paper.id;
  return (
    <article className="group relative overflow-hidden rounded-2xl border bg-card shadow-sm transition hover:-translate-y-0.5 hover:shadow-md">
      <div className="h-1 bg-gradient-to-r from-primary to-primary/45" />
      <div className="flex h-full flex-col p-5">
        <div className="flex items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full border border-primary/20 bg-primary/10 px-3 py-1 text-[11px] font-extrabold uppercase tracking-[0.08em] text-primary">Mock</span>
            <span className="rounded-full border bg-muted/40 px-3 py-1 text-[11px] font-bold text-muted-foreground">Test</span>
            <span className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-[11px] font-bold ${paper.is_active === false ? "border-border bg-muted text-muted-foreground" : "border-emerald-200 bg-emerald-50 text-emerald-700"}`}>
              <span className={`h-1.5 w-1.5 rounded-full ${paper.is_active === false ? "bg-muted-foreground" : "bg-emerald-500"}`} />
              {paper.is_active === false ? "Unpublished" : "Published"}
            </span>
          </div>
          <span title={statusLabel(paper.rubric_status)} className={`h-2.5 w-2.5 shrink-0 rounded-full ${paper.rubric_status === "ready" ? "bg-emerald-500" : paper.rubric_status === "failed" ? "bg-destructive" : "animate-pulse bg-amber-400"}`} />
        </div>

        <div className="mt-5">
          <h3 className="line-clamp-2 text-base font-bold leading-6">{paper.title}</h3>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <span className="rounded-md bg-primary/10 px-2 py-1 font-semibold text-primary">{paper.subject_name || "Subject"}</span>
            {monthLabel(paper.created_at) ? <span>{monthLabel(paper.created_at)}</span> : null}
          </div>
        </div>

        <div className="mt-4 flex flex-wrap gap-2">
          <span className="inline-flex items-center gap-1.5 rounded-lg border bg-muted/30 px-3 py-2 text-xs font-semibold">
            <FileText size={14} /> {paper.total_marks}m
          </span>
          <span className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-100 bg-emerald-50 px-3 py-2 text-xs font-semibold text-emerald-700">
            <Inbox size={14} /> {paper.submission_count ?? 0} submissions
          </span>
          <span className="inline-flex items-center gap-1.5 rounded-lg border bg-muted/30 px-3 py-2 text-xs font-semibold text-muted-foreground">
            {statusLabel(paper.rubric_status)}
          </span>
        </div>

        <div className={`mt-4 grid gap-2 ${paper.has_suggested_answer ? "grid-cols-3" : "grid-cols-2"}`}>
          <button type="button" aria-label="Question PDF" onClick={() => onOpenPdf(paper, "question")} className="inline-flex min-h-10 items-center justify-center gap-1.5 rounded-lg border border-primary/20 bg-primary/5 px-2 text-xs font-bold text-primary transition hover:bg-primary hover:text-primary-foreground">
            <FileText size={14} /> <span className="hidden sm:inline">Question </span>PDF
          </button>
          {paper.has_suggested_answer ? (
            <button type="button" aria-label="Answers PDF" onClick={() => onOpenPdf(paper, "answer")} className="inline-flex min-h-10 items-center justify-center gap-1.5 rounded-lg border border-primary/20 bg-primary/5 px-2 text-xs font-bold text-primary transition hover:bg-primary hover:text-primary-foreground">
              <BookOpen size={14} /> <span className="hidden sm:inline">Answers </span>PDF
            </button>
          ) : null}
          <button type="button" aria-label="Extracted Text" onClick={() => onExtracted(paper)} className="inline-flex min-h-10 items-center justify-center gap-1.5 rounded-lg border border-blue-200 bg-blue-50 px-2 text-xs font-bold text-blue-700 transition hover:bg-blue-100">
            <FileText size={14} /> Extracted<span className="hidden sm:inline"> Text</span>
          </button>
        </div>

        <div className="mt-5 grid grid-cols-[1fr_1fr_auto] gap-2 border-t pt-4">
          <button type="button" disabled={busy} onClick={() => onToggleActive(paper)} className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg bg-foreground px-3 text-xs font-bold text-background transition hover:opacity-90 disabled:opacity-50">
            {busy ? <RefreshCw size={14} className="animate-spin" /> : paper.is_active === false ? <Check size={14} /> : <BookOpen size={14} />}
            {paper.is_active === false ? "Publish" : "Unpublish"}
          </button>
          <button type="button" onClick={() => onEdit(paper)} className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border bg-background px-3 text-xs font-bold transition hover:border-primary/40 hover:text-primary">
            <Pencil size={14} /> Edit
          </button>
          <button type="button" onClick={() => onDelete(paper)} aria-label={`Delete ${paper.title}`} className="flex min-h-10 min-w-10 items-center justify-center rounded-lg border border-destructive/25 bg-destructive/5 text-destructive transition hover:bg-destructive/10">
            <Trash size={14} />
          </button>
        </div>
      </div>
    </article>
  );
}

function EditPaperDialog({
  paper,
  courses,
  busy,
  onClose,
  onSave,
}: {
  paper: EvaluationPaper;
  courses: Course[];
  busy: boolean;
  onClose: () => void;
  onSave: (values: {
    course_level_id: string;
    subject_id: string;
    title: string;
    total_marks: number;
    mcq_marks: number | null;
    is_active: boolean;
    question_paper?: File;
    suggested_answer?: File;
  }) => void;
}) {
  const [title, setTitle] = useState(paper.title);
  const [marks, setMarks] = useState(paper.total_marks);
  const [mcqMarks, setMcqMarks] = useState<number | "">(paper.mcq_marks ?? "");
  const [courseLevelId, setCourseLevelId] = useState(paper.course_level_id);
  const [subjectId, setSubjectId] = useState(paper.subject_id);
  const [active, setActive] = useState(paper.is_active !== false);
  const [questionPaper, setQuestionPaper] = useState<File | null>(null);
  const [suggestedAnswer, setSuggestedAnswer] = useState<File | null>(null);
  const questionRef = useRef<HTMLInputElement>(null);
  const answerRef = useRef<HTMLInputElement>(null);
  const levels = useMemo(
    () => courses.flatMap((course) => (course.levels ?? []).map((level) => ({ ...level, course }))),
    [courses],
  );
  const selectedLevel = levels.find((item) => item.id === courseLevelId);
  const subjects = (selectedLevel?.course.subjects ?? []).filter(
    (subject) => subject.course_level_id === courseLevelId,
  );
  const rubricWillRebuild = Boolean(
    questionPaper || suggestedAnswer || marks !== paper.total_marks || mcqMarks !== (paper.mcq_marks ?? ""),
  );
  return (
    <Dialog
      onClose={onClose}
      ariaLabel="Edit evaluation paper"
      overlayClassName="fixed inset-0 z-[80] flex items-center justify-center bg-slate-950/75 p-3 backdrop-blur-sm sm:p-6"
      contentClassName="flex max-h-[94vh] w-full max-w-5xl flex-col overflow-hidden rounded-2xl border bg-card shadow-2xl"
    >
      <header className="flex shrink-0 items-center justify-between gap-4 bg-slate-950 px-5 py-4 text-white sm:px-6">
        <div>
          <p className="text-[11px] font-bold uppercase tracking-[0.16em] text-white/55">Editing paper</p>
          <h2 className="mt-0.5 text-lg font-bold">Edit question paper</h2>
        </div>
        <button type="button" onClick={onClose} aria-label="Close edit paper" className="flex h-9 w-9 items-center justify-center rounded-lg bg-white/10 transition hover:bg-white/20"><X size={17} /></button>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto p-5 sm:p-6">
        <section className="rounded-2xl border bg-background p-5 sm:p-6">
          <div className="flex items-center gap-3 border-b pb-4">
            <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-primary text-primary-foreground"><Pencil size={16} /></span>
            <div><h3 className="font-bold">Paper details</h3><p className="text-xs text-muted-foreground">Update the classification and details students see.</p></div>
          </div>
          <div className="mt-5 grid gap-5 sm:grid-cols-2">
            <label className="text-sm font-semibold sm:col-span-2">Paper title<span className="text-destructive"> *</span><input className={field} value={title} maxLength={200} onChange={(event) => setTitle(event.target.value)} /></label>
            <label className="text-sm font-semibold">Course and level<span className="text-destructive"> *</span>
              <select className={field} value={courseLevelId} onChange={(event) => { setCourseLevelId(event.target.value); setSubjectId(""); }}>
                <option value="">Select course and level…</option>
                {levels.map((item) => <option key={item.id} value={item.id}>{item.course.name} · {item.name}</option>)}
              </select>
              <span className="mt-1.5 block text-xs font-normal leading-5 text-muted-foreground">Changing the course or subject only reclassifies the paper. Existing PDFs and rubric stay unchanged.</span>
            </label>
            <label className="text-sm font-semibold">Subject<span className="text-destructive"> *</span>
              <select className={field} value={subjectId} disabled={!courseLevelId} onChange={(event) => setSubjectId(event.target.value)}>
                <option value="">{courseLevelId ? "Select subject…" : "Select course first"}</option>
                {subjects.map((subject) => <option key={subject.id} value={subject.id}>{subject.name}</option>)}
              </select>
            </label>
            <label className="text-sm font-semibold">Total marks<span className="text-destructive"> *</span><input className={field} type="number" min={0.5} step={0.5} value={marks} onChange={(event) => setMarks(Number(event.target.value))} /></label>
            <label className="text-sm font-semibold">Externally graded MCQ marks <span className="font-normal text-muted-foreground">(optional)</span><input className={field} type="number" min={0} max={marks} step={0.5} value={mcqMarks} placeholder="None" onChange={(event) => setMcqMarks(event.target.value === "" ? "" : Number(event.target.value))} /></label>
          </div>
        </section>

        <section className="mt-5 rounded-2xl border bg-background p-5 sm:p-6">
          <h3 className="font-bold">Replace source files</h3>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">Leave a file unchanged to keep the current upload. Replacing either file automatically extracts it and rebuilds the frozen rubric.</p>
          <div className="mt-5 grid gap-5 sm:grid-cols-2">
            <FilePicker id={`edit-question-${paper.id}`} label="Question paper" hint={questionPaper ? "Selected replacement" : "Current question paper will be retained"} file={questionPaper} inputRef={questionRef} onChange={setQuestionPaper} />
            <FilePicker id={`edit-answer-${paper.id}`} label="Suggested answers" hint={suggestedAnswer ? "Selected replacement" : paper.has_suggested_answer ? "Current suggested answers will be retained" : "No current file · optional"} file={suggestedAnswer} inputRef={answerRef} onChange={setSuggestedAnswer} />
          </div>
        </section>

        <label className="mt-5 flex cursor-pointer items-center justify-between gap-4 rounded-2xl border bg-background p-5">
          <span><span className="block text-sm font-bold">Published to students</span><span className="mt-1 block text-xs text-muted-foreground">Turn this off to hide the paper without deleting it.</span></span>
          <input type="checkbox" checked={active} onChange={(event) => setActive(event.target.checked)} className="h-5 w-5 accent-primary" />
        </label>

        {rubricWillRebuild ? <div className="mt-5 flex gap-2 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900"><AlertTriangle size={18} className="mt-0.5 shrink-0" /><span>These changes affect grading. Saving will queue fresh extraction and rubric generation; the paper will show its real progress until the new rubric is ready.</span></div> : null}
      </div>

      <footer className="flex shrink-0 justify-end gap-3 border-t bg-muted/25 px-5 py-4 sm:px-6">
        <button type="button" onClick={onClose} className="h-10 rounded-lg border bg-background px-4 text-sm font-semibold">Cancel</button>
        <button type="button" disabled={busy || !title.trim() || !courseLevelId || !subjectId || marks <= 0 || (mcqMarks !== "" && mcqMarks > marks)} onClick={() => onSave({ course_level_id: courseLevelId, subject_id: subjectId, title: title.trim(), total_marks: marks, mcq_marks: mcqMarks === "" ? null : mcqMarks, is_active: active, ...(questionPaper ? { question_paper: questionPaper } : {}), ...(suggestedAnswer ? { suggested_answer: suggestedAnswer } : {}) })} className="inline-flex h-10 items-center gap-2 rounded-lg bg-primary px-5 text-sm font-semibold text-primary-foreground disabled:opacity-50">{busy ? <RefreshCw size={15} className="animate-spin" /> : <Check size={15} />}{busy ? "Saving…" : "Save changes"}</button>
      </footer>
    </Dialog>
  );
}

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
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [collapsedSubjects, setCollapsedSubjects] = useState<Set<string>>(new Set());
  const [extracted, setExtracted] = useState<{ paper: EvaluationPaper | null; loading: boolean } | null>(null);
  const [editing, setEditing] = useState<EvaluationPaper | null>(null);
  const [deleting, setDeleting] = useState<EvaluationPaper | null>(null);
  const questionInputRef = useRef<HTMLInputElement>(null);
  const answerInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    Promise.all([listCourses(), listEvaluationPapers()])
      .then(([nextCourses, nextPapers]) => {
        setCourses(nextCourses);
        setPapers(nextPapers);
      })
      .catch((reason) => setError(reason instanceof Error ? reason.message : "Couldn't load evaluation papers."))
      .finally(() => setLoading(false));
  }, []);

  const levels = useMemo(
    () => courses.flatMap((course) => (course.levels ?? []).map((level) => ({ ...level, course }))),
    [courses],
  );
  const level = levels.find((item) => item.id === courseLevelId);
  const subjects = (level?.course.subjects ?? []).filter((subject) => subject.course_level_id === courseLevelId);
  const subjectNames = useMemo(() => new Map(courses.flatMap((course) => course.subjects.map((subject) => [subject.id, subject.name] as const))), [courses]);
  const grouped = useMemo(() => {
    const groups = new Map<string, { name: string; papers: EvaluationPaper[]; submissions: number }>();
    for (const paper of papers) {
      const name = paper.subject_name || subjectNames.get(paper.subject_id) || "Other papers";
      const group = groups.get(paper.subject_id) ?? { name, papers: [], submissions: 0 };
      group.papers.push(paper);
      group.submissions += paper.submission_count ?? 0;
      groups.set(paper.subject_id, group);
    }
    return [...groups.entries()].sort(([, a], [, b]) => a.name.localeCompare(b.name));
  }, [papers, subjectNames]);

  function clearMessages() { setError(null); setSuccess(null); }

  async function create() {
    clearMessages();
    if (!courseLevelId || !subjectId || !title.trim() || !questionPaper) {
      setError("Choose a course level, subject and question-paper file, and enter a title.");
      return;
    }
    if (mcqMarks !== "" && mcqMarks > marks) {
      setError("MCQ marks cannot exceed the paper's total marks.");
      return;
    }
    setBusy(true);
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
      setPapers((current) => [{ ...paper, subject_name: paper.subject_name || subjectNames.get(subjectId) }, ...current]);
      setTitle("");
      setMcqMarks("");
      setQuestionPaper(null);
      setSuggestedAnswer(null);
      if (questionInputRef.current) questionInputRef.current.value = "";
      if (answerInputRef.current) answerInputRef.current.value = "";
      setSuccess("Paper published. Extraction and rubric preparation are running in the background.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Couldn't create the evaluation paper.");
    } finally {
      setBusy(false);
    }
  }

  async function detailedPaper(paper: EvaluationPaper) {
    const detail = await getEvaluationPaper(paper.id);
    setPapers((current) => replacePaper(current, detail));
    return detail;
  }

  async function openPdf(paper: EvaluationPaper, kind: "question" | "answer") {
    clearMessages();
    setBusyAction(paper.id);
    const documentTab = window.open("about:blank", "_blank");
    if (documentTab) documentTab.opener = null;
    try {
      const detail = await detailedPaper(paper);
      const url = kind === "question" ? detail.question_paper_url : detail.suggested_answer_url;
      if (!url) {
        documentTab?.close();
        setError(kind === "answer" ? "No suggested-answers file was uploaded for this paper." : "The question-paper file is unavailable.");
        return;
      }
      if (documentTab) documentTab.location.replace(url);
      else window.location.assign(url);
    } catch (reason) {
      documentTab?.close();
      setError(reason instanceof Error ? reason.message : "Couldn't open the paper file.");
    } finally {
      setBusyAction(null);
    }
  }

  async function openExtracted(paper: EvaluationPaper) {
    clearMessages();
    setExtracted({ paper, loading: true });
    try {
      const detail = await detailedPaper(paper);
      setExtracted({ paper: detail, loading: false });
    } catch (reason) {
      setExtracted(null);
      setError(reason instanceof Error ? reason.message : "Couldn't load the extracted paper content.");
    }
  }

  async function openEdit(paper: EvaluationPaper) {
    clearMessages();
    setBusyAction(paper.id);
    try {
      setEditing(await detailedPaper(paper));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Couldn't load the paper for editing.");
    } finally {
      setBusyAction(null);
    }
  }

  async function toggleActive(paper: EvaluationPaper) {
    clearMessages();
    setBusyAction(paper.id);
    try {
      const updated = await updateEvaluationPaper(paper.id, { is_active: paper.is_active === false });
      setPapers((current) => replacePaper(current, updated));
      setSuccess(updated.is_active === false ? "Paper unpublished." : "Paper published.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Couldn't update the paper.");
    } finally {
      setBusyAction(null);
    }
  }

  async function saveEdit(values: Parameters<typeof updateEvaluationPaper>[1]) {
    if (!editing) return;
    clearMessages();
    setBusy(true);
    try {
      const changes: Parameters<typeof updateEvaluationPaper>[1] = {};
      if (values.course_level_id !== editing.course_level_id) changes.course_level_id = values.course_level_id;
      if (values.subject_id !== editing.subject_id) changes.subject_id = values.subject_id;
      if (values.title !== editing.title) changes.title = values.title;
      if (values.total_marks !== editing.total_marks) changes.total_marks = values.total_marks;
      if (values.mcq_marks !== (editing.mcq_marks ?? null)) changes.mcq_marks = values.mcq_marks;
      if (values.is_active !== (editing.is_active !== false)) changes.is_active = values.is_active;
      if (values.question_paper) changes.question_paper = values.question_paper;
      if (values.suggested_answer) changes.suggested_answer = values.suggested_answer;
      if (Object.keys(changes).length === 0) {
        setEditing(null);
        setSuccess("No changes to save.");
        return;
      }
      const updated = await updateEvaluationPaper(editing.id, changes);
      setPapers((current) => replacePaper(current, updated));
      setEditing(null);
      const rebuildsRubric = Boolean(
        changes.question_paper
        || changes.suggested_answer
        || changes.total_marks !== undefined
        || changes.mcq_marks !== undefined,
      );
      setSuccess(rebuildsRubric
        ? "Paper updated. Fresh extraction and rubric generation have been queued."
        : "Paper details updated.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Couldn't update the paper.");
    } finally {
      setBusy(false);
    }
  }

  async function confirmDelete() {
    if (!deleting) return;
    clearMessages();
    setBusy(true);
    try {
      await deleteEvaluationPaper(deleting.id);
      setPapers((current) => current.filter((paper) => paper.id !== deleting.id));
      setDeleting(null);
      setSuccess("Paper deleted.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Couldn't delete the paper.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-7">
      <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.16em] text-primary">Paper management</p>
          <h1 className="mt-1 text-2xl font-bold tracking-tight sm:text-3xl">Handwritten evaluation</h1>
          <p className="mt-1 max-w-3xl text-sm leading-6 text-muted-foreground">Create evaluation papers, verify the extracted content, and control what enrolled students can attempt.</p>
        </div>
        <div className="flex gap-2">
          <span className="rounded-xl border bg-card px-3 py-2 text-xs font-semibold"><strong className="text-base">{papers.length}</strong> papers</span>
          <span className="rounded-xl border bg-card px-3 py-2 text-xs font-semibold"><strong className="text-base">{papers.reduce((total, paper) => total + (paper.submission_count ?? 0), 0)}</strong> submissions</span>
        </div>
      </div>

      {error ? <div role="alert" className="flex items-start gap-2 rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive"><AlertTriangle size={18} className="mt-0.5 shrink-0" /><span>{error}</span></div> : null}
      {success ? <div role="status" className="flex items-start gap-2 rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-800"><Check size={18} className="mt-0.5 shrink-0" /><span>{success}</span></div> : null}

      <section className="overflow-hidden rounded-2xl border bg-card shadow-sm">
        <div className="flex items-start gap-3 border-b bg-muted/25 px-5 py-4 sm:px-6">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary"><Plus size={19} /></span>
          <div><h2 className="text-lg font-bold">Create evaluation paper</h2><p className="mt-0.5 text-sm text-muted-foreground">Upload the source files and publish the paper to matching enrolled students.</p></div>
        </div>
        <div className="p-5 sm:p-6">
          <div className="grid gap-5 lg:grid-cols-2">
            <label className="text-sm font-semibold">Course level<span className="text-destructive"> *</span>
              <select className={field} value={courseLevelId} onChange={(event) => { setCourseLevelId(event.target.value); setSubjectId(""); }}>
                <option value="">Choose a course and level…</option>
                {levels.map((item) => <option key={item.id} value={item.id}>{item.course.name} · {item.name}</option>)}
              </select>
            </label>
            <label className="text-sm font-semibold">Subject<span className="text-destructive"> *</span>
              <select className={field} value={subjectId} disabled={!courseLevelId} onChange={(event) => setSubjectId(event.target.value)}>
                <option value="">{courseLevelId ? "Choose a subject…" : "Choose a course level first"}</option>
                {subjects.map((subject) => <option key={subject.id} value={subject.id}>{subject.name}</option>)}
              </select>
            </label>
            <label className="text-sm font-semibold lg:col-span-2">Paper title<span className="text-destructive"> *</span>
              <input className={field} value={title} maxLength={200} placeholder="e.g. Business Law Mock Test — August 2026" onChange={(event) => setTitle(event.target.value)} />
            </label>
            <label className="text-sm font-semibold">Total marks<span className="text-destructive"> *</span>
              <input className={field} type="number" min={0.5} step={0.5} value={marks} onChange={(event) => setMarks(Number(event.target.value))} />
            </label>
            <label className="text-sm font-semibold">MCQ marks graded separately <span className="font-normal text-muted-foreground">(optional)</span>
              <input className={field} type="number" min={0} max={marks} step={0.5} value={mcqMarks} placeholder="None" onChange={(event) => setMcqMarks(event.target.value === "" ? "" : Number(event.target.value))} />
            </label>
            <FilePicker inputRef={questionInputRef} id="evaluation-question-paper" label="Question paper" hint="PDF, PNG or JPEG · maximum 30 MB" required file={questionPaper} onChange={setQuestionPaper} />
            <FilePicker inputRef={answerInputRef} id="evaluation-suggested-answer" label="Suggested answers" hint="Optional · improves rubric quality" file={suggestedAnswer} onChange={setSuggestedAnswer} />
          </div>
          <div className="mt-6 flex flex-col-reverse items-stretch justify-between gap-3 border-t pt-5 sm:flex-row sm:items-center">
            <p className="text-xs leading-5 text-muted-foreground">Publishing starts extraction and rubric generation automatically.</p>
            <button type="button" disabled={busy} onClick={() => void create()} className="inline-flex h-11 items-center justify-center gap-2 rounded-xl bg-primary px-6 text-sm font-bold text-primary-foreground shadow-sm transition hover:opacity-90 disabled:opacity-50">
              {busy ? <RefreshCw size={16} className="animate-spin" /> : <Plus size={16} />}{busy ? "Publishing…" : "Publish paper"}
            </button>
          </div>
        </div>
      </section>

      <section>
        <div className="mb-4 flex items-end justify-between gap-3">
          <div><h2 className="text-xl font-bold">Published papers</h2><p className="mt-1 text-sm text-muted-foreground">Manage paper availability and inspect exactly what the evaluator will use.</p></div>
        </div>
        {loading ? (
          <div className="flex min-h-44 items-center justify-center rounded-2xl border bg-card"><RefreshCw size={22} className="animate-spin text-primary" /><span className="ml-3 text-sm font-semibold">Loading papers…</span></div>
        ) : papers.length === 0 ? (
          <div className="rounded-2xl border border-dashed bg-card p-10 text-center"><FileText size={30} className="mx-auto text-muted-foreground" /><h3 className="mt-3 font-semibold">No evaluation papers yet</h3><p className="mt-1 text-sm text-muted-foreground">Your first published paper will appear here.</p></div>
        ) : (
          <div className="space-y-5">
            {grouped.map(([groupId, group]) => {
              const collapsed = collapsedSubjects.has(groupId);
              return (
                <div key={groupId} className="relative border-l-2 border-primary/25 pl-4">
                  <button type="button" onClick={() => setCollapsedSubjects((current) => { const next = new Set(current); if (next.has(groupId)) next.delete(groupId); else next.add(groupId); return next; })} className="mb-3 flex min-h-10 w-full items-center gap-2 text-left">
                    <ChevronDown size={17} className={`text-muted-foreground transition ${collapsed ? "-rotate-90" : ""}`} />
                    <span className="font-bold">{group.name}</span>
                    <span className="rounded-full bg-primary/10 px-2 py-0.5 text-xs font-bold text-primary">{group.papers.length}</span>
                    <span className="text-xs text-muted-foreground">· {group.submissions} submissions</span>
                  </button>
                  {!collapsed ? <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{group.papers.map((paper) => <PaperCard key={paper.id} paper={paper} busyAction={busyAction} onOpenPdf={(item, kind) => void openPdf(item, kind)} onExtracted={(item) => void openExtracted(item)} onToggleActive={(item) => void toggleActive(item)} onEdit={(item) => void openEdit(item)} onDelete={setDeleting} />)}</div> : null}
                </div>
              );
            })}
          </div>
        )}
      </section>

      {extracted ? <EvaluationPaperExtractedDialog paper={extracted.paper} loading={extracted.loading} onClose={() => setExtracted(null)} /> : null}
      {editing ? <EditPaperDialog paper={editing} courses={courses} busy={busy} onClose={() => setEditing(null)} onSave={(values) => void saveEdit(values)} /> : null}
      {deleting ? (
        <Dialog onClose={() => setDeleting(null)} ariaLabel="Delete evaluation paper" contentClassName="w-full max-w-md rounded-2xl border bg-card p-6 text-center shadow-2xl">
          <span className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-destructive/10 text-destructive"><Trash size={21} /></span>
          <h2 className="mt-4 text-lg font-bold">Delete this paper?</h2>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">“{deleting.title}” and its uploaded files will be removed. This cannot be undone.</p>
          <div className="mt-6 grid grid-cols-2 gap-3"><button type="button" onClick={() => setDeleting(null)} className="h-10 rounded-lg border text-sm font-semibold">Cancel</button><button type="button" disabled={busy} onClick={() => void confirmDelete()} className="h-10 rounded-lg bg-destructive text-sm font-semibold text-destructive-foreground disabled:opacity-50">{busy ? "Deleting…" : "Delete paper"}</button></div>
        </Dialog>
      ) : null}
    </div>
  );
}
