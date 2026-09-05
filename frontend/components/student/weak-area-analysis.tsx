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
import { ErrorCard } from "@/components/ui/error-card";
import { SkeletonList } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty-state";
import { BookOpen, Check } from "@/components/ui/icons";
import {
  WeakAnalysis,
  WeakChapterNode,
  WeakSubjectNode,
  getWeakAnalysis,
} from "@/lib/api";

// Below this success rate a topic counts as "weak" (needs work). At or above it
// the student is doing fine, so we hide it — this view is weak areas ONLY.
const WEAK = 60;

/** Keep only weak areas: drop strong subjects entirely, and within the rest keep
 *  only weak topics (and the chapters that still have any). A subject the student
 *  is doing well on overall never appears here. */
function onlyWeak(subjects: WeakSubjectNode[]): WeakSubjectNode[] {
  return subjects
    .filter((s) => s.accuracy < WEAK) // strong subject → gone
    .map((s) => ({
      ...s,
      chapters: s.chapters
        .map((c) => ({ ...c, topics: c.topics.filter((t) => t.accuracy < WEAK) }))
        .filter((c) => c.topics.length > 0),
    }))
    .filter((s) => s.chapters.length > 0);
}

function tone(pct: number) {
  return pct < 40 ? "#ff6b7a" : pct < 60 ? "#f5a623" : "#00a651";
}
function label(pct: number) {
  return pct < 40 ? "Weak" : pct < 60 ? "Needs work" : "Strong";
}

function Bar({ pct }: { pct: number }) {
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
      <div
        className="h-full rounded-full transition-[width] duration-700 ease-out"
        style={{ width: `${pct}%`, background: tone(pct) }}
      />
    </div>
  );
}

function Chevron({ open }: { open: boolean }) {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={`shrink-0 text-muted-foreground transition-transform ${open ? "rotate-90" : ""}`}
    >
      <polyline points="9 18 15 12 9 6" />
    </svg>
  );
}

function Pct({ pct }: { pct: number }) {
  return (
    <span className="shrink-0 text-sm font-semibold" style={{ color: tone(pct) }}>
      {pct}%
    </span>
  );
}

const ckey = (s: string, c: string) => `${s}::${c}`;

