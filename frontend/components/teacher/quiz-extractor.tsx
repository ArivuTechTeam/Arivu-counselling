"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { AlertTriangle, FileText, Sparkles } from "@/components/ui/icons";
import { useToast } from "@/components/ui/toast";
import {
  Chapter,
  DuplicateFileError,
  createChapter,
  extractQuiz,
  listChapters,
} from "@/lib/api";
import { useCourses } from "@/lib/staff-queries";
import { useDashboardIdentity } from "@/components/shared/dashboard-identity-context";

const fieldClass =
  "h-10 w-full rounded-md border border-input bg-background px-3 text-sm shadow-sm transition-colors focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20";

const NEW_CHAPTER = "__new__";
const EXTRACT_FORM_STORAGE_KEY = "teacher-quiz-extract-form-v1";
const MAX_EXTRACTION_BYTES = 20 * 1024 * 1024;
const EXTRACTION_EXTENSIONS = new Set(["pdf", "docx", "png", "jpg", "jpeg"]);
const EXTRACTION_MIME_TYPES = new Set([
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "image/png",
  "image/jpeg",
]);

function validateExtractionFile(file: File): string | null {
  const extension = file.name.split(".").pop()?.toLowerCase() ?? "";
  if (
    !EXTRACTION_EXTENSIONS.has(extension) ||
    (file.type !== "" && !EXTRACTION_MIME_TYPES.has(file.type))
  ) {
    return "Choose a PDF, DOCX, PNG, or JPG file.";
  }
  if (file.size > MAX_EXTRACTION_BYTES) {
    return "This file is larger than 20 MB. Choose a smaller quiz document.";
  }
  if (file.size === 0) {
    return "The selected file is empty.";
  }
  return null;
}

