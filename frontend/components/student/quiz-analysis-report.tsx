"use client";

import { typeLabel } from "@/lib/format";
import { MiniBar, StatPill } from "@/components/ui/allocation-meter";
import {
  AnalysisQuestion,
  byType,
  hasTimingSignal,
  insightSentences,
  qualityCounts,
  summarize,
  timeBuckets,
} from "@/lib/quiz-analysis";

function accuracyTone(pct: number): "rose" | "amber" | "emerald" {
  if (pct < 40) return "rose";
  if (pct < 70) return "amber";
  return "emerald";
}

function fmtMinSec(sec: number): string {
  const s = Math.round(sec);
  if (s < 60) return `${s}s`;
  return `${Math.floor(s / 60)}m ${s % 60}s`;
}

/**
 * "Smart Analysis" — a diagnostic report over a graded attempt. Everything is
 * computed client-side from the results + per-question time tracked in the
 * browser. Sections that need timing hide themselves when timing is unavailable.
 */
export function QuizAnalysisReport({
  results,
  score,
  maxScore,
  times,
}: {
  results: AnalysisQuestion[];
  score: number;
  maxScore: number;
  times: Record<string, number>;
}) {
  const summary = summarize(results, score, maxScore);
  const typeStats = byType(results);
  const timed = hasTimingSignal(results, times);
  const quality = qualityCounts(results, times);
  const insights = timed ? insightSentences(quality) : [];
  const buckets = timeBuckets(results, times);

  return (
    <div className="flex flex-col gap-4 rounded-xl border bg-card p-5 shadow-sm">
      <div className="flex items-center justify-between">
        <h2 className="text-base font-semibold tracking-tight">Smart analysis</h2>
        <StatPill label="Accuracy" value={`${summary.accuracy}%`} tone={accuracyTone(summary.accuracy)} />
      </div>

      {/* Headline counts */}
      <div className="grid grid-cols-3 gap-2 sm:grid-cols-4">
        <div className="rounded-lg border bg-emerald-50 px-3 py-2 text-center">
          <div className="text-xl font-bold tabular-nums text-emerald-700">{summary.correct}</div>
          <div className="text-[11px] font-medium uppercase tracking-wide text-emerald-700/80">Correct</div>
        </div>
        <div className="rounded-lg border bg-rose-50 px-3 py-2 text-center">
          <div className="text-xl font-bold tabular-nums text-rose-700">{summary.wrong}</div>
          <div className="text-[11px] font-medium uppercase tracking-wide text-rose-700/80">Wrong</div>
        </div>
        <div className="rounded-lg border bg-muted px-3 py-2 text-center">
          <div className="text-xl font-bold tabular-nums text-muted-foreground">{summary.skipped}</div>
          <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Skipped</div>
        </div>
        <div className="rounded-lg border bg-primary/5 px-3 py-2 text-center">
          <div className="text-xl font-bold tabular-nums text-primary">{summary.scorePct}%</div>
          <div className="text-[11px] font-medium uppercase tracking-wide text-primary/80">Score</div>
        </div>
      </div>

      {/* By question type — the client-side stand-in for weak/strong areas */}
      {typeStats.length > 1 && (
        <div>
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            By question type
          </p>
          <div className="flex flex-col gap-2">
            {typeStats.map((s) => (
              <div key={s.type} className="flex items-center gap-3">
                <span className="w-28 shrink-0 truncate text-xs text-foreground">{typeLabel(s.type)}</span>
                <MiniBar value={s.correct} max={s.attempted || 1} tone={accuracyTone(s.accuracy)} className="flex-1" />
                <span className="w-16 shrink-0 text-right text-xs tabular-nums text-muted-foreground">
                  {s.correct}/{s.attempted || 0} · {s.accuracy}%
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Attempt quality — only when we have per-question timing */}
      {timed && (
        <div>
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            How you attempted
          </p>
          <div className="flex flex-wrap gap-1.5">
            {quality.perfect > 0 && <StatPill label="Perfect" value={quality.perfect} tone="emerald" />}
            {quality.overtime_correct > 0 && <StatPill label="Slow but right" value={quality.overtime_correct} tone="amber" />}
            {quality.too_fast_wrong > 0 && <StatPill label="Rushed (wrong)" value={quality.too_fast_wrong} tone="rose" />}
            {quality.overtime_wrong > 0 && <StatPill label="Struggled" value={quality.overtime_wrong} tone="rose" />}
            {quality.wrong_normal > 0 && <StatPill label="Wrong" value={quality.wrong_normal} tone="neutral" />}
            {quality.unattempted > 0 && <StatPill label="Skipped" value={quality.unattempted} tone="neutral" />}
          </div>
          {insights.length > 0 && (
            <ul className="mt-2 space-y-1">
              {insights.map((line, i) => (
                <li key={i} className="text-xs text-muted-foreground">• {line}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      {/* Time split */}
      {timed && buckets.totalSec > 0 && (
        <div>
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Where your time went
          </p>
          <div className="flex h-3 overflow-hidden rounded-full bg-muted">
            <div className="bg-emerald-500" style={{ width: `${(buckets.correctSec / buckets.totalSec) * 100}%` }} />
            <div className="bg-rose-500" style={{ width: `${(buckets.wrongSec / buckets.totalSec) * 100}%` }} />
            <div className="bg-muted-foreground/40" style={{ width: `${(buckets.skippedSec / buckets.totalSec) * 100}%` }} />
          </div>
          <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted-foreground">
            <span><span className="mr-1 inline-block h-2 w-2 rounded-full bg-emerald-500 align-middle" />Correct {fmtMinSec(buckets.correctSec)}</span>
            <span><span className="mr-1 inline-block h-2 w-2 rounded-full bg-rose-500 align-middle" />Wrong {fmtMinSec(buckets.wrongSec)}</span>
            <span><span className="mr-1 inline-block h-2 w-2 rounded-full bg-muted-foreground/40 align-middle" />Skipped {fmtMinSec(buckets.skippedSec)}</span>
          </div>
        </div>
      )}
    </div>
  );
}
