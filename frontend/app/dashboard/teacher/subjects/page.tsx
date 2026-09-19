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
import {
  AlertTriangle,
  BookOpen,
  Check,
  FileText,
  Sparkles,
  TrendingUp,
  Users,
} from "@/components/ui/icons";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton, SkeletonCards, SkeletonList } from "@/components/ui/skeleton";
import {
  Chapter,
  SubjectMetrics,
  createChapter,
  deleteChapter,
  listChapters,
} from "@/lib/api";
import { useTeacherSubjectMetrics } from "@/lib/staff-queries";

type SubjectRow = { id: string; name: string; course: string };
const ACTIVE_SUBJECT_STORAGE_KEY = "teacher-subjects-active";

type IconComponent = (p: { size?: number; className?: string }) => React.JSX.Element;

// ── Score band colouring (design-system tones) ───────────────────────────────
function scoreTone(pct: number): { bar: string; text: string } {
  if (pct >= 70) return { bar: "bg-emerald-500", text: "text-emerald-600" };
  if (pct >= 40) return { bar: "bg-amber-500", text: "text-amber-600" };
  return { bar: "bg-rose-500", text: "text-rose-500" };
}

// ── Top KPI card ─────────────────────────────────────────────────────────────
function StatCard({
  icon: Icon,
  label,
  value,
  accent,
}: {
  icon: IconComponent;
  label: string;
  value: string | number;
  accent: string;
}) {
  return (
    <div className="animate-rise flex items-center gap-3 rounded-2xl border bg-card p-4 shadow-sm">
      <span
        className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl ${accent}`}
      >
        <Icon size={20} />
      </span>
      <div className="min-w-0">
        <div className="text-2xl font-bold leading-tight tracking-tight text-foreground">
          {value}
        </div>
        <div className="truncate text-xs font-medium uppercase tracking-wide text-muted-foreground">
          {label}
        </div>
      </div>
    </div>
  );
}

// ── Compact labelled metric inside a subject card ────────────────────────────
function Metric({
  icon: Icon,
  value,
  label,
}: {
  icon: IconComponent;
  value: number;
  label: string;
}) {
  return (
    <div className="flex items-center gap-2">
      <Icon size={15} className="shrink-0 text-muted-foreground" />
      <span className="text-sm font-semibold text-foreground">{value}</span>
      <span className="text-xs text-muted-foreground">{label}</span>
    </div>
  );
}

function SubjectCard({
  m,
  onOpen,
}: {
  m: SubjectMetrics;
  onOpen: () => void;
}) {
  const hasScore = m.avg_score_pct !== null;
  const pct = m.avg_score_pct ?? 0;
  const tone = scoreTone(pct);

  return (
    <div className="animate-rise flex flex-col gap-4 rounded-2xl border bg-card p-5 shadow-sm transition-all hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-md">
      {/* Header: course + subject, and the headline score */}
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <span className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground">
            {m.course_name || "Subject"}
          </span>
          <h3 className="truncate text-lg font-bold text-foreground">{m.name}</h3>
        </div>
        <div className="shrink-0 text-right">
          <div className={`text-2xl font-bold leading-none ${hasScore ? tone.text : "text-muted-foreground"}`}>
            {hasScore ? `${Math.round(pct)}%` : "—"}
          </div>
          <div className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
            avg score
          </div>
        </div>
      </div>

      {/* Average-score bar */}
      <div>
        <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
          {hasScore ? (
            <div
              className={`h-full rounded-full ${tone.bar} transition-all duration-700`}
              style={{ width: `${Math.max(4, Math.min(100, pct))}%` }}
            />
          ) : null}
        </div>
        <p className="mt-1 text-[11px] text-muted-foreground">
          {hasScore
            ? `${m.attempts} attempt${m.attempts === 1 ? "" : "s"} by ${m.students} student${m.students === 1 ? "" : "s"}`
            : "No student attempts yet"}
        </p>
      </div>

      {/* Metric grid */}
      <div className="grid grid-cols-2 gap-x-3 gap-y-2.5 border-t pt-3">
        <Metric icon={BookOpen} value={m.chapters} label="chapters" />
        <Metric icon={FileText} value={m.quizzes_total} label="quizzes" />
        <Metric icon={Sparkles} value={m.questions} label="questions" />
        <Metric icon={Users} value={m.attempts} label="attempts" />
      </div>

      {/* Quiz status + pending-review actionable chips */}
      <div className="flex flex-wrap items-center gap-2">
        {m.quizzes_published > 0 && (
          <span className="rounded-full bg-emerald-100 px-2.5 py-0.5 text-[11px] font-medium text-emerald-700">
            {m.quizzes_published} published
          </span>
        )}
        {m.quizzes_draft > 0 && (
          <span className="rounded-full bg-muted px-2.5 py-0.5 text-[11px] font-medium text-muted-foreground">
            {m.quizzes_draft} draft
          </span>
        )}
        {m.pending_review + m.needs_edit > 0 && (
          <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2.5 py-0.5 text-[11px] font-semibold text-amber-700">
            <AlertTriangle size={11} />
            {m.pending_review + m.needs_edit} to review
          </span>
        )}
      </div>

      <button
        onClick={onOpen}
        className="mt-auto w-fit text-sm font-semibold text-primary transition-colors hover:text-primary/80"
      >
        Manage chapters →
      </button>
    </div>
  );
}

export default function TeacherSubjectsPage() {
  const { data: metrics = null, error, mutate } = useTeacherSubjectMetrics();
  const [active, setActive] = useState<SubjectRow | null>(null);
  const [activeHydrated, setActiveHydrated] = useState(false);

  useEffect(() => {
    try {
      const raw = window.sessionStorage.getItem(ACTIVE_SUBJECT_STORAGE_KEY);
      if (raw) {
        const saved = JSON.parse(raw) as Partial<SubjectRow>;
        if (saved.id && saved.name) {
          setActive({ id: saved.id, name: saved.name, course: saved.course || "Subject" });
        }
      }
    } catch {
      try {
        window.sessionStorage.removeItem(ACTIVE_SUBJECT_STORAGE_KEY);
      } catch {
        // Navigation still works if session storage is unavailable.
      }
    } finally {
      setActiveHydrated(true);
    }
  }, []);

  useEffect(() => {
    if (!activeHydrated) return;
    try {
      if (active) {
        window.sessionStorage.setItem(ACTIVE_SUBJECT_STORAGE_KEY, JSON.stringify(active));
      } else {
        window.sessionStorage.removeItem(ACTIVE_SUBJECT_STORAGE_KEY);
      }
    } catch {
      // Navigation still works if session storage is unavailable.
    }
  }, [active, activeHydrated]);

  // Rolled-up KPIs for the top strip.
  const totals = useMemo(() => {
    const m = metrics ?? [];
    const scored = m.filter((s) => s.avg_score_pct !== null);
    return {
      subjects: m.length,
      quizzes: m.reduce((a, s) => a + s.quizzes_total, 0),
      questions: m.reduce((a, s) => a + s.questions, 0),
      attempts: m.reduce((a, s) => a + s.attempts, 0),
      pending: m.reduce((a, s) => a + s.pending_review + s.needs_edit, 0),
      avg:
        scored.reduce((a, s) => a + s.score_possible, 0) > 0
          ? Math.round(
              (scored.reduce((a, s) => a + s.score_earned, 0) /
                scored.reduce((a, s) => a + s.score_possible, 0)) *
                100,
            )
          : null,
    };
  }, [metrics]);

  if (active) {
    return <ChapterManager subject={active} onBack={() => setActive(null)} onChanged={() => void mutate()} />;
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Subjects"
        description="Your teaching at a glance — quizzes, student activity and scores per subject. Open one to manage its chapters."
      />

      {error ? (
        <ErrorCard message={error.message} onRetry={() => void mutate()} />
      ) : metrics === null ? (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-[76px] rounded-2xl" />
            ))}
          </div>
          <SkeletonCards count={3} />
        </>
      ) : metrics.length === 0 ? (
        <EmptyState
          icon={<BookOpen />}
          title="No subjects yet"
          message="You haven't been assigned to any subjects yet. Ask your institution admin to add you to a course."
        />
      ) : (
        <>
          {/* KPI strip */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
            <StatCard
              icon={BookOpen}
              label="Subjects"
              value={totals.subjects}
              accent="bg-primary/10 text-primary"
            />
            <StatCard
              icon={FileText}
              label="Quizzes"
              value={totals.quizzes}
              accent="bg-blue-100 text-blue-600"
            />
            <StatCard
              icon={Sparkles}
              label="Questions"
              value={totals.questions}
              accent="bg-violet-100 text-violet-600"
            />
            <StatCard
              icon={Users}
              label="Attempts"
              value={totals.attempts}
              accent="bg-amber-100 text-amber-600"
            />
            <StatCard
              icon={TrendingUp}
              label="Avg score"
              value={totals.avg === null ? "—" : `${totals.avg}%`}
              accent="bg-emerald-100 text-emerald-600"
            />
          </div>

          {totals.pending > 0 && (
            <div className="flex items-center gap-2 rounded-xl border border-amber-200 bg-amber-50 px-4 py-2.5 text-sm text-amber-800">
              <AlertTriangle size={16} className="shrink-0" />
              <span>
                <strong>{totals.pending}</strong> question
                {totals.pending === 1 ? "" : "s"} across your subjects are waiting
                for review.
              </span>
            </div>
          )}

          {/* Per-subject cards */}
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            {metrics.map((m) => (
              <SubjectCard
                key={m.id}
                m={m}
                onOpen={() =>
                  setActive({ id: m.id, name: m.name, course: m.course_name })
                }
              />
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function ChapterManager({
  subject,
  onBack,
  onChanged,
}: {
  subject: SubjectRow;
  onBack: () => void;
  onChanged: () => void;
}) {
  const [chapters, setChapters] = useState<Chapter[] | null>(null);
  const [name, setName] = useState("");
  const [nameHydrated, setNameHydrated] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  function load() {
    listChapters(subject.id)
      .then(setChapters)
      .catch((e) => setError(e.message));
  }
  useEffect(load, [subject.id]);
  useEffect(() => {
    try {
      setName(
        window.sessionStorage.getItem(`teacher-chapter-draft:${subject.id}`) || "",
      );
    } catch {
      // Start with an empty draft if session storage is unavailable.
    } finally {
      setNameHydrated(true);
    }
  }, [subject.id]);
  useEffect(() => {
    if (!nameHydrated) return;
    const key = `teacher-chapter-draft:${subject.id}`;
    try {
      if (name) window.sessionStorage.setItem(key, name);
      else window.sessionStorage.removeItem(key);
    } catch {
      // The chapter can still be submitted without draft persistence.
    }
  }, [name, nameHydrated, subject.id]);

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
      onChanged();
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
      onChanged();
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
