// Shared "reconciliation" primitives for building quizzes to a target.
//
// <AllocationMeter> is the sticky target-vs-allocated-vs-remaining bar the
// teacher keeps in view while distributing questions across topics — the exact
// "I lost track of how many I've assigned" fix. <StatPill> and <MiniBar> are
// small building blocks reused across the meter (and later analytics surfaces).

export function MiniBar({
  value,
  max,
  tone = "primary",
  className = "",
}: {
  value: number;
  max: number;
  tone?: "primary" | "amber" | "rose" | "emerald";
  className?: string;
}) {
  const pct = max > 0 ? Math.min(100, Math.round((value / max) * 100)) : 0;
  const fill = {
    primary: "bg-primary",
    amber: "bg-amber-500",
    rose: "bg-rose-500",
    emerald: "bg-emerald-500",
  }[tone];
  return (
    <div className={`h-1.5 w-full overflow-hidden rounded-full bg-muted ${className}`}>
      <div
        className={`h-full rounded-full transition-all duration-300 ${fill}`}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

export function StatPill({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: string | number;
  tone?: "neutral" | "primary" | "amber" | "rose" | "emerald";
}) {
  const tones = {
    neutral: "border-border bg-muted text-muted-foreground",
    primary: "border-primary/30 bg-primary/10 text-primary",
    amber: "border-amber-300 bg-amber-50 text-amber-800",
    rose: "border-rose-300 bg-rose-50 text-rose-700",
    emerald: "border-emerald-300 bg-emerald-50 text-emerald-700",
  }[tone];
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs font-semibold ${tones}`}
    >
      {label}
      <span className="tabular-nums">{value}</span>
    </span>
  );
}

/**
 * Live allocation meter: shows how many questions have been assigned against the
 * target, what's left, and the per-type breakdown — designed to sit `sticky` at
 * the top of the topic list so it never scrolls out of view.
 */
export function AllocationMeter({
  allocated,
  target,
  byType = [],
}: {
  allocated: number;
  target: number;
  byType?: { label: string; count: number }[];
}) {
  const remaining = target - allocated;
  const state = remaining === 0 ? "done" : remaining > 0 ? "under" : "over";
  const tone = state === "done" ? "emerald" : state === "under" ? "amber" : "rose";
  const barTone = state === "done" ? "emerald" : state === "over" ? "rose" : "primary";

  const message =
    state === "done"
      ? "All questions assigned — you're ready to generate."
      : state === "under"
        ? allocated === 0
          ? "Assign questions to your selected topics below."
          : `${remaining} more to assign`
        : `${-remaining} too many — remove some below`;

  const ring = {
    done: "border-emerald-300 bg-emerald-50",
    under: "border-amber-200 bg-amber-50/60",
    over: "border-rose-300 bg-rose-50",
  }[state];

  return (
    <div className={`rounded-xl border p-3 shadow-sm ${ring}`}>
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
        <div className="flex items-baseline gap-2">
          <span className="text-sm font-semibold text-foreground">Assigned</span>
          <span className="text-lg font-bold tabular-nums text-foreground">
            {allocated}
            <span className="text-sm font-medium text-muted-foreground"> / {target}</span>
          </span>
        </div>
        <StatPill
          label={state === "over" ? "Over by" : state === "done" ? "Complete" : "Remaining"}
          value={state === "done" ? "✓" : Math.abs(remaining)}
          tone={tone}
        />
      </div>
      <MiniBar value={allocated} max={target} tone={barTone} className="mt-2" />
      <p
        className={`mt-1.5 text-xs font-medium ${
          state === "done"
            ? "text-emerald-700"
            : state === "over"
              ? "text-rose-700"
              : "text-amber-700"
        }`}
      >
        {message}
      </p>
      {byType.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5 border-t border-black/5 pt-2">
          {byType.map((t) => (
            <StatPill key={t.label} label={t.label} value={t.count} tone="neutral" />
          ))}
        </div>
      )}
    </div>
  );
}
