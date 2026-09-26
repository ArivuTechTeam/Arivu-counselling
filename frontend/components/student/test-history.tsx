"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { EmptyState } from "@/components/ui/empty-state";
import { Inbox } from "@/components/ui/icons";
import { MiniSparkline } from "@/components/ui/mini-sparkline";
import { AttemptHistoryItem } from "@/lib/api";
import { practiceTitle, variantLabel } from "@/lib/format";

function hexFor(pct: number) {
  return pct >= 70 ? "#00a651" : pct >= 40 ? "#f5a623" : "#ff6b7a";
}

export function AttemptHistoryList({
  items,
  chapterNames = {},
  emptyScope = "subject",
}: {
  items: AttemptHistoryItem[];
  chapterNames?: Record<string, string>;
  emptyScope?: "subject" | "all";
}) {
  const [mounted, setMounted] = useState(false);

  // Let the bars/rings animate from 0 once the list is in.
  useEffect(() => {
    if (items && items.length) {
      const t = setTimeout(() => setMounted(true), 80);
      return () => clearTimeout(t);
    }
  }, [items]);

  // Score trajectory over the most recent attempts (chronological, oldest→newest).
  const recent = items
    .filter((a) => a.total_score != null && a.max_score)
    .slice(0, 10);
  const trendVals = [...recent]
    .reverse()
    .map((a) => Math.round((a.total_score! / a.max_score!) * 100));
  const delta = trendVals.length >= 2 ? trendVals[trendVals.length - 1] - trendVals[0] : 0;
  const avg = trendVals.length
    ? Math.round(trendVals.reduce((s, v) => s + v, 0) / trendVals.length)
    : 0;
  const best = trendVals.length ? Math.max(...trendVals) : 0;

  return (
    <div className="flex flex-col gap-4">
      {trendVals.length >= 2 && (
        <div className="flex flex-wrap items-center justify-between gap-4 rounded-2xl border bg-card p-4 shadow-sm">
          <div className="min-w-0">
            <p className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground">
              Score trend
            </p>
            <p className="mt-1 text-sm font-medium text-foreground">
              {delta > 0
                ? `📈 Improving — up ${delta}% across your last ${trendVals.length}`
                : delta < 0
                  ? `📉 Down ${-delta}% recently — time to revise`
                  : "Holding steady"}
            </p>
            <p className="text-xs text-muted-foreground">
              Average {avg}% · Best {best}%
            </p>
          </div>
          <MiniSparkline
            values={trendVals}
            tone={delta >= 0 ? "emerald" : "rose"}
            width={160}
            height={44}
          />
        </div>
      )}
      {items.length === 0 ? (
        <EmptyState
          icon={<Inbox />}
          title={
            emptyScope === "all" ? "No quiz history yet" : "No history for this subject yet"
          }
          message={
            emptyScope === "all"
              ? "Complete a quiz or practice session and your score will appear here."
              : "Complete a quiz for this subject and your score will appear here."
          }
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
                    {a.source === "practice" ? practiceTitle(a.quiz_title) : a.quiz_title}
                  </p>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    {variantLabel(a.variant_type)}
                    {a.chapter_id && chapterNames[a.chapter_id]
                      ? ` · ${chapterNames[a.chapter_id]}`
                      : ""}
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
