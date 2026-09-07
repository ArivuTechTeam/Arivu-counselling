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
import {
  Chapter,
  Course,
  DuplicateFileError,
  createChapter,
  extractQuiz,
  listChapters,
  listCourses,
} from "@/lib/api";

const fieldClass =
  "h-10 w-full rounded-md border border-input bg-background px-3 text-sm shadow-sm transition-colors focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20";

const NEW_CHAPTER = "__new__";

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
  const [courses, setCourses] = useState<Course[]>([]);
  const [subjectId, setSubjectId] = useState("");

  const [chapters, setChapters] = useState<Chapter[]>([]);
  const [chapterSel, setChapterSel] = useState(""); // "" | chapterId | NEW_CHAPTER
  const [newChapterName, setNewChapterName] = useState("");

  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dupMessage, setDupMessage] = useState<string | null>(null);

  useEffect(() => {
    listCourses()
      .then(setCourses)
      .catch((e) => setError(e instanceof Error ? e.message : "Couldn't load subjects."));
  }, []);

  // When the subject changes, reload its chapters and reset the chapter choice.
  useEffect(() => {
    setChapterSel("");
    setNewChapterName("");
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

  async function handleExtract(force = false) {
    if (!file || !subjectId || !chapterReady) return;
    setBusy(true);
    setError(null);
    setDupMessage(null);
    try {
      // Resolve the chapter: create a new one (get-or-create) or use the picked id.
      let chapterId = chapterSel;
      if (chapterSel === NEW_CHAPTER) {
        const chapter = await createChapter(subjectId, newChapterName.trim());
        chapterId = chapter.id;
      }
      const res = await extractQuiz(file, subjectId, chapterId, force);
      // Hand off to the existing review screen to check/edit/publish.
      router.push(`/dashboard/teacher/review/${res.quiz_set_id}`);
    } catch (e) {
      if (e instanceof DuplicateFileError) {
        setDupMessage(e.message); // offer "extract anyway"
      } else {
        setError(e instanceof Error ? e.message : "Extraction failed. Please try again.");
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
            onChange={(e) => setSubjectId(e.target.value)}
            disabled={busy}
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
              {file ? file.name : "Click to choose a file"}
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
                setFile(e.target.files?.[0] ?? null);
                setDupMessage(null);
              }}
            />
          </label>
        </div>

        {error && <InlineError message={error} />}

        {busy ? (
          <div className="flex items-center gap-2 rounded-lg border border-primary/20 bg-primary/5 px-3 py-2.5 text-sm text-primary">
            <Spinner />
            Reading your document with AI… this can take up to a minute. Please
            don&apos;t close this tab.
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
