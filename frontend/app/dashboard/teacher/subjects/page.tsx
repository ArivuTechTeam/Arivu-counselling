"use client";

import { useEffect, useMemo, useState } from "react";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorCard } from "@/components/ui/error-card";
import { AlertTriangle, BookOpen, Check } from "@/components/ui/icons";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton, SkeletonCards, SkeletonList } from "@/components/ui/skeleton";
import {
  Chapter,
  Course,
  createChapter,
  deleteChapter,
  listChapters,
  listCourses,
} from "@/lib/api";

type SubjectRow = { id: string; name: string; course: string };

export default function TeacherSubjectsPage() {
  const [courses, setCourses] = useState<Course[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [active, setActive] = useState<SubjectRow | null>(null);

  function load() {
    setError(null);
    listCourses()
      .then(setCourses)
      .catch((e) => setError(e.message));
  }

  useEffect(() => {
    load();
  }, []);

  const subjects: SubjectRow[] = useMemo(() => {
    const out: SubjectRow[] = [];
    for (const c of courses ?? []) {
      for (const s of c.subjects) out.push({ id: s.id, name: s.name, course: c.name });
    }
    return out;
  }, [courses]);

  if (active) {
    return (
      <ChapterManager subject={active} onBack={() => setActive(null)} />
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Subjects"
        description="Your subjects. Open one to add or remove its chapters — chapters show up when you generate a quiz and in your students' subject view."
      />

      {error ? (
        <ErrorCard message={error} onRetry={load} />
      ) : courses === null ? (
        <SkeletonCards count={3} />
      ) : subjects.length === 0 ? (
        <EmptyState
          icon={<BookOpen />}
          title="No subjects yet"
          message="You haven't been assigned to any subjects yet. Ask your institution admin to add you to a course."
        />
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {subjects.map((s) => (
            <button
              key={s.id}
              onClick={() => setActive(s)}
              className="animate-rise flex flex-col items-start gap-1 rounded-2xl border bg-card p-5 text-left shadow-sm transition-all hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-md"
            >
              <span className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground">
                {s.course}
              </span>
              <span className="text-lg font-bold text-foreground">{s.name}</span>
              <span className="mt-2 text-xs font-medium text-primary">
                Manage chapters →
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function ChapterManager({
  subject,
  onBack,
}: {
  subject: SubjectRow;
  onBack: () => void;
}) {
  const [chapters, setChapters] = useState<Chapter[] | null>(null);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  function load() {
    listChapters(subject.id)
      .then(setChapters)
      .catch((e) => setError(e.message));
  }
  useEffect(load, [subject.id]);

  async function add(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await createChapter(subject.id, trimmed);
      setName("");
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not add chapter.");
    } finally {
      setBusy(false);
    }
  }

  async function remove(c: Chapter) {
    setError(null);
    setNotice(null);
    try {
      await deleteChapter(c.id);
      setNotice(`Deleted "${c.name}".`);
      load();
    } catch (err) {
      // The backend blocks deletion when the chapter is still in use.
      setError(err instanceof Error ? err.message : "Could not delete chapter.");
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <button
        onClick={onBack}
        className="w-fit text-sm font-medium text-muted-foreground hover:text-foreground"
      >
        ← Subjects
      </button>

      <PageHeader
        title={subject.name}
        description={`${subject.course} · add the chapters that make up this subject.`}
      />

      <Card className="animate-rise">
        <CardHeader>
          <CardTitle>Add a chapter</CardTitle>
          <CardDescription>
            Chapters appear in the Chapter dropdown when you generate a quiz,
            and in your students&apos; subject view.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={add} className="flex flex-wrap items-center gap-3">
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Chapter 1: Capital Budgeting"
              className="h-10 min-w-0 flex-1 rounded-md border border-input bg-background px-3 text-sm shadow-sm focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
            />
            <button
              type="submit"
              disabled={busy || !name.trim()}
              className="h-10 shrink-0 rounded-md bg-primary px-4 text-sm font-semibold text-primary-foreground shadow-sm transition-colors hover:bg-primary/90 disabled:opacity-60"
            >
              {busy ? "Adding…" : "Add chapter"}
            </button>
          </form>
          {error && (
            <div className="mt-3 flex items-start gap-2 rounded-lg border border-destructive/20 bg-destructive/5 px-3 py-2 text-sm text-destructive">
              <AlertTriangle size={16} className="mt-0.5 shrink-0" />
              <span>{error}</span>
            </div>
          )}
          {notice && (
            <div className="mt-3 flex items-start gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
              <Check size={16} className="mt-0.5 shrink-0" />
              <span>{notice}</span>
            </div>
          )}
        </CardContent>
      </Card>

      <Card className="animate-rise">
        <CardHeader>
          <CardTitle>Chapters</CardTitle>
          <CardDescription>
            {chapters === null ? (
              <Skeleton className="h-4 w-40" />
            ) : (
              `${chapters.length} chapter${chapters.length === 1 ? "" : "s"} in this subject.`
            )}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          {chapters === null ? (
            <SkeletonList rows={3} />
          ) : chapters.length === 0 ? (
            <EmptyState
              icon={<BookOpen />}
              title="No chapters yet"
              message="Add your first chapter above to start organizing this subject."
            />
          ) : (
            chapters.map((c) => (
              <div
                key={c.id}
                className="flex items-center justify-between gap-3 rounded-lg border p-3"
              >
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-foreground">{c.name}</p>
                  <p className="text-xs text-muted-foreground">
                    {c.quiz_count} quiz{c.quiz_count === 1 ? "" : "zes"} ·{" "}
                    {c.question_count} question{c.question_count === 1 ? "" : "s"}
                  </p>
                </div>
                <button
                  onClick={() => remove(c)}
                  className="shrink-0 rounded-md border border-input px-3 py-1.5 text-xs font-medium text-destructive transition-colors hover:bg-destructive/10"
                >
                  Delete
                </button>
              </div>
            ))
          )}
        </CardContent>
      </Card>
    </div>
  );
}
