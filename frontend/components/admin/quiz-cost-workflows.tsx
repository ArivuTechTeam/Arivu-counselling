"use client";

import { useState } from "react";
import useSWR from "swr";
import { ErrorCard } from "@/components/ui/error-card";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiCallLog, ApiLogFilters, QuizCostSummary, listApiLogs, listQuizCostWorkflows } from "@/lib/api";
import { callStage } from "@/lib/api-log-display";

const usd = (value: number | null) => value === null ? "Not priced" : `US$${value.toFixed(5)}`;
const inr = (value: number | null, rate: number) => value === null ? "Not priced"
  : new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 4 }).format(value * rate);
const date = (value: string) => new Date(value).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" });

function Calls({ group, filters, onView }: {
  group: QuizCostSummary; filters: ApiLogFilters; onView: (call: ApiCallLog) => void;
}) {
  const [page, setPage] = useState(1);
  const callFilters: ApiLogFilters = {
    provider: filters.provider, status: filters.status,
    date_from: filters.date_from, date_to: filters.date_to,
    tenant_id: group.tenant_id ?? undefined, platform_only: !group.tenant_id,
    workflow_id: group.workflow_id ?? undefined,
    document_id: group.workflow_id ? undefined : group.document_id ?? undefined,
    legacy_only: !group.workflow_id, unlinked_only: group.kind === "unlinked",
    call_type: group.kind === "unlinked" ? group.stages[0]?.call_type : undefined,
    page, page_size: 50,
  };
  const { data, error, isLoading, mutate } = useSWR(["quiz-cost-calls", callFilters], () => listApiLogs(callFilters));
  if (error) return <ErrorCard message={error.message} onRetry={() => void mutate()} />;
  if (isLoading) return <Skeleton className="h-24 w-full" />;
  return <div className="border-t p-4">
    <div className="overflow-x-auto">
      <table className="w-full min-w-[650px] text-left text-sm">
        <thead><tr>{["Stage", "Provider / model", "Tokens in / out", "USD", "Result", "Details"].map(label =>
          <th key={label} className="p-2 text-xs text-muted-foreground">{label}</th>)}</tr></thead>
        <tbody>{data?.items.map(call => <tr key={call.id} className="border-t">
          <td className="p-2">{callStage(call.call_type)}</td>
          <td className="p-2">{call.model}<span className="block text-xs text-muted-foreground">{call.provider}{call.was_fallback ? " · fallback" : ""}</span></td>
          <td className="p-2">{call.input_tokens ?? "—"} / {call.output_tokens ?? "—"}</td>
          <td className="p-2">{usd(call.cost_usd)}</td><td className="p-2">{call.status}</td>
          <td className="p-2"><button onClick={() => onView(call)} className="text-primary underline">View</button></td>
        </tr>)}</tbody>
      </table>
    </div>
    <div className="mt-3 flex items-center justify-between text-sm">
      <span>{data?.total ?? 0} matching calls · page {page}</span>
      <div className="flex gap-2"><button disabled={page === 1} onClick={() => setPage(page - 1)} className="rounded border px-3 py-1 disabled:opacity-40">Previous</button>
        <button disabled={page * 50 >= (data?.total ?? 0)} onClick={() => setPage(page + 1)} className="rounded border px-3 py-1 disabled:opacity-40">Next</button></div>
    </div>
  </div>;
}