export function WeakAreaAnalysis() {
  const [data, setData] = useState<WeakAnalysis | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [openS, setOpenS] = useState<Set<string>>(new Set());
  const [openC, setOpenC] = useState<Set<string>>(new Set());

  function load() {
    setError(null);
    getWeakAnalysis()
      .then((d) => {
        setData(d);
        // Auto-open the weakest subject and its weakest chapter to guide focus.
        const weak = onlyWeak(d.subjects);
        const s0: WeakSubjectNode | undefined = weak[0];
        if (s0) {
          setOpenS(new Set([s0.subject]));
          const c0: WeakChapterNode | undefined = s0.chapters[0];
          if (c0) setOpenC(new Set([ckey(s0.subject, c0.chapter)]));
        }
      })
      .catch((e) =>
        setError(e instanceof Error ? e.message : "Could not load your analysis."),
      );
  }

  useEffect(() => {
    load();
  }, []);

  function toggleS(s: string) {
    setOpenS((prev) => {
      const next = new Set(prev);
      if (next.has(s)) next.delete(s);
      else next.add(s);
      return next;
    });
  }
  function toggleC(k: string) {
    setOpenC((prev) => {
      const next = new Set(prev);
      if (next.has(k)) next.delete(k);
      else next.add(k);
      return next;
    });
  }

  if (error) {
    return <ErrorCard message={error} onRetry={load} />;
  }

  if (data === null) {
    return <SkeletonList rows={4} />;
  }

  if (data.subjects.length === 0) {
    return (
      <EmptyState
        icon={<BookOpen />}
        title="No analysis yet"
        message="Take a quiz to unlock your weak-area analysis — once you have graded attempts, your subjects, chapters, and topics break down here."
      />
    );
  }

  const { overall } = data;
  const weakSubjects = onlyWeak(data.subjects);

  return (
    <div className="flex flex-col gap-6">
      {/* Overall summary */}
      <Card className="animate-rise">
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <CardTitle>Your weak topics</CardTitle>
              <CardDescription>
                Only your weak topics (below {WEAK}% correct) — weakest first.
                Strong topics are hidden so you can focus.
              </CardDescription>
            </div>
            <Link
              href="/dashboard/student/revision"
              className="shrink-0 rounded-md bg-primary px-3 py-1.5 text-sm font-semibold text-primary-foreground shadow-sm transition-colors hover:bg-primary/90"
            >
              Revise these →
            </Link>
          </div>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-6">
          <div>
            <div className="text-3xl font-bold" style={{ color: tone(overall.accuracy) }}>
              {overall.accuracy}%
            </div>
            <div className="text-[11px] uppercase tracking-widest text-muted-foreground">
              overall accuracy
            </div>
          </div>
          <div>
            <div className="text-3xl font-bold text-foreground">
              {overall.answered}
            </div>
            <div className="text-[11px] uppercase tracking-widest text-muted-foreground">
              questions answered
            </div>
          </div>
          <div>
            <div className="text-3xl font-bold text-rose-500">
              {overall.weak_topics}
            </div>
            <div className="text-[11px] uppercase tracking-widest text-muted-foreground">
              weak topics
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Weak subject -> chapter -> topic drill-down (weak only) */}
      {weakSubjects.length === 0 ? (
        <EmptyState
          className="animate-rise"
          icon={<Check />}
          title="No weak areas right now"
          message={`You're scoring ${WEAK}% or higher on every topic. Keep practising to stay sharp.`}
        />
      ) : (
      <div className="flex flex-col gap-3">
        {weakSubjects.map((s) => {
          const sOpen = openS.has(s.subject);
          return (
            <Card key={s.subject} className="animate-rise overflow-hidden">
              {/* Subject row */}
              <button
                type="button"
                onClick={() => toggleS(s.subject)}
                className="flex w-full items-center gap-3 p-4 text-left transition-colors hover:bg-accent"
              >
                <Chevron open={sOpen} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-3">
                    <span className="font-semibold text-foreground">{s.subject}</span>
                    <span className="flex items-center gap-2">
                      <span
                        className="rounded-full px-2 py-0.5 text-[11px] font-semibold"
                        style={{ background: `${tone(s.accuracy)}1a`, color: tone(s.accuracy) }}
                      >
                        {label(s.accuracy)}
                      </span>
                      <Pct pct={s.accuracy} />
                    </span>
                  </div>
                  <div className="mt-2">
                    <Bar pct={s.accuracy} />
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {s.answered} question{s.answered === 1 ? "" : "s"} ·{" "}
                    {s.chapters.length} chapter{s.chapters.length === 1 ? "" : "s"}
                  </p>
                </div>
              </button>

              {/* Chapters */}
              {sOpen && (
                <div className="flex flex-col gap-2 border-t bg-muted/50 p-3">
                  {s.chapters.map((c) => {
                    const k = ckey(s.subject, c.chapter);
                    const cOpen = openC.has(k);
                    return (
                      <div
                        key={k}
                        className="overflow-hidden rounded-lg border bg-card"
                      >
                        <button
                          type="button"
                          onClick={() => toggleC(k)}
                          className="flex w-full items-center gap-3 p-3 text-left transition-colors hover:bg-accent"
                        >
                          <Chevron open={cOpen} />
                          <div className="min-w-0 flex-1">
                            <div className="flex items-center justify-between gap-3 text-sm">
                              <span className="truncate font-medium text-foreground">
                                {c.chapter}
                              </span>
                              <Pct pct={c.accuracy} />
                            </div>
                            <div className="mt-1.5">
                              <Bar pct={c.accuracy} />
                            </div>
                          </div>
                        </button>

                        {/* Topics */}
                        {cOpen && (
                          <div className="flex flex-col gap-2 border-t p-3">
                            {c.topics.map((t) => (
                              <div key={t.topic} className="flex flex-col gap-1">
                                <div className="flex items-center justify-between gap-3 text-sm">
                                  <span className="truncate text-foreground">
                                    {t.topic}
                                  </span>
                                  <span className="shrink-0 text-muted-foreground">
                                    {t.accuracy}% · {t.answered} q
                                  </span>
                                </div>
                                <Bar pct={t.accuracy} />
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </Card>
          );
        })}
      </div>
      )}
    </div>
  );
}
