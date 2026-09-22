"use client";

import { DeferredAreaTrendChart } from "@/components/shared/deferred-area-trend-chart";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { ErrorCard } from "@/components/ui/error-card";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton, SkeletonStats } from "@/components/ui/skeleton";
import { QualityFinding } from "@/lib/api";
import { usePlatformAiMonitoring } from "@/lib/staff-queries";

const BRAND = "#15603d";

const TYPE_LABEL: Record<string, string> = {
  mcq_single: "Single choice",
  mcq_multi: "Multiple choice",
  true_false: "True / False",
  numerical: "Numerical",
  fill_blank: "Fill in the blank",
  matching: "Matching",
  unknown: "Unknown",
};
const FIELD_LABEL: Record<string, string> = {
  question_text: "Question wording",
  options: "Options",
  correct_answer: "Correct answer",
  explanation: "Explanation",
  difficulty: "Difficulty",
  marks: "Marks",
};

// Severity styling for the findings / recommendations layer.
const SEV: Record<
  QualityFinding["severity"],
  { label: string; color: string; chip: string }
> = {
  critical: { label: "Fix now", color: "#ff6b7a", chip: "bg-rose-100 text-rose-700" },
  warn: { label: "Improve", color: "#f5a623", chip: "bg-amber-100 text-amber-700" },
  good: { label: "Good", color: "#00a651", chip: "bg-emerald-100 text-emerald-700" },
  info: { label: "Note", color: "#6366f1", chip: "bg-indigo-100 text-indigo-700" },
};

function tone(pct: number) {
  return pct >= 70 ? "#00a651" : pct >= 40 ? "#f5a623" : "#ff6b7a";
}
function verdictText(pct: number) {
  return pct >= 80
    ? "Strong — teachers keep most questions as written."
    : pct >= 60
      ? "Decent — but teachers still fix a fair share."
      : "Needs work — teachers edit most questions before using them.";
}

function StatTile({
  label,
  value,
  color,
  hint,
}: {
  label: string;
  value: number | string;
  color?: string;
  hint?: string;
}) {
  return (
    <Card className="animate-rise">
      <CardContent className="p-5">
        <div className="text-[26px] font-bold leading-none" style={{ color }}>
          {value}
        </div>
        <div className="mt-2 text-[11px] font-semibold uppercase tracking-widest text-muted-foreground">
          {label}
        </div>
        {hint && <div className="mt-1 text-xs text-muted-foreground/80">{hint}</div>}
      </CardContent>
    </Card>
  );
}

