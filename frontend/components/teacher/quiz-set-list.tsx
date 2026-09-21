"use client";

import Link from "next/link";
import { useState } from "react";
import { useSWRConfig } from "swr";
import { Button } from "@/components/ui/button";
import { restoreQuizSet } from "@/lib/api";
import { STAFF_QUERY_KEYS } from "@/lib/staff-queries";

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
import { SkeletonList } from "@/components/ui/skeleton";
import { statusLabel } from "@/lib/format";
import { useTeacherQuizSets } from "@/lib/staff-queries";

const SET_TONE: Record<string, string> = {
  published: "border-emerald-200 bg-emerald-50 text-emerald-700",
  draft: "border-border bg-muted/70 text-muted-foreground",
  archived: "border-border bg-muted/70 text-muted-foreground",
};

export function QuizSetList() {
  const [archived, setArchived] = useState(false);
  const [restoring, setRestoring] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const { mutate: refreshCache } = useSWRConfig();
  const { data: sets = null, error, mutate } = useTeacherQuizSets(archived);

  async function restore(id: string) {
    setRestoring(id);
    setActionError(null);
    setNotice(null);
    try {
      await restoreQuizSet(id);
      setNotice("Quiz restored to draft. Find it under Active to review and publish.");
      await Promise.all([mutate(), refreshCache(STAFF_QUERY_KEYS.teacherQuizSets)]);
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Could not restore this quiz.");
    } finally {
      setRestoring(null);
    }
  }
  const reviewSets =
    sets?.filter((set) =>
      archived ? set.status === "archived" : set.status !== "published" && set.status !== "archived",
    ) ?? [];

  return (
    <Card className="overflow-hidden rounded-2xl border-primary/10 shadow-sm">
      <CardHeader className="space-y-1 border-b bg-muted/15 p-5 sm:p-6">
        <CardTitle className="text-2xl tracking-tight">Your quizzes</CardTitle>
        <CardDescription>Review, publish, and recover archived quizzes.</CardDescription>
        <div className="flex gap-2 pt-3" aria-label="Quiz lists">
          {[false, true].map((value) => (
            <Button key={String(value)} variant={archived === value ? "default" : "outline"}
              aria-pressed={archived === value}
              onClick={() => { setArchived(value); setActionError(null); setNotice(null); }}>
              {value ? "Archived" : "Active"}
            </Button>
          ))}
        </div>
        {archived && <p className="pt-2 text-sm text-muted-foreground">Archived quizzes are unpublished. Open one to review it, or restore it to draft for later use.</p>}
        {actionError && <p role="alert" className="text-sm text-destructive">{actionError}</p>}
        {notice && <p role="status" className="text-sm text-muted-foreground">{notice}</p>}
      </CardHeader>
      <CardContent className={sets && reviewSets.length > 0 ? "p-0" : "p-5 sm:p-6"}>
        {error ? (
          <ErrorCard message={error.message} onRetry={() => void mutate()} />
        ) : sets === null ? (
          <SkeletonList />
        ) : reviewSets.length === 0 ? (
          <EmptyState
            icon={<Inbox />}
            title={archived ? "No archived quizzes" : "No active quizzes yet"}
            message={archived ? "Quizzes you archive will appear here for future reuse." : "Generate a quiz or restore one from Archived."}
            action={
              <Link
                href="/dashboard/teacher/generate"
                className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground shadow-sm transition-colors hover:bg-primary/90"
              >
                Create a quiz
              </Link>
            }
          />
        ) : (
          <div className="divide-y divide-border">
            {reviewSets.map((s) => (
              <div key={s.id} className="flex flex-wrap items-center gap-2 pr-5">
              <Link
                href={`/dashboard/teacher/review/${s.id}`}
                className="group flex min-w-0 flex-1 items-center justify-between gap-4 bg-card px-5 py-5 text-sm transition-colors hover:bg-primary/[0.035] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring sm:px-6"
              >
                <div className="min-w-0">
                  <p className="truncate text-base font-semibold tracking-tight text-foreground transition-colors group-hover:text-primary">
                    {s.title}
                  </p>
                  <p className="mt-1 text-[13px] text-muted-foreground">
                    Created {new Date(s.created_at).toLocaleDateString()}
                  </p>
                </div>
                <span className="flex shrink-0 items-center gap-3">
                  <span
                    className={`rounded-full border px-3 py-1.5 text-xs font-medium ${
                      SET_TONE[s.status] ?? "bg-muted text-muted-foreground"
                    }`}
                  >
                    {statusLabel(s.status)}
                  </span>
                  <span className="flex h-9 w-9 items-center justify-center rounded-full bg-muted text-base text-muted-foreground transition-all group-hover:translate-x-0.5 group-hover:bg-primary group-hover:text-primary-foreground">
                    →
                  </span>
                </span>
              </Link>
              {archived && <Button variant="outline" className="mb-3 ml-5 sm:mb-0 sm:ml-0"
                disabled={restoring !== null} onClick={() => void restore(s.id)}
                aria-label={`Restore ${s.title} to draft`}>
                {restoring === s.id ? "Restoring…" : "Restore to draft"}
              </Button>}
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
