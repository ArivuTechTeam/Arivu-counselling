import { InstitutionAnalytics } from "@/lib/api";

type Trend = InstitutionAnalytics["trend"];

export function TrendWidget({
  trend,
  activeStudents,
}: {
  trend: Trend;
  activeStudents: number;
}) {
  const up = trend.delta >= 0;
  const direction = trend.delta === 0 ? "Steady" : up ? "Engagement up" : "Engagement down";
  const max = Math.max(1, trend.attempts_last7, trend.attempts_prev7);

  return (
    <div className="rounded-xl border bg-secondary/25 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Weekly comparison
          </p>
          <p className={`mt-1 text-lg font-bold ${up ? "text-emerald-700" : "text-rose-700"}`}>
            {trend.delta === 0 ? "→" : up ? "↑" : "↓"} {direction}
            {trend.has_trend && ` ${Math.abs(trend.percentage_change)}%`}
          </p>
        </div>
        <p className="text-sm text-muted-foreground">
          {activeStudents} active student{activeStudents === 1 ? "" : "s"}
        </p>
      </div>

      <div className="mt-4 space-y-3">
        {[
          ["Last 7 days", trend.attempts_last7, "bg-emerald-600"],
          ["Previous 7 days", trend.attempts_prev7, "bg-slate-400"],
        ].map(([label, value, color]) => (
          <div
            key={String(label)}
            className="grid grid-cols-[108px_1fr_auto] items-center gap-3 text-xs"
          >
            <span className="text-muted-foreground">{label}</span>
            <span className="h-2 overflow-hidden rounded-full bg-muted">
              <span
                className={`block h-full rounded-full ${color}`}
                style={{ width: `${(Number(value) / max) * 100}%` }}
              />
            </span>
            <strong>{value}</strong>
          </div>
        ))}
      </div>
    </div>
  );
}
