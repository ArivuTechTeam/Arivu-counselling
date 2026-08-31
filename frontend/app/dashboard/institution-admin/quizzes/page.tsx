"use client";

import { useEffect, useMemo, useState } from "react";

import { QuestionPaperButtons } from "@/components/pdf-buttons";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorCard } from "@/components/ui/error-card";
import { Inbox } from "@/components/ui/icons";
import { PageHeader } from "@/components/ui/page-header";
import { SkeletonList } from "@/components/ui/skeleton";
import { AdminQuizSet, getAdminQuizSets } from "@/lib/api";

const STATUS_TONE: Record<string, string> = {
  published: "bg-emerald-100 text-emerald-700",
  draft: "bg-amber-100 text-amber-700",
};

export default function AdminQuizzesPage() {
  const [rows, setRows] = useState<AdminQuizSet[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  function load() {
    setError(null);
    getAdminQuizSets()
      .then(setRows)
      .catch((e) => setError(e.message));
  }
  useEffect(load, []);

  const filtered = useMemo(() => {
    const list = rows ?? [];
    const q = query.trim().toLowerCase();
    if (!q) return list;
    return list.filter((r) =>
      [r.title, r.course, r.subject, r.teacher]
        .filter(Boolean)
        .some((v) => (v as string).toLowerCase().includes(q)),
    );
  }, [rows, query]);

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Quizzes"
        description="Browse every quiz in your institution and download any as a question paper."
      />

      {error && <ErrorCard message={error} onRetry={load} />}

      <input
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Search by title, course, subject or teacher…"
        className="h-11 w-full rounded-xl border border-input bg-background px-4 text-sm shadow-sm focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
      />

      {rows === null ? (
        <SkeletonList />
      ) : filtered.length === 0 ? (
        <EmptyState
          icon={<Inbox />}
          title={rows.length === 0 ? "No quizzes yet" : "No matches"}
          message={
            rows.length === 0
              ? "Quizzes created across your institution will appear here."
              : "No quizzes match your search — try a different title, course, subject or teacher."
          }
        />
      ) : (
        <div className="flex flex-col gap-3">
          {filtered.map((q) => (
            <Card key={q.id} className="animate-rise">
              <CardHeader className="pb-3">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <CardTitle className="text-base">{q.title}</CardTitle>
                    <CardDescription className="mt-1">
                      {[q.course, q.subject, q.teacher].filter(Boolean).join(" · ") ||
                        "—"}
                      {"  ·  "}
                      {q.questions} question{q.questions === 1 ? "" : "s"}
                    </CardDescription>
                  </div>
                  <span
                    className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium capitalize ${
                      STATUS_TONE[q.status] ?? "bg-muted text-muted-foreground"
                    }`}
                  >
                    {q.status}
                  </span>
                </div>
              </CardHeader>
              <CardContent>
                <QuestionPaperButtons
                  quizSetId={q.id}
                  title={q.title}
                  meta={[q.course, q.subject].filter(Boolean).join(" · ")}
                  compact
                />
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