export function QuizCostWorkflows({ filters, inrPerUsd, onView }: {
  filters: ApiLogFilters; inrPerUsd: number; onView: (call: ApiCallLog) => void;
}) {
  const [page, setPage] = useState(1);
  const [kind, setKind] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const query = { ...filters, page, page_size: 20, kind: kind || undefined };
  const { data, error, isLoading, mutate } = useSWR(["quiz-cost-workflows", query], () => listQuizCostWorkflows(query), {
    refreshInterval: 15000,
  });
  return <div className="space-y-4">
    <div className="rounded-2xl border bg-card p-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div><h2 className="text-lg font-semibold">Cost per quiz run</h2>
          <p className="mt-1 text-sm text-muted-foreground">Each new generation/import is separate, even when it uses the same paper. Retries and provider fallbacks are included.</p></div>
        <label className="text-sm">Show<select value={kind} onChange={event => { setKind(event.target.value); setPage(1); setOpen(null); }}
          className="ml-2 rounded-md border bg-background px-3 py-2">
          <option value="">All recorded activity</option><option value="generation">Quiz generation runs</option>
          <option value="extraction">Quiz import runs</option><option value="legacy">Legacy / unattributed calls</option>
        </select></label>
      </div>
      <p className="mt-2 text-xs text-muted-foreground">Totals include all matching calls across every page, not just the displayed rows. Date, provider and result filters narrow the costs. Topic analysis and later review edits are separate from generation runs. Costs are estimates from recorded usage, not a provider invoice.</p>
      {data && <div className="mt-4 grid gap-3 sm:grid-cols-3">
        {[["Matching groups", String(data.total)], ["Recorded calls", String(data.call_count)],
          ["Filtered cost", `${usd(data.cost_usd)} / ${inr(data.cost_usd, inrPerUsd)}`]].map(([label, value]) =>
          <div key={label} className="rounded-xl bg-muted/40 p-3"><p className="text-xs text-muted-foreground">{label}</p><p className="mt-1 text-xl font-semibold">{value}</p></div>)}
      </div>}
      {!!data?.unpriced_calls && <p className="mt-3 text-sm text-amber-700">{data.unpriced_calls} calls have no price estimate. Totals are incomplete.</p>}
    </div>
    {error && <div className="space-y-2"><ErrorCard message={error.message} onRetry={() => void mutate()} />
      <p className="text-sm text-muted-foreground">This view needs migration 73 and the updated backend. If you have applied it, check the database connection and restart the local backend.</p></div>}
    {isLoading && <Skeleton className="h-36 w-full" />}
    {data?.items.map(group => <section key={group.group_key} className="overflow-hidden rounded-2xl border bg-card">
      <button onClick={() => setOpen(open === group.group_key ? null : group.group_key)} aria-expanded={open === group.group_key}
        className="w-full p-5 text-left hover:bg-muted/30">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            {group.quiz_title && <p className="mb-1 break-words text-lg font-semibold">{group.quiz_title}</p>}
            <h3 className="font-semibold">{group.kind === "generation" ? "Quiz generation" : group.kind === "extraction" ? "Quiz import"
              : group.kind === "legacy" ? "Legacy paper activity — not a single quiz" : "Unattributed activity"}
              {group.workflow_id && <span className="ml-2 font-mono text-sm">#{group.workflow_id.slice(0, 8)}</span>}
            </h3>
            <p className="mt-1 text-sm text-muted-foreground">{date(group.started_at)} IST · {group.status} · {group.call_count} calls{group.error_count ? ` · ${group.error_count} errors` : ""}</p>
            {group.quiz_set_id && <p className="mt-1 break-all text-xs text-muted-foreground">Quiz ID: {group.quiz_set_id}</p>}
            {group.document_id && <p className="mt-1 break-all text-xs text-muted-foreground">Paper ID: {group.document_id}</p>}
          </div>
          <div className="text-right"><p className="text-xs text-muted-foreground">Recorded cost {group.unpriced_calls ? "(incomplete)" : ""}</p>
            <p className="mt-1 text-xl font-semibold text-primary">{inr(group.cost_usd, inrPerUsd)}</p>
            <p className="text-sm text-muted-foreground">{usd(group.cost_usd)} · {open === group.group_key ? "Hide calls ↑" : "Show calls ↓"}</p>
          </div>
        </div>
        <div className="mt-3 flex flex-wrap gap-2">{group.stages.map(stage => <span key={stage.call_type} className="rounded-lg border bg-muted/20 px-3 py-2 text-xs">
          {callStage(stage.call_type)} ×{stage.calls}<span className="ml-2 font-semibold">{inr(stage.cost_usd, inrPerUsd)}</span>
        </span>)}</div>
        <p className="mt-3 text-xs text-muted-foreground">Tokens: {group.input_tokens.toLocaleString()} in · {group.output_tokens.toLocaleString()} out · {group.thinking_tokens.toLocaleString()} thinking · {group.cached_tokens.toLocaleString()} cached</p>
        {!group.workflow_id && <p className="mt-2 text-xs text-amber-700">Older calls have no generation-run ID. We cannot reliably split them by quiz; this is a historical activity total.</p>}
      </button>
      {open === group.group_key && <Calls group={group} filters={filters} onView={onView} />}
    </section>)}
    {data && !data.items.length && <p className="rounded-2xl border bg-card p-8 text-center text-sm text-muted-foreground">No matching cost runs. Older calls appear under All recorded activity or Legacy.</p>}
    {data && <div className="flex items-center justify-between text-sm"><span>Page {page} · {data.total} groups</span>
      <div className="flex gap-2"><button disabled={page === 1} onClick={() => { setPage(page - 1); setOpen(null); }} className="rounded border px-3 py-1 disabled:opacity-40">Previous</button>
        <button disabled={page * 20 >= data.total} onClick={() => { setPage(page + 1); setOpen(null); }} className="rounded border px-3 py-1 disabled:opacity-40">Next</button></div></div>}
  </div>;
}
