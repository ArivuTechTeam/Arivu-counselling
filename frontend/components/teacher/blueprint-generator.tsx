"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { AlertTriangle, Check, Sparkles, Zap } from "@/components/ui/icons";
import { useToast } from "@/components/ui/toast";
import {
  BlueprintTopicInput,
  Chapter,
  DocumentOut,
  analyzeDocument,
  checkDocumentDuplicate,
  generateBlueprintQuiz,
  generateFromJob,
  getGenerationJob,
  listChapters,
  listDocuments,
  retryGenerationJob,
  uploadDocument,
} from "@/lib/api";
import { useCourses } from "@/lib/staff-queries";

const fieldClass =
  "h-10 w-full rounded-md border border-input bg-background px-3 text-sm shadow-sm transition-colors focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20";

const MAX_UPLOAD_MB = 150;
const MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024;
const ALLOWED_UPLOAD_EXTENSIONS = new Set(["pdf", "docx"]);

const QUESTION_TYPES = [
  { value: "mcq_single", label: "Single choice" },
  { value: "mcq_multi", label: "Multiple choice" },
  { value: "true_false", label: "True / False" },
  { value: "numerical", label: "Numerical" },
  { value: "fill_blank", label: "Fill in the blank" },
];

function Spinner() {
  return (
    <svg className="animate-spin" width="16" height="16" viewBox="0 0 24 24" fill="none">
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" strokeOpacity="0.25" />
      <path d="M22 12a10 10 0 0 1-10 10" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

// Inline, tinted error row — replaces bare `text-red-600` paragraphs.
function InlineError({ message }: { message: string }) {
  return (
    <div className="flex items-start gap-2 rounded-lg border border-destructive/20 bg-destructive/5 px-3 py-2 text-sm text-destructive">
      <AlertTriangle size={16} className="mt-0.5 shrink-0" />
      <span>{message}</span>
    </div>
  );
}

function StepBar({ step }: { step: number }) {
  const steps = ["Generate", "Topics", "Review"];
  return (
    <div className="flex flex-wrap items-center gap-2">
      {steps.map((label, i) => {
        const n = i + 1;
        const active = n === step;
        const done = n < step;
        return (
          <div key={label} className="flex items-center gap-2">
            <div
              className={`flex h-7 w-7 items-center justify-center rounded-full text-xs font-semibold transition-all duration-300 ${
                done
                  ? "bg-emerald-500 text-white"
                  : active
                    ? "scale-110 bg-primary text-primary-foreground shadow-glow"
                    : "bg-muted text-muted-foreground"
              }`}
            >
              {done ? <Check size={14} /> : n}
            </div>
            <span
              className={`text-sm transition-colors ${
                active ? "font-semibold text-foreground" : "text-muted-foreground"
              }`}
            >
              {label}
            </span>
            {i < steps.length - 1 && (
              <div
                className={`h-0.5 w-8 rounded transition-colors duration-300 ${
                  done ? "bg-emerald-500" : "bg-muted"
                }`}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}

/**
 * Generate quiz (Create Quiz — page 1): upload a document + set the constraints
 * (subject, chapter, topics, question settings), then Generate → the app creates
 * a draft quiz set and navigates to the Review queue (page 2/3).
 */
export function BlueprintGenerator() {
  const router = useRouter();
  const { notify } = useToast();
  const coursesQuery = useCourses();

  const [documents, setDocuments] = useState<DocumentOut[]>([]);
  const [documentId, setDocumentId] = useState("");
  const [uploading, setUploading] = useState(false);
  const [uploadedName, setUploadedName] = useState<string | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);

  const courses = coursesQuery.data ?? [];
  const [subjectId, setSubjectId] = useState("");
  const [chapterName, setChapterName] = useState("");
  const [chapters, setChapters] = useState<Chapter[]>([]);
  const [addingNewChapter, setAddingNewChapter] = useState(false);

  const [extracting, setExtracting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Non-blocking notice when the same file is already filed under this
  // subject + chapter (surfaced at the "Extract topics" step; never blocks).
  const [duplicateWarning, setDuplicateWarning] = useState<string | null>(null);
  const displayError = error ?? coursesQuery.error?.message ?? null;
  const [topics, setTopics] = useState<string[]>([]);
  const [topicPageRanges, setTopicPageRanges] = useState<
    Record<string, { start: number; end: number }[]>
  >({});
  // Per-topic blueprint: for each SELECTED topic, how many of each format. A
  // topic key present here = selected; {} = selected but nothing set yet.
  const [topicCounts, setTopicCounts] = useState<
    Record<string, Record<string, number>>
  >({});
  const [newTopic, setNewTopic] = useState("");
  const [selectionError, setSelectionError] = useState<string | null>(null);

  // Legacy (no-topic) flow: global per-type counts — used only when the teacher
  // selects no topic at all (whole-document coverage, current behaviour).
  const [typeCounts, setTypeCounts] = useState<Record<string, number>>({
    mcq_single: 5,
    true_false: 5,
  });
  const [level, setLevel] = useState("mixed");
  const [difficulty, setDifficulty] = useState("medium");
  // Per-topic flow target: the teacher enters the overall total; the per-topic
  // counts must sum to it. Only used when at least one topic is selected.
  const [desiredTotal, setDesiredTotal] = useState(10);
  // One-time "what to do next" guidance shown after topics are extracted.
  const [showTopicHelp, setShowTopicHelp] = useState(false);

  const [generating, setGenerating] = useState(false);
  const [genError, setGenError] = useState<string | null>(null);
  // Large documents are analysed in the background (chunk → MAP → REDUCE) before
  // topics appear. `jobId` (set once analysis is under way) also routes the final
  // generation to the job path; null = small-document single-call flow.
  const [jobId, setJobId] = useState<string | null>(null);
  const [analysis, setAnalysis] = useState<
    { status: string; phase: string; done: number; total: number } | null
  >(null);

  useEffect(() => {
    listDocuments()
      .then((docs) => setDocuments(docs.filter((d) => d.status === "completed")))
      .catch((e) => setError(e.message));
  }, []);

  // Load the selected subject's chapters for the dropdown.
  useEffect(() => {
    setChapterName("");
    setAddingNewChapter(false);
    if (!subjectId) {
      setChapters([]);
      return;
    }
    listChapters(subjectId)
      .then(setChapters)
      .catch((e) => {
        setChapters([]);
        setError(e.message);
      });
  }, [subjectId]);

  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploadError(null);
    const extension = file.name.split(".").pop()?.toLowerCase() ?? "";
    if (!ALLOWED_UPLOAD_EXTENSIONS.has(extension)) {
      setUploadError("Choose a PDF or DOCX file.");
      e.target.value = "";
      return;
    }
    if (file.size === 0) {
      setUploadError("The selected file is empty.");
      e.target.value = "";
      return;
    }
    if (file.size > MAX_UPLOAD_BYTES) {
      setUploadError(`Choose a file no larger than ${MAX_UPLOAD_MB} MB.`);
      e.target.value = "";
      return;
    }
    setUploading(true);
    try {
      const res = await uploadDocument(file);
      setDocuments((prev) => [
        res.document,
        ...prev.filter((d) => d.id !== res.document.id),
      ]);
      setJobId(null);
      setAnalysis(null);
      setTopics([]);
      setTopicPageRanges({});
      setTopicCounts({});
      setDuplicateWarning(null);
      setDocumentId(res.document.id);
      setUploadedName(res.document.original_filename ?? file.name);
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
      e.target.value = "";
    }
  }

  const analyzing =
    analysis?.status === "queued" || analysis?.status === "running";
  const canExtract =
    Boolean(subjectId) &&
    chapterName.trim().length > 0 &&
    Boolean(documentId) &&
    !extracting &&
    !analyzing;

  async function handleExtract() {
    setError(null);
    setTopics([]);
    setTopicPageRanges({});
    setTopicCounts({});
    setShowTopicHelp(false);
    setJobId(null);
    setAnalysis(null);
    setDuplicateWarning(null);
    setExtracting(true);
    try {
      // Non-blocking: warn (but never stop) if the same file is already filed
      // under this subject + chapter. Best-effort — a check failure must not
      // block extraction.
      try {
        const dup = await checkDocumentDuplicate(
          documentId,
          subjectId,
          chapterName,
        );
        if (dup.duplicate) {
          const name = dup.previous_filename ? ` (“${dup.previous_filename}”)` : "";
          const when = dup.previous_uploaded_at
            ? ` on ${dup.previous_uploaded_at}`
            : "";
          setDuplicateWarning(
            `You've already uploaded this document${name} under this subject and chapter${when}. Generating again will create a duplicate quiz.`,
          );
        }
      } catch {
        /* ignore — duplicate check is advisory only */
      }
      const res = await analyzeDocument(documentId);
      if (res.mode === "job") {
        // Large document → background analysis. The polling effect fills in the
        // topics (and clears `analysis`) once the Master Blueprint is ready.
        setJobId(res.job_id);
        setAnalysis({ status: "queued", phase: "queued", done: 0, total: 0 });
        return;
      }
      setTopics(res.topics);
      if (res.topics.length > 0) setShowTopicHelp(true);
      if (res.topics.length === 0) {
        setError(
          "No topics found — try a document with clearer text (a scanned image PDF won't work yet).",
        );
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Extraction failed");
    } finally {
      setExtracting(false);
    }
  }

  function toggleTopic(name: string) {
    setTopicCounts((prev) => {
      const next = { ...prev };
      if (name in next) {
        delete next[name];
        setSelectionError(null);
      } else if (Object.keys(prev).length >= desiredTotal) {
        setSelectionError(
          `Increase the total questions before selecting more than ${desiredTotal} topic${desiredTotal === 1 ? "" : "s"}.`,
        );
        return prev;
      } else {
        next[name] = {};
        setSelectionError(null);
      }
      return next;
    });
  }
  function setTopicFormatCount(name: string, format: string, n: number) {
    const value = Math.max(0, Math.min(30, Number.isFinite(n) ? n : 0));
    setTopicCounts((prev) => ({
      ...prev,
      [name]: { ...(prev[name] || {}), [format]: value },
    }));
    setSelectionError(null);
  }
  function changeTotal(n: number) {
    setDesiredTotal(Math.max(1, Math.min(50, Number.isFinite(n) ? n : 1)));
    setSelectionError(null);
  }

  // Teachers can curate the extracted list: add a topic the AI missed, or drop
  // one that isn't useful. Added topics are selected by default.
  function addTopic() {
    const name = newTopic.trim();
    if (!name) return;
    const exists = topics.some((t) => t.toLowerCase() === name.toLowerCase());
    if (!exists) {
      if (Object.keys(topicCounts).length >= desiredTotal) {
        setSelectionError(
          `Increase the total questions before adding another selected topic.`,
        );
        return;
      }
      setTopics((prev) => [...prev, name]);
      setTopicCounts((prev) => ({ ...prev, [name]: {} }));
    }
    setSelectionError(null);
    setNewTopic("");
  }
  function removeTopic(name: string) {
    setTopics((prev) => prev.filter((t) => t !== name));
    setTopicCounts((prev) => {
      const next = { ...prev };
      delete next[name];
      return next;
    });
  }
  function setCount(type: string, n: number) {
    setTypeCounts((prev) => ({
      ...prev,
      [type]: Math.max(0, Math.min(30, Number.isFinite(n) ? n : 0)),
    }));
    setSelectionError(null);
  }

  // Legacy total = sum of the global per-type counts (no-topic path).
  const legacyTotal = Object.values(typeCounts).reduce((a, b) => a + (b || 0), 0);
  const selectedTopicNames = Object.keys(topicCounts);
  const perTopicMode = selectedTopicNames.length > 0;
  const allocated = selectedTopicNames.reduce(
    (sum, name) =>
      sum +
      Object.values(topicCounts[name] || {}).reduce((a, b) => a + (b || 0), 0),
    0,
  );
  const totalQuestions = perTopicMode ? desiredTotal : legacyTotal;
  const selectedCount = selectedTopicNames.length;
  const step = topics.length > 0 ? 2 : 1;

  async function handleGenerate() {
    setGenError(null);

    let selectedPayload: BlueprintTopicInput[];
    let typeCountsPayload: Record<string, number>;

    if (perTopicMode) {
      // New per-topic flow: each selected topic carries its own per-format counts,
      // and those must add up to the teacher's overall total.
      const empty = selectedTopicNames.filter(
        (name) =>
          Object.values(topicCounts[name] || {}).reduce((a, b) => a + (b || 0), 0) <
          1,
      );
      if (empty.length) {
        setGenError(`Add at least one question for: ${empty.join(", ")}.`);
        return;
      }
      if (desiredTotal > 50) {
        setGenError(
          "That's more than 50 questions in total — please reduce the counts.",
        );
        return;
      }
      if (allocated !== desiredTotal) {
        setGenError(
          `Allocate exactly ${desiredTotal} question${desiredTotal === 1 ? "" : "s"} across your topics (currently ${allocated}).`,
        );
        return;
      }
      selectedPayload = selectedTopicNames.map((name) => ({
        name,
        counts: Object.fromEntries(
          Object.entries(topicCounts[name]).filter(([, n]) => n > 0),
        ),
      }));
      typeCountsPayload = {};
    } else {
      // Legacy flow (no topic selected): whole-document coverage from a global
      // per-type mix. Large documents require at least one selected topic.
      if (jobId) {
        setGenError("Select at least one extracted topic for this large document.");
        return;
      }
      typeCountsPayload = Object.fromEntries(
        Object.entries(typeCounts).filter(([, n]) => n > 0),
      );
      if (legacyTotal < 1) {
        setGenError("Set a count of at least 1 for one or more question types.");
        return;
      }
      if (legacyTotal > 50) {
        setGenError(
          "That's more than 50 questions in total — please reduce the counts.",
        );
        return;
      }
      selectedPayload = [];
    }

    setGenerating(true);
    try {
      // Large document → generate from the ready analysis job's blueprint;
      // small document → the existing single-call blueprint path.
      const res = jobId
        ? await generateFromJob(jobId, {
            subject_id: subjectId,
            chapter_name: chapterName,
            selected_topics: selectedPayload,
            type_counts: typeCountsPayload,
            cognitive_level: level,
            difficulty,
          })
        : await generateBlueprintQuiz({
            document_id: documentId,
            subject_id: subjectId,
            chapter_name: chapterName,
            selected_topics: selectedPayload,
            type_counts: typeCountsPayload,
            cognitive_level: level,
            difficulty,
          });
      notify("✓ Quiz generated — opening your review queue", "success");
      // → page 2/3: review + publish
      router.push(`/dashboard/teacher/review/${res.quiz_set_id}`);
    } catch (e) {
      setGenError(e instanceof Error ? e.message : "Generation failed");
      setGenerating(false);
    }
  }

  // Poll a running ANALYSIS job; when it's ready, show its blueprint topics for
  // the teacher to pick (generation itself is a separate single call afterwards).
  useEffect(() => {
    if (!jobId || !analysis) return;
    if (analysis.status === "failed" || analysis.status === "partial") return;
    const timer = window.setInterval(async () => {
      try {
        const s = await getGenerationJob(jobId);
        if (s.status === "completed" && s.topics.length > 0) {
          window.clearInterval(timer);
          setTopics(s.topics.map((t) => t.name));
          setShowTopicHelp(true);
          setTopicPageRanges(
            Object.fromEntries(s.topics.map((t) => [t.name, t.page_ranges || []])),
          );
          setAnalysis(null); // ready → reveal topic picker
          return;
        }
        if (s.status === "partial") {
          window.clearInterval(timer);
          setTopics([]);
          setAnalysis({
            status: "partial",
            phase: s.phase,
            done: s.done_chunks,
            total: s.total_chunks,
          });
          return;
        }
        if (s.status === "failed") {
          window.clearInterval(timer);
          setAnalysis({
            status: "failed",
            phase: s.phase,
            done: s.done_chunks,
            total: s.total_chunks,
          });
          setError(
            s.error_message ||
              "Analysis failed. Your completed sections are saved — retry to continue.",
          );
          return;
        }
        setAnalysis({
          status: s.status,
          phase: s.phase,
          done: s.done_chunks,
          total: s.total_chunks,
        });
      } catch {
        // transient poll error — keep trying on the next tick
      }
    }, 2500);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId, analysis?.status]);

  async function retryAnalysis() {
    if (!jobId) return;
    setError(null);
    try {
      await retryGenerationJob(jobId);
      setAnalysis({ status: "running", phase: "queued", done: 0, total: 0 });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Retry failed");
    }
  }

  return (
    <div className="flex flex-col gap-6">
      {/* Informational guidance shown once topics are extracted. Collects no
          data — every input lives on the page below. */}
      {showTopicHelp && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
          role="dialog"
          aria-modal="true"
          onClick={() => setShowTopicHelp(false)}
        >
          <div
            className="w-full max-w-md rounded-2xl bg-background p-6 shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mb-1 text-3xl">🎉</div>
            <h3 className="text-lg font-semibold text-foreground">
              Topics ready!
            </h3>
            <p className="mt-1 text-sm text-muted-foreground">
              Here&apos;s how to build your quiz:
            </p>
            <ol className="mt-3 flex flex-col gap-2 text-sm text-foreground">
              <li>
                <span className="font-semibold text-primary">1.</span> Set the{" "}
                <b>total questions</b>, difficulty and style below.
              </li>
              <li>
                <span className="font-semibold text-primary">2.</span>{" "}
                <b>Click the topics</b> you want to focus on.
              </li>
              <li>
                <span className="font-semibold text-primary">3.</span> Under each
                selected topic, choose <b>how many of each format</b> (MCQ, fill
                in the blank, true/false…). The counts must add up to your total.
              </li>
            </ol>
            <p className="mt-3 rounded-lg bg-muted p-2.5 text-xs text-muted-foreground">
              Prefer whole-document coverage? Just leave every topic unselected
              and set the overall question mix.
            </p>
            <Button
              className="mt-4 w-full"
              onClick={() => setShowTopicHelp(false)}
            >
              Got it
            </Button>
          </div>
        </div>
      )}
      <div className="animate-rise">
        <StepBar step={step} />
      </div>

      {/* Step 1 — document + constraints */}
      <Card className="animate-rise" style={{ animationDelay: "60ms" }}>
        <CardHeader>
          <CardTitle>Generate a quiz</CardTitle>
          <CardDescription>
            Upload a document, set the subject &amp; chapter, then extract its
            topics to mark the important ones.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-5">
          {/* Upload card */}
          <div>
            <input
              id="doc-file"
              type="file"
              accept=".pdf,.docx"
              className="hidden"
              onChange={handleUpload}
              disabled={uploading}
            />
            <label
              htmlFor="doc-file"
              className={`flex cursor-pointer flex-col items-center gap-2 rounded-2xl border-2 border-dashed p-8 text-center transition-colors ${
                uploadedName
                  ? "border-emerald-300 bg-emerald-50/50"
                  : "border-input bg-muted/60 hover:border-primary/50 hover:bg-primary/5"
              }`}
            >
              <span className="flex h-14 w-14 items-center justify-center rounded-full bg-primary/10 text-2xl font-light text-primary">
                {uploading ? <Spinner /> : "+"}
              </span>
              <span className="flex items-center gap-1.5 text-sm font-medium text-foreground">
                {uploading ? (
                  "Uploading & extracting text…"
                ) : uploadedName ? (
                  <>
                    <Check size={15} className="text-emerald-600" />
                    {uploadedName}
                  </>
                ) : (
                  "Upload a document"
                )}
              </span>
              <span className="text-xs text-muted-foreground">
                PDF or DOCX · up to {MAX_UPLOAD_MB} MB
              </span>
            </label>
            {uploadError && (
              <div className="mt-2">
                <InlineError message={uploadError} />
              </div>
            )}
            {documents.length > 0 && (
              <div className="mt-3 flex flex-col gap-1.5">
                <span className="text-xs text-muted-foreground">
                  …or choose an already-uploaded document
                </span>
                <select
                  className={fieldClass}
                  value={documentId}
                  onChange={(e) => {
                    setJobId(null);
                    setAnalysis(null);
                    setTopics([]);
                    setTopicPageRanges({});
                    setTopicCounts({});
                    setDuplicateWarning(null);
                    setDocumentId(e.target.value);
                    const d = documents.find((x) => x.id === e.target.value);
                    setUploadedName(d?.original_filename ?? null);
                  }}
                >
                  <option value="">Select a document…</option>
                  {documents.map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.original_filename}
                    </option>
                  ))}
                </select>
              </div>
            )}
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <label className="flex flex-col gap-1.5 text-sm font-medium">
              Subject
              <select
                className={fieldClass}
                value={subjectId}
                onChange={(e) => setSubjectId(e.target.value)}
              >
                <option value="">Select a subject…</option>
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

            <label className="flex flex-col gap-1.5 text-sm font-medium">
              Chapter
              <select
                className={fieldClass}
                disabled={!subjectId}
                value={addingNewChapter ? "__new__" : chapterName}
                onChange={(e) => {
                  const v = e.target.value;
                  if (v === "__new__") {
                    setAddingNewChapter(true);
                    setChapterName("");
                  } else {
                    setAddingNewChapter(false);
                    setChapterName(v);
                  }
                }}
              >
                <option value="">
                  {subjectId ? "Select a chapter…" : "Pick a subject first"}
                </option>
                {chapters.map((c) => (
                  <option key={c.id} value={c.name}>
                    {c.name}
                  </option>
                ))}
                <option value="__new__">+ Add a new chapter</option>
              </select>
              {addingNewChapter && (
                <input
                  className={fieldClass}
                  value={chapterName}
                  onChange={(e) => setChapterName(e.target.value)}
                  placeholder="e.g. Chapter 1: Capital Budgeting"
                  autoFocus
                />
              )}
            </label>
          </div>

          <div>
            <Button onClick={handleExtract} disabled={!canExtract}>
              {extracting ? (
                <span className="flex items-center gap-2">
                  <Spinner /> Reading document…
                </span>
              ) : (
                <span className="flex items-center gap-2">
                  <Sparkles size={16} /> Extract topics
                </span>
              )}
            </Button>
          </div>
          {/* Non-blocking duplicate notice: same file already under this
              subject + chapter. Informational only — never stops generation. */}
          {duplicateWarning && (
            <div className="flex items-start gap-2 rounded-xl border border-amber-300 bg-amber-50 p-3 text-sm text-amber-800">
              <AlertTriangle size={16} className="mt-0.5 shrink-0" />
              <span className="flex-1">{duplicateWarning}</span>
              <button
                type="button"
                onClick={() => setDuplicateWarning(null)}
                className="shrink-0 font-medium text-amber-700 underline underline-offset-2 hover:text-amber-900"
              >
                Dismiss
              </button>
            </div>
          )}
          {/* Large-document analysis progress (chunk → read sections → merge) */}
          {analysis && (
            <div className="flex flex-col gap-3 rounded-xl border border-primary/20 bg-primary/5 p-4">
              <div className="flex items-center gap-2 text-sm font-medium text-primary">
                {analyzing && <Spinner />}
                {analyzing
                  ? "Analysing a large document — reading it section by section…"
                  : analysis.status === "partial"
                    ? "Some document sections could not be processed"
                    : "Analysis incomplete"}
              </div>
              <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
                <div
                  className="h-full rounded-full bg-primary transition-all duration-500"
                  style={{
                    width: `${
                      analysis.total
                        ? Math.round((analysis.done / analysis.total) * 100)
                        : 5
                    }%`,
                  }}
                />
              </div>
              <p className="text-xs text-muted-foreground">
                {analysis.total > 0
                  ? `Read ${analysis.done} of ${analysis.total} sections`
                  : "Splitting the document into sections…"}{" "}
                · this can take a couple of minutes. Topics appear here
                automatically when it&apos;s ready.
              </p>
              {analysis.status === "partial" && (
                <InlineError
                  message={`${analysis.done} of ${analysis.total} sections were processed. Topic selection is blocked because content may be missing. Retry the remaining sections to continue.`}
                />
              )}
              {(analysis.status === "failed" || analysis.status === "partial") && (
                <div className="flex flex-wrap items-center gap-3">
                  <div className="flex-1">
                    {analysis.status === "failed" && (
                      <InlineError message="Analysis stopped before it finished. Completed sections are saved — retry to continue from where it stopped." />
                    )}
                  </div>
                  <Button onClick={retryAnalysis}>
                    <Zap size={16} /> Retry
                  </Button>
                </div>
              )}
            </div>
          )}
          {displayError && <InlineError message={displayError} />}
        </CardContent>
      </Card>

      {/* Step 2 — options (total + difficulty + style + generate) */}
      {topics.length > 0 && (
        <Card className="animate-rise" style={{ animationDelay: "80ms" }}>
          <CardHeader>
            <CardTitle>Quiz options</CardTitle>
            <CardDescription>
              {perTopicMode
                ? "Set the total, then distribute it across your selected topics below — the per-topic counts must add up to the total."
                : "Choose the difficulty, style and how many of each question type. Covers the whole document."}
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            {perTopicMode && (
              <fieldset className="flex flex-col gap-2">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium text-muted-foreground">
                    Total questions for this quiz
                  </span>
                  <span
                    className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${
                      allocated === desiredTotal
                        ? "bg-primary/10 text-primary"
                        : "bg-amber-100 text-amber-800"
                    }`}
                  >
                    {allocated} / {desiredTotal} allocated
                  </span>
                </div>
                <div className="flex items-center gap-1.5">
                  <button
                    type="button"
                    aria-label="Fewer total questions"
                    onClick={() => changeTotal(desiredTotal - 1)}
                    disabled={desiredTotal <= 1}
                    className="flex h-9 w-9 items-center justify-center rounded-md border border-input text-lg leading-none text-muted-foreground transition-colors hover:border-primary/50 hover:text-primary disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    −
                  </button>
                  <input
                    type="number"
                    min={1}
                    max={50}
                    value={desiredTotal}
                    onChange={(e) => changeTotal(Number(e.target.value))}
                    className="h-9 w-14 rounded-md border border-input text-center text-sm [appearance:textfield] focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20 [&::-webkit-inner-spin-button]:appearance-none"
                  />
                  <button
                    type="button"
                    aria-label="More total questions"
                    onClick={() => changeTotal(desiredTotal + 1)}
                    disabled={desiredTotal >= 50}
                    className="flex h-9 w-9 items-center justify-center rounded-md border border-input text-lg leading-none text-muted-foreground transition-colors hover:border-primary/50 hover:text-primary disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    +
                  </button>
                </div>
                {allocated !== desiredTotal && (
                  <p className="text-xs text-amber-700">
                    {allocated < desiredTotal
                      ? `Assign ${desiredTotal - allocated} more question${desiredTotal - allocated === 1 ? "" : "s"} across your topics below.`
                      : `Remove ${allocated - desiredTotal} — you've allocated more than the total.`}
                  </p>
                )}
              </fieldset>
            )}
            {/* Per-type question counts — legacy whole-document flow (no topic selected). */}
            {!perTopicMode && (
            <fieldset className="flex flex-col gap-2">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium text-muted-foreground">
                  How many of each question type?
                </span>
                <span className="rounded-full bg-primary/10 px-2.5 py-0.5 text-xs font-semibold text-primary">
                  {totalQuestions} total
                </span>
              </div>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                {QUESTION_TYPES.map((t) => {
                  const n = typeCounts[t.value] || 0;
                  const on = n > 0;
                  return (
                    <div
                      key={t.value}
                      className={`flex items-center justify-between gap-2 rounded-lg border p-2.5 transition-colors ${
                        on ? "border-primary/40 bg-primary/5" : "border-input"
                      }`}
                    >
                      <span
                        className={`text-sm ${
                          on ? "font-medium text-foreground" : "text-muted-foreground"
                        }`}
                      >
                        {t.label}
                      </span>
                      <div className="flex items-center gap-1.5">
                        <button
                          type="button"
                          aria-label={`Fewer ${t.label}`}
                          onClick={() => setCount(t.value, n - 1)}
                          disabled={n <= 0}
                          className="flex h-9 w-9 items-center justify-center rounded-md border border-input text-lg leading-none text-muted-foreground transition-colors hover:border-primary/50 hover:text-primary disabled:cursor-not-allowed disabled:opacity-40"
                        >
                          −
                        </button>
                        <input
                          type="number"
                          min={0}
                          max={30}
                          value={n}
                          onChange={(e) => setCount(t.value, Number(e.target.value))}
                          className="h-9 w-11 rounded-md border border-input text-center text-sm [appearance:textfield] focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20 [&::-webkit-inner-spin-button]:appearance-none"
                        />
                        <button
                          type="button"
                          aria-label={`More ${t.label}`}
                          onClick={() => setCount(t.value, n + 1)}
                          className="flex h-9 w-9 items-center justify-center rounded-md border border-input text-lg leading-none text-muted-foreground transition-colors hover:border-primary/50 hover:text-primary"
                        >
                          +
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            </fieldset>
            )}

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <label className="flex flex-col gap-1.5 text-sm font-medium">
                Question style
                <select
                  className={fieldClass}
                  value={level}
                  onChange={(e) => setLevel(e.target.value)}
                >
                  <option value="theory">Theory</option>
                  <option value="practical">Practical</option>
                  <option value="mixed">Mixed</option>
                </select>
              </label>
              <label className="flex flex-col gap-1.5 text-sm font-medium">
                Difficulty
                <select
                  className={fieldClass}
                  value={difficulty}
                  onChange={(e) => setDifficulty(e.target.value)}
                >
                  <option value="easy">Easy</option>
                  <option value="medium">Medium</option>
                  <option value="hard">Hard</option>
                </select>
              </label>
            </div>

          </CardContent>
        </Card>
      )}

      {/* Step 2 — topics */}
      {topics.length > 0 && (
        <Card className="animate-rise">
          <CardHeader>
            <CardTitle>Select the important topics</CardTitle>
            <CardDescription>
              Click a topic to include it, then choose how many of each question
              format you want from it. {jobId
                ? "For this large document, questions use only the topics you select."
                : "Leave every topic unselected to cover the whole document instead."}{" "}
              <span className="font-medium text-primary">{selectedCount} selected</span>.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            {topics.map((name, i) => {
              const selected = name in topicCounts;
              const counts = topicCounts[name] || {};
              const topicTotal = Object.values(counts).reduce(
                (a, b) => a + (b || 0),
                0,
              );
              return (
                <div
                  key={name}
                  style={{ animationDelay: `${i * 40}ms` }}
                  className={`flex animate-rise flex-col gap-2 rounded-lg border p-3 text-sm transition-all ${
                    selected
                      ? "border-primary bg-primary/5 shadow-sm"
                      : "border-input hover:border-primary/40 hover:bg-accent"
                  }`}
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <button
                      type="button"
                      onClick={() => toggleTopic(name)}
                      className="flex items-center gap-2 text-left font-medium"
                    >
                      <span
                        className={`flex h-4 w-4 shrink-0 items-center justify-center rounded border text-[10px] transition-all ${
                          selected
                            ? "scale-110 border-primary bg-primary text-primary-foreground"
                            : "border-input"
                        }`}
                      >
                        {selected && <Check size={11} />}
                      </span>
                      {name}
                      {(topicPageRanges[name] || []).length > 0 && (
                        <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] font-normal text-muted-foreground">
                          pages{" "}
                          {topicPageRanges[name]
                            .map((range) =>
                              range.start === range.end
                                ? range.start
                                : `${range.start}–${range.end}`,
                            )
                            .join(", ")}
                        </span>
                      )}
                    </button>

                    <div className="flex items-center gap-2">
                      {selected && (
                        <span className="rounded-full bg-primary/10 px-2 py-0.5 text-[11px] font-semibold text-primary">
                          {topicTotal} q
                        </span>
                      )}
                      <button
                        type="button"
                        aria-label={`Remove ${name}`}
                        title="Remove this topic"
                        onClick={() => removeTopic(name)}
                        className="flex h-7 w-7 items-center justify-center rounded-md text-lg leading-none text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
                      >
                        ×
                      </button>
                    </div>
                  </div>

                  {/* Per-topic blueprint: how many of each format from THIS topic. */}
                  {selected && (
                    <div className="grid grid-cols-1 gap-2 border-t border-dashed border-primary/20 pt-2 sm:grid-cols-2">
                      {QUESTION_TYPES.map((t) => {
                        const n = counts[t.value] || 0;
                        return (
                          <div
                            key={t.value}
                            className="flex items-center justify-between gap-2 rounded-md border border-input bg-background px-2.5 py-1.5"
                          >
                            <span className="text-xs text-muted-foreground">
                              {t.label}
                            </span>
                            <div className="flex items-center gap-1">
                              <button
                                type="button"
                                aria-label={`Fewer ${t.label} from ${name}`}
                                onClick={() =>
                                  setTopicFormatCount(name, t.value, n - 1)
                                }
                                disabled={n <= 0}
                                className="flex h-7 w-7 items-center justify-center rounded-md border border-input text-base leading-none text-muted-foreground transition-colors hover:border-primary/50 hover:text-primary disabled:cursor-not-allowed disabled:opacity-40"
                              >
                                −
                              </button>
                              <input
                                type="number"
                                min={0}
                                max={30}
                                value={n}
                                onChange={(e) =>
                                  setTopicFormatCount(
                                    name,
                                    t.value,
                                    Number(e.target.value),
                                  )
                                }
                                className="h-7 w-10 rounded-md border border-input text-center text-xs [appearance:textfield] focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20 [&::-webkit-inner-spin-button]:appearance-none"
                              />
                              <button
                                type="button"
                                aria-label={`More ${t.label} from ${name}`}
                                onClick={() =>
                                  setTopicFormatCount(name, t.value, n + 1)
                                }
                                className="flex h-7 w-7 items-center justify-center rounded-md border border-input text-base leading-none text-muted-foreground transition-colors hover:border-primary/50 hover:text-primary"
                              >
                                +
                              </button>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              );
            })}

            {/* A custom topic has no consolidated source block in large-document
                mode, so only the direct/small-document flow can safely add one. */}
            {!jobId && (
              <div className="mt-2 flex items-center gap-2 border-t border-dashed border-input pt-3">
                <input
                  className={fieldClass}
                  value={newTopic}
                  onChange={(e) => setNewTopic(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      addTopic();
                    }
                  }}
                  placeholder="Add a topic the AI missed…"
                />
                <Button type="button" onClick={addTopic} disabled={!newTopic.trim()}>
                  Add
                </Button>
              </div>
            )}
            {selectionError && <InlineError message={selectionError} />}
          </CardContent>
        </Card>
      )}

      {/* Generate — placed last so the teacher clicks it right after picking
          topics and setting their per-format counts. */}
      {topics.length > 0 && (
        <div className="flex flex-col gap-2">
          <Button
            onClick={handleGenerate}
            disabled={generating || (perTopicMode && allocated !== desiredTotal)}
          >
            {generating ? (
              <span className="flex items-center gap-2">
                <Spinner /> Generating… (20–40s)
              </span>
            ) : (
              <span className="flex items-center gap-2">
                <Zap size={16} /> Generate quiz →
              </span>
            )}
          </Button>
          {perTopicMode && allocated !== desiredTotal && (
            <p className="text-xs text-amber-700">
              Allocate all {desiredTotal} questions across your topics to enable
              generation ({allocated}/{desiredTotal} so far).
            </p>
          )}
          {genError && <InlineError message={genError} />}
        </div>
      )}
    </div>
  );
}
