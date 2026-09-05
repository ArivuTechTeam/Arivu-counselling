"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { PageHeader } from "@/components/ui/page-header";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorCard } from "@/components/ui/error-card";
import { SkeletonList } from "@/components/ui/skeleton";
import { Inbox } from "@/components/ui/icons";
import { AttemptHistoryItem, listStudentAttempts } from "@/lib/api";
import { variantLabel } from "@/lib/format";

function hexFor(pct: number) {
  return pct >= 70 ? "#00a651" : pct >= 40 ? "#f5a623" : "#ff6b7a";
}

export function TestHistory() {
  const [items, setItems] = useState<AttemptHistoryItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [mounted, setMounted] = useState(false);

  function load() {
    setError(null);
    listStudentAttempts()
      .then(setItems)
      .catch((e) => setError(e.message));
  }

  useEffect(() => {
    load();
  }, []);

  // Let the bars/rings animate from 0 once the list is in.
  useEffect(() => {
    if (items && items.length) {
      const t = setTimeout(() => setMounted(true), 80);
      return () => clearTimeout(t);
    }
  }, [items]);

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Quiz history"
        description="Every attempt you've made, newest first — tap a card to review it."
      />

      {error ? (
        <ErrorCard message={error} onRetry={load} />
      ) : items === null ? (
        <SkeletonList />
      ) : items.length === 0 ? (
        <EmptyState
          icon={<Inbox />}
          title="No attempts yet"
          message="Take a quiz to build your history — every attempt you make will show up here for you to review."
        />
      ) : (
        <div className="flex flex-col gap-4">
          {items.map((a, i) => {
            const pct =
              a.total_score != null && a.max_score
                ? Math.round((a.total_score / a.max_score) * 100)
                : 0;
            const hex = hexFor(pct);
            const ringDeg = (mounted ? pct : 0) * 3.6;
            return (
              <Link
                key={a.attempt_id}
                href={`/dashboard/student/${a.source === "practice" ? "practice" : "attempt"}/${a.attempt_id}`}
                style={{ animationDelay: `${i * 60}ms` }}
                className="group relative flex animate-rise items-center gap-5 overflow-hidden rounded-2xl border bg-card p-5 pl-6 shadow-sm transition-all hover:-translate-y-0.5 hover:shadow-md"
              >
                {/* accent strip */}
                <span
                  className="absolute inset-y-0 left-0 w-1.5"
                  style={{ background: hex }}
                />

                {/* score ring */}
                <div
                  className="relative flex h-16 w-16 shrink-0 items-center justify-center rounded-full transition-all duration-700 ease-out"
                  style={{ background: `conic-gradient(${hex} ${ringDeg}deg, #edeeec 0deg)` }}
                >
                  <div className="flex h-12 w-12 items-center justify-center rounded-full bg-card text-sm font-bold text-foreground">
                    {pct}%
                  </div>
                </div>

                {/* title + animated bar */}
                <div className="min-w-0 flex-1">
                  <p className="truncate text-base font-semibold text-foreground">
                    {a.quiz_title}
                  </p>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    {variantLabel(a.variant_type)}
                    {a.submitted_at
                      ? ` · ${new Date(a.submitted_at).toLocaleDateString()}`
                      : ""}
                  </p>
                  <div className="mt-3 h-2 w-full max-w-md overflow-hidden rounded-full bg-muted">
                    <div
                      className="h-full rounded-full transition-[width] duration-700 ease-out"
                      style={{ width: mounted ? `${pct}%` : "0%", background: hex }}
                    />
                  </div>
                </div>

                {/* score + review hint */}
                <div className="flex shrink-0 flex-col items-end gap-1">
                  <span className="text-sm font-semibold text-muted-foreground">
                    {a.total_score ?? "—"}
                    {a.max_score ? ` / ${a.max_score}` : ""}
                  </span>
                  <span className="text-xs font-medium text-primary opacity-0 transition-opacity group-hover:opacity-100">
                    Review →
                  </span>
                </div>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}