function FindingCard({ f }: { f: QualityFinding }) {
  const s = SEV[f.severity];
  return (
    <div
      className="animate-rise rounded-xl border bg-card p-4 shadow-sm"
      style={{ borderLeft: `3px solid ${s.color}` }}
    >
      <div className="flex items-start justify-between gap-3">
        <p className="font-semibold text-foreground">{f.title}</p>
        <span
          className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] font-semibold ${s.chip}`}
        >
          {s.label}
        </span>
      </div>
      <p className="mt-1.5 text-sm text-muted-foreground">{f.detail}</p>
      <div className="mt-3 flex items-start gap-2 rounded-lg bg-muted px-3 py-2 text-sm">
        <span className="font-semibold text-primary">Do this</span>
        <span className="text-foreground">{f.action}</span>
      </div>
    </div>
  );
}

export default function QuestionQualityPage() {
  const { data: d = null, error, isValidating: loading, mutate } = usePlatformAiMonitoring();

  if (error) {
    return (
      <div className="flex flex-col gap-6">
        <PageHeader
          title="Question quality"
          description="Track AI question quality and improvements using real teacher reviews."
        />
        <ErrorCard message={error.message} onRetry={() => void mutate()} />
      </div>
    );
  }

  // First load: one coherent skeleton instead of real-looking 0/0% tiles.
  if (d === null) {
    return (
      <div className="flex flex-col gap-6">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div className="flex flex-col gap-2">
            <Skeleton className="h-8 w-64" />
            <Skeleton className="h-4 w-96 max-w-full" />
          </div>
          <Skeleton className="h-9 w-28 rounded-lg" />
        </div>
        <Skeleton className="h-40 w-full rounded-2xl" />
        <SkeletonStats />
        <Skeleton className="h-56 w-full rounded-2xl" />
      </div>
    );
  }

  const sig = d?.signals;
  const hasApproved = (sig?.approved ?? 0) > 0;
  const keptRate = sig?.kept_as_is_rate ?? 0;
  const trend = d?.trend;
  const findings = d?.findings ?? [];

  // Quality-by-type bars, sorted weakest-first so the to-do list is obvious.
  const typeBars = (
    (sig?.by_type?.length ?? 0) > 0
      ? (sig?.by_type ?? []).map((t) => ({
          key: t.type,
          pct: t.kept_rate,
          right: `${t.kept_rate}% kept · ${t.kept_as_is}/${t.approved}`,
        }))
      : (d?.by_type ?? []).map((t) => ({
          key: t.type,
          pct: t.approval,
          right: `${t.approval}% · ${t.approved}/${t.total}`,
        }))
  ).sort((a, b) => a.pct - b.pct);

  const updated = d?.updated_at ? new Date(d.updated_at) : null;
  const maxFunnel = Math.max(1, ...(d?.funnel ?? []).map((s) => s.count));

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Question quality"
        description="Track AI question quality and improvements using real teacher reviews."
        actions={
          <div className="flex items-center gap-3">
            {updated && (
              <span className="text-xs text-muted-foreground">
                Updated{" "}
                {updated.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
              </span>
            )}
            <button
              onClick={() => void mutate()}
              disabled={loading}
              className="rounded-lg border border-input bg-card px-3 py-1.5 text-sm font-medium text-foreground shadow-sm transition-colors hover:bg-accent disabled:opacity-60"
            >
              {loading ? "Refreshing…" : "Refresh"}
            </button>
          </div>
        }
      />

      {/* Verdict hero */}
      <div className="animate-rise relative overflow-hidden rounded-2xl bg-gradient-to-br from-[#1a6942] via-[#15603d] to-[#0f4e33] p-6 text-white shadow-lg sm:p-8">
        <div className="pointer-events-none absolute -right-8 -top-10 h-40 w-40 rounded-full bg-white/10 blur-2xl" />
        <div className="relative flex flex-wrap items-center justify-between gap-6">
          <div className="min-w-0">
            <p className="text-[11px] font-semibold uppercase tracking-widest text-white/70">
              AI quality verdict
            </p>
            {hasApproved ? (
              <>
                <h2 className="mt-2 text-2xl font-bold leading-tight sm:text-[28px]">
                  <span className="text-[#9ff0a6]">{keptRate}%</span> of approved
                  questions were kept exactly as the AI wrote them.
                </h2>
                <p className="mt-2 text-sm text-white/80">
                  {verdictText(keptRate)}
                  {sig?.measured_from ? ` · measured since ${sig.measured_from}` : ""}
                </p>
                {trend?.has_trend &&
                  trend.approved_last7 + trend.approved_prev7 >= 4 && (
                    <p className="mt-3 inline-flex items-center gap-1.5 rounded-full bg-white/10 px-3 py-1 text-xs font-medium">
                      {trend.keep_rate_delta >= 0 ? (
                        <span className="text-[#9ff0a6]">
                          ↑ +{trend.keep_rate_delta} pts vs last week
                        </span>
                      ) : (
                        <span className="text-[#ffb4bc]">
                          ↓ {trend.keep_rate_delta} pts vs last week
                        </span>
                      )}
                      <span className="text-white/60">
                        ({trend.keep_rate_prev7}% → {trend.keep_rate_last7}%)
                      </span>
                    </p>
                  )}
              </>
            ) : (
              <>
                <h2 className="mt-2 text-2xl font-bold leading-tight sm:text-[28px]">
                  Measuring quality…
                </h2>
                <p className="mt-2 max-w-xl text-sm text-white/80">
                  Approve or edit some AI questions and this will show how often the
                  AI is good enough to keep as-is. All-time approval rate so far:{" "}
                  <span className="font-semibold text-[#9ff0a6]">
                    {d?.approval_rate ?? 0}%
                  </span>
                  .
                </p>
              </>
            )}
          </div>
          {hasApproved && (
            <div
              className="relative flex h-28 w-28 shrink-0 items-center justify-center rounded-full transition-all duration-700 ease-out"
              style={{
                background: `conic-gradient(#7ae582 ${keptRate * 3.6}deg, rgba(255,255,255,0.16) 0deg)`,
              }}
            >
              <div className="flex h-[94px] w-[94px] flex-col items-center justify-center rounded-full bg-[#15603d]">
                <span className="text-3xl font-bold">{keptRate}%</span>
                <span className="text-[10px] uppercase tracking-widest text-white/70">
                  kept as-is
                </span>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Quick stats */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatTile label="AI questions generated" value={d?.total_generated ?? 0} />
        <StatTile
          label="Approval rate"
          value={`${d?.approval_rate ?? 0}%`}
          color={tone(d?.approval_rate ?? 0)}
        />
        <StatTile label="Quizzes published" value={d?.published_quizzes ?? 0} />
        <StatTile
          label="Generation failures (14d)"
          value={d?.failures_14d ?? 0}
          color={(d?.failures_14d ?? 0) > 0 ? "#ff6b7a" : undefined}
        />
      </div>

      {/* Key findings & recommendations — the decision layer */}
      <Card className="animate-rise">
        <CardHeader>
          <CardTitle>Key findings &amp; what to do</CardTitle>
          <CardDescription>
            The important signals turned into decisions. Work top to bottom — the
            most urgent items come first.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {findings.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Nothing to flag yet — generate and review some AI questions and the
              findings will appear here.
            </p>
          ) : (
            <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
              {findings.map((f, i) => (
                <FindingCard key={i} f={f} />
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Quality funnel */}
      <Card className="animate-rise">
        <CardHeader>
          <CardTitle>Quality funnel</CardTitle>
          <CardDescription>
            Where questions drop off between generation and being kept as-is.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          {(d?.funnel ?? []).map((st, i) => {
            const prev = i > 0 ? d!.funnel[i - 1].count : st.count;
            const pctOfPrev = prev > 0 ? Math.round((st.count / prev) * 100) : 0;
            return (
              <div key={st.stage} className="flex items-center gap-3">
                <span className="w-28 shrink-0 text-sm text-muted-foreground">
                  {st.stage}
                </span>
                <div className="h-7 flex-1 overflow-hidden rounded-md bg-muted">
                  <div
                    className="flex h-full items-center rounded-md bg-primary/85 px-2 text-xs font-semibold text-white transition-[width] duration-700 ease-out"
                    style={{ width: `${Math.max(6, (st.count / maxFunnel) * 100)}%` }}
                  >
                    {st.count}
                  </div>
                </div>
                <span className="w-16 shrink-0 text-right text-xs text-muted-foreground">
                  {i === 0 ? "—" : `${pctOfPrev}% kept`}
                </span>
              </div>
            );
          })}
        </CardContent>
      </Card>

      {/* Weak spots by type + what teachers fix */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <Card className="animate-rise lg:col-span-2">
          <CardHeader>
            <CardTitle>Weakest question types</CardTitle>
            <CardDescription>
              {(sig?.by_type?.length ?? 0) > 0
                ? "Kept-as-is rate by type (weakest first) — low bars are where the AI needs work."
                : "Approval rate by type (weakest first) — richer once teachers review new questions."}
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            {typeBars.length === 0 ? (
              <p className="text-sm text-muted-foreground">No question data yet.</p>
            ) : (
              typeBars.map((t) => (
                <div key={t.key} className="flex flex-col gap-1">
                  <div className="flex items-center justify-between gap-3 text-sm">
                    <span className="text-foreground">
                      {TYPE_LABEL[t.key] ?? t.key}
                    </span>
                    <span className="text-muted-foreground">{t.right}</span>
                  </div>
                  <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
                    <div
                      className="h-full rounded-full transition-[width] duration-700 ease-out"
                      style={{ width: `${t.pct}%`, background: tone(t.pct) }}
                    />
                  </div>
                </div>
              ))
            )}
          </CardContent>
        </Card>

        <Card className="animate-rise lg:col-span-1" style={{ animationDelay: "60ms" }}>
          <CardHeader>
            <CardTitle>What teachers fix most</CardTitle>
            <CardDescription>Which part of a question gets edited.</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            {(sig?.most_edited_fields?.length ?? 0) === 0 ? (
              <p className="text-sm text-muted-foreground">
                No edits recorded yet — this reveals what to improve in the prompts
                (e.g. options, correct answer).
              </p>
            ) : (
              sig!.most_edited_fields.map((f) => (
                <div
                  key={f.field}
                  className="flex items-center justify-between rounded-lg border p-3 text-sm"
                >
                  <span className="text-foreground">
                    {FIELD_LABEL[f.field] ?? f.field}
                  </span>
                  <span className="font-semibold text-muted-foreground">
                    {f.count} edit{f.count === 1 ? "" : "s"}
                  </span>
                </div>
              ))
            )}
          </CardContent>
        </Card>
      </div>

      {/* Quality by difficulty */}
      <Card className="animate-rise">
        <CardHeader>
          <CardTitle>Quality by difficulty</CardTitle>
          <CardDescription>
            Approval rate across easy / medium / hard — spot which level the AI
            handles worst.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          {(d?.difficulty_quality?.length ?? 0) === 0 ? (
            <p className="text-sm text-muted-foreground">No difficulty data yet.</p>
          ) : (
            d!.difficulty_quality.map((x) => (
              <div key={x.difficulty} className="flex flex-col gap-1">
                <div className="flex items-center justify-between gap-3 text-sm">
                  <span className="capitalize text-foreground">{x.difficulty}</span>
                  <span className="text-muted-foreground">
                    {x.approval}% · {x.approved}/{x.total}
                  </span>
                </div>
                <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
                  <div
                    className="h-full rounded-full transition-[width] duration-700 ease-out"
                    style={{ width: `${x.approval}%`, background: tone(x.approval) }}
                  />
                </div>
              </div>
            ))
          )}
        </CardContent>
      </Card>

      {/* Generation volume */}
      <Card className="animate-rise">
        <CardHeader>
          <CardTitle>Generation volume</CardTitle>
          <CardDescription>AI questions generated per day, last 14 days.</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="h-56">
            <DeferredAreaTrendChart
              data={d?.volume ?? []}
              xKey="date"
              yKey="generated"
              color={BRAND}
              gradientId="platformGenerationVolumeFill"
            />
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