function Spinner() {
  return (
    <svg className="animate-spin" width="16" height="16" viewBox="0 0 24 24" fill="none">
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" strokeOpacity="0.25" />
      <path d="M22 12a10 10 0 0 1-10 10" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

function InlineError({ message }: { message: string }) {
  return (
    <div className="flex items-start gap-2 rounded-lg border border-destructive/20 bg-destructive/5 px-3 py-2 text-sm text-destructive">
      <AlertTriangle size={16} className="mt-0.5 shrink-0" />
      <span>{message}</span>
    </div>
  );
}

export function QuizExtractor() {
  const router = useRouter();
  const { notify } = useToast();
  const coursesQuery = useCourses();
  const courses = coursesQuery.data ?? [];
  const hasAssignedSubjects = courses.some((course) => course.subjects.length > 0);
  const [subjectId, setSubjectId] = useState("");

  const [chapters, setChapters] = useState<Chapter[]>([]);
  const [chapterSel, setChapterSel] = useState(""); // "" | chapterId | NEW_CHAPTER
  const [newChapterName, setNewChapterName] = useState("");
  const [rememberedFileName, setRememberedFileName] = useState<string | null>(null);
  const [formHydrated, setFormHydrated] = useState(false);

  const [file, setFile] = useState<File | null>(null);
  const [analyzePapers, setAnalyzePapers] = useState(false);
  const { features } = useDashboardIdentity();
  const paperBank = !!features?.paper_bank;
  const [busy, setBusy] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const displayError = error ?? coursesQuery.error?.message ?? null;
  const [dupMessage, setDupMessage] = useState<string | null>(null);
  // True after an extraction attempt fails (e.g. the AI timed out), so we can
  // offer a one-click retry instead of a dead-end error.
  const [canRetry, setCanRetry] = useState(false);

  useEffect(() => {
    try {
      const raw = window.sessionStorage.getItem(EXTRACT_FORM_STORAGE_KEY);
      if (raw) {
        const saved = JSON.parse(raw) as {
          subjectId?: string;
          chapterSel?: string;
        };
        setSubjectId(saved.subjectId || "");
        setChapterSel(saved.chapterSel || "");
      }
    } catch {
      try {
        window.sessionStorage.removeItem(EXTRACT_FORM_STORAGE_KEY);
      } catch {
        // Extraction still works without refresh restoration.
      }
    } finally {
      setFormHydrated(true);
    }
  }, []);

  useEffect(() => {
    if (!formHydrated) return;
    try {
      window.sessionStorage.setItem(
        EXTRACT_FORM_STORAGE_KEY,
        JSON.stringify({
          subjectId,
          chapterSel,
        }),
      );
    } catch {
      // Extraction remains available when browser storage is disabled.
    }
  }, [
    formHydrated,
    subjectId,
    chapterSel,
  ]);

  // Reload chapters for both a freshly chosen and a refresh-restored subject.
  useEffect(() => {
    if (!subjectId) {
      setChapters([]);
      return;
    }
    listChapters(subjectId)
      .then(setChapters)
      .catch(() => setChapters([]));
  }, [subjectId]);

  const chapterReady =
    chapterSel === NEW_CHAPTER ? newChapterName.trim().length > 0 : chapterSel !== "";
  const canExtract = Boolean(file && subjectId && chapterReady && !busy);

  // A live elapsed timer while extracting, so the wait feels tracked, not stuck.
  useEffect(() => {
    if (!busy) {
      setElapsed(0);
      return;
    }
    const t = window.setInterval(() => setElapsed((s) => s + 1), 1000);
    return () => window.clearInterval(t);
  }, [busy]);

  async function handleExtract(force = false) {
    if (!file || !subjectId || !chapterReady) return;
    setBusy(true);
    setError(null);
    setDupMessage(null);
    setCanRetry(false);
    try {
      // Resolve the chapter: create a new one (get-or-create) or use the picked id.
      let chapterId = chapterSel;
      if (chapterSel === NEW_CHAPTER) {
        const chapter = await createChapter(subjectId, newChapterName.trim());
        chapterId = chapter.id;
      }
      const res = await extractQuiz(file, subjectId, chapterId, force, analyzePapers);
      window.sessionStorage.removeItem(EXTRACT_FORM_STORAGE_KEY);
      if ("background_job" in res) {
        setBusy(false);
        window.dispatchEvent(new Event("faculty-job-queued"));
        notify("Import queued. You can leave this page and open the quiz from Recent tasks when it is ready.", "success");
        return;
      }
      notify(
        `${res.extracted} questions imported${res.skipped ? `; ${res.skipped} skipped — check the import receipt` : " — review against your original paper"}`,
        "success",
      );
      // Hand off to the existing review screen to check/edit/publish.
      router.push(`/dashboard/teacher/review/${res.quiz_set_id}`);
    } catch (e) {
      if (e instanceof DuplicateFileError) {
        setDupMessage(e.message); // offer "extract anyway"
      } else {
        setError(e instanceof Error ? e.message : "Extraction failed. Please try again.");
        setCanRetry(true); // the file is still selected — allow a retry
      }
      setBusy(false);
    }
  }

  return (
    <Card className="animate-rise">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Sparkles size={18} className="text-primary" />
          Extract a quiz from a document
        </CardTitle>
        <CardDescription>
          Upload an existing quiz — a typed PDF, a scanned image, or a DOCX — and
          we&apos;ll pull out the questions, options and answers for you to review
          and publish.
        </CardDescription>
      </CardHeader>

      <CardContent className="flex flex-col gap-5">
        {/* Subject */}
        <div className="flex flex-col gap-1.5">
          <label className="text-sm font-medium text-foreground">Subject</label>
          <select
            className={fieldClass}
            value={subjectId}
            onChange={(e) => {
              setSubjectId(e.target.value);
              setChapterSel("");
              setNewChapterName("");
            }}
            disabled={busy || (coursesQuery.data !== undefined && !hasAssignedSubjects)}
          >
            <option value="">Select a subject…</option>
            {courses.map((c) => (
              <optgroup key={c.id} label={c.name}>
                {c.subjects.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.level_name ? `${s.level_name} — ${s.name}` : s.name}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
          {coursesQuery.data !== undefined && !hasAssignedSubjects && !coursesQuery.error && (
            <p className="text-xs text-amber-700">
              No subjects are assigned to you yet. Ask your institution administrator to assign one before importing a quiz.
            </p>
          )}
        </div>

        {/* Chapter (required) — pick one or add a new one under this subject */}
        <div className="flex flex-col gap-1.5">
          <label className="text-sm font-medium text-foreground">Chapter</label>
          <select
            className={fieldClass}
            value={chapterSel}
            onChange={(e) => setChapterSel(e.target.value)}
            disabled={busy || !subjectId}
          >
            <option value="">
              {subjectId ? "Select a chapter…" : "Choose a subject first"}
            </option>
            {chapters.map((ch) => (
              <option key={ch.id} value={ch.id}>
                {ch.name}
              </option>
            ))}
            {subjectId && <option value={NEW_CHAPTER}>+ Add new chapter…</option>}
          </select>
          {chapterSel === NEW_CHAPTER && (
            <input
              className={fieldClass}
              placeholder="New chapter name"
              value={newChapterName}
              onChange={(e) => setNewChapterName(e.target.value)}
              disabled={busy}
            />
          )}
          <p className="text-xs text-muted-foreground">
            Every extracted question is filed under this subject &amp; chapter.
          </p>
        </div>

        {/* File */}
        <div className="flex flex-col gap-1.5">
          <label className="text-sm font-medium text-foreground">
            Quiz document
          </label>
          <label
            htmlFor="extract-file"
            className={`flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-4 py-8 text-center transition-colors ${
              busy
                ? "pointer-events-none opacity-60"
                : "border-input hover:border-primary/50 hover:bg-accent/40"
            }`}
          >
            <FileText size={24} className="text-muted-foreground" />
            <span className="text-sm font-medium text-foreground">
              {file
                ? file.name
                : rememberedFileName
                  ? `Select ${rememberedFileName} again`
                  : "Click to choose a file"}
            </span>
            <span className="text-xs text-muted-foreground">
              PDF, DOCX, or image (PNG/JPG) · up to 20 MB
            </span>
            <input
              id="extract-file"
              type="file"
              accept=".pdf,.docx,.png,.jpg,.jpeg"
              className="hidden"
              disabled={busy}
              onChange={(e) => {
                const selected = e.target.files?.[0] ?? null;
                const validationError = selected
                  ? validateExtractionFile(selected)
                  : null;
                if (validationError) {
                  setFile(null);
                  setRememberedFileName(null);
                  setError(validationError);
                  e.currentTarget.value = "";
                } else {
                  setFile(selected);
                  setRememberedFileName(selected?.name || null);
                  setError(null);
                }
                setDupMessage(null);
                setCanRetry(false);
              }}
            />
          </label>
          {!file && rememberedFileName && (
            <p className="text-xs text-amber-700">
              Your subject and chapter were restored. Browsers do not allow a
              file to be reattached automatically after refresh, so choose the
              same file once more.
            </p>
          )}
        </div>

        {displayError && <InlineError message={displayError} />}

        {paperBank && (
          <label className="flex items-start gap-2.5 rounded-lg border border-input bg-background px-3 py-2.5 text-sm">
            <input
              type="checkbox"
              className="mt-0.5 h-4 w-4 accent-primary"
              checked={analyzePapers}
              disabled={busy}
              onChange={(e) => setAnalyzePapers(e.target.checked)}
            />
            <span>
              <span className="font-medium text-foreground">
                Also add to the paper bank (previous-year, mock test and revision papers)
              </span>
              <span className="mt-0.5 block text-xs text-muted-foreground">
                Tick this if the document is an exam paper. The AI classifies each question (exam &amp; year),
                and they feed student Mock Test &amp; PYQ practice and Generate exam paper.
                Questions appear there only after you approve them and publish the quiz.
                Descriptive questions are extracted only in this mode. Leave unticked for a normal quiz.
              </span>
            </span>
          </label>
        )}

        {busy ? (
          <div className="flex flex-col gap-1 rounded-lg border border-primary/20 bg-primary/5 px-3 py-2.5 text-sm text-primary">
            <div className="flex items-center gap-2">
              <Spinner />
              <span>
                Reading your document with AI…{" "}
                <span className="tabular-nums opacity-80">
                  ({Math.floor(elapsed / 60)}:{String(elapsed % 60).padStart(2, "0")})
                </span>
              </span>
            </div>
            <p className="pl-6 text-xs text-primary/80">
              This usually takes 1–5 minutes for a typical paper. Keep this tab open — you
              can switch to other tabs meanwhile.
            </p>
          </div>
        ) : dupMessage ? (
          <div className="flex flex-col gap-2.5 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2.5 text-sm text-amber-800">
            <div className="flex items-start gap-2">
              <AlertTriangle size={16} className="mt-0.5 shrink-0" />
              <span>{dupMessage}</span>
            </div>
            <div className="flex gap-2">
              <Button onClick={() => handleExtract(true)} className="w-fit">
                Extract anyway
              </Button>
              <button
                type="button"
                onClick={() => setDupMessage(null)}
                className="rounded-lg border border-input bg-background px-3 py-2 text-sm font-medium text-foreground transition-colors hover:bg-accent"
              >
                Cancel
              </button>
            </div>
          </div>
        ) : canRetry ? (
          <Button
            onClick={() => handleExtract(true)}
            disabled={!file || !subjectId || !chapterReady}
            className="w-fit"
          >
            <Sparkles size={16} />
            Try again
          </Button>
        ) : (
          <Button onClick={() => handleExtract()} disabled={!canExtract} className="w-fit">
            <Sparkles size={16} />
            Extract quiz
          </Button>
        )}

        <p className="text-xs text-muted-foreground">
          Extracted questions land in your <strong>Review queue</strong> as a
          draft — nothing is shown to students until you approve and publish it.
        </p>
      </CardContent>
    </Card>
  );
}
