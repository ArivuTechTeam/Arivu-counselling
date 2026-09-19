"use client";

import { useMemo, useState } from "react";
import useSWR from "swr";

import { ErrorCard } from "@/components/ui/error-card";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton, SkeletonStats } from "@/components/ui/skeleton";
import {
  ApiCallLog,
  ApiCallLogPage,
  ApiLogFilters,
  getApiLog,
  listApiLogs,
} from "@/lib/api";

const money = (value: number | null, currency: "USD" | "INR") =>
  value === null ? "—" : new Intl.NumberFormat("en-IN", {
    style: "currency", currency, maximumFractionDigits: currency === "USD" ? 5 : 2,
  }).format(value);
const number = (value: number | null) => value?.toLocaleString() ?? "—";
const compactNumber = (value: number) => new Intl.NumberFormat("en-IN", {
  notation: "compact",
  maximumFractionDigits: 1,
}).format(value);
const localDateTime = (value: string) => new Intl.DateTimeFormat("en-IN", {
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
  timeZoneName: "short",
}).format(new Date(value));
const callStage = (callType: string) => ({
  document_profile: "Extraction — document profiling",
  topic_extraction: "Extraction — topic identification",
  topic_extraction_map: "Extraction — topic mapping",
  topic_extraction_reduce: "Extraction — topic consolidation",
  quiz_extraction: "Extraction — quiz questions",
  quiz_generation: "Quiz generation",
  blueprint_generation: "Quiz generation",
  question_verification: "Question verification",
  question_regeneration: "Question regeneration",
  question_explain: "Student explanation",
  unclassified: "Needs attribution (older call)",
}[callType] ?? callType.replaceAll("_", " "));

function JsonTree({ value, depth = 0 }: { value: unknown; depth?: number }) {
  if (value === null) return <span className="text-rose-600">null</span>;
  if (typeof value === "string") return <span className="break-all text-emerald-700">&quot;{value}&quot;</span>;
  if (typeof value === "number" || typeof value === "boolean") return <span className="text-indigo-700">{String(value)}</span>;
  if (!value || typeof value !== "object") return <span>{String(value)}</span>;
  const entries = Array.isArray(value) ? value.map((item, index) => [String(index), item]) : Object.entries(value);
  return (
    <details open={depth < 1} className="group rounded-md" >
      <summary className="cursor-pointer select-none text-xs font-medium text-muted-foreground">
        {Array.isArray(value) ? `Array (${entries.length})` : `Object (${entries.length})`}
      </summary>
      <div className="ml-3 border-l border-input pl-3 font-mono text-xs leading-5">
        {entries.map(([key, child]) => (
          <div key={key} className="py-0.5">
            <span className="text-primary">{key}</span><span className="text-muted-foreground">: </span>
            <JsonTree value={child} depth={depth + 1} />
          </div>
        ))}
      </div>
    </details>
  );
}

function LogDetail({ id, inrPerUsd, onClose }: { id: string; inrPerUsd: number; onClose: () => void }) {
  const { data, error } = useSWR(["api-log", id], () => getApiLog(id));
  return (
    <aside className="fixed inset-y-0 right-0 z-40 w-full max-w-2xl overflow-y-auto border-l bg-card p-5 shadow-2xl sm:p-6" aria-label="API call detail">
      <div className="mb-5 flex items-start justify-between gap-4">
        <div><p className="text-lg font-semibold">API call detail</p><p className="mt-1 text-sm text-muted-foreground">Raw provider payloads are visible only to super admins.</p></div>
        <button onClick={onClose} className="rounded-lg border border-input px-3 py-1.5 text-sm hover:bg-accent">Close</button>
      </div>
      {error && <ErrorCard message={error.message} />}
      {!data && !error && <Skeleton className="h-80 w-full" />}
      {data && <div className="space-y-5">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {[['Input', number(data.input_tokens)], ['Output', number(data.output_tokens)], ['USD', money(data.cost_usd, 'USD')], ['INR', money(data.cost_usd === null ? null : data.cost_usd * inrPerUsd, 'INR')]].map(([label, value]) => <div key={label} className="rounded-xl border bg-muted/30 p-3"><p className="text-xs text-muted-foreground">{label}</p><p className="mt-1 font-semibold">{value}</p></div>)}
        </div>
        <div className="rounded-xl border bg-muted/30 p-4 text-sm"><span className="font-medium">{data.provider} / {data.model}</span><span className="mx-2 text-muted-foreground">·</span>{data.call_type}<span className="mx-2 text-muted-foreground">·</span>{data.latency_ms} ms</div>
        <section className="rounded-xl border p-4"><h2 className="mb-3 font-semibold">Raw request</h2><JsonTree value={data.raw_request} /></section>
        <section className="rounded-xl border p-4"><h2 className="mb-3 font-semibold">Raw response</h2><JsonTree value={data.raw_response} /></section>
      </div>}
    </aside>
  );
}

function CallRows({
  calls,
  inrPerUsd,
  onView,
}: {
  calls: ApiCallLog[];
  inrPerUsd: number;
  onView: (id: string) => void;
}) {
  return <table className="w-full min-w-[1100px] text-left text-sm">
    <thead className="bg-muted/50 text-xs uppercase tracking-wide text-muted-foreground">
      <tr>{["Time (IST)", "Stage", "Model", "Routing", "In", "Out", "Thinking", "Cached", "Cost", "Result", ""].map(x => <th key={x} className="px-4 py-3 font-medium">{x}</th>)}</tr>
    </thead>
    <tbody>{calls.map(item => <tr key={item.id} className="border-t hover:bg-background/60">
      <td className="px-4 py-3 whitespace-nowrap text-xs">{localDateTime(item.created_at)}</td>
      <td className="px-4 py-3"><span className="inline-flex rounded-full bg-emerald-100 px-2.5 py-1 text-xs font-medium text-emerald-800">{callStage(item.call_type)}</span></td>
      <td className="px-4 py-3"><span className="font-medium">{item.model}</span><span className="mt-0.5 block text-xs text-muted-foreground">{item.provider}</span></td>
      <td className="px-4 py-3"><span className={`rounded-full px-2 py-1 text-xs ${item.was_fallback ? "bg-amber-100 text-amber-800" : "bg-slate-100 text-slate-700"}`}>{item.was_fallback ? "Fallback" : "Primary"}</span></td>
      <td className="px-4 py-3 tabular-nums">{number(item.input_tokens)}</td>
      <td className="px-4 py-3 tabular-nums">{number(item.output_tokens)}</td>
      <td className="px-4 py-3 tabular-nums">{number(item.thinking_tokens)}</td>
      <td className="px-4 py-3 tabular-nums">{number(item.cached_tokens)}</td>
      <td className="px-4 py-3 whitespace-nowrap tabular-nums"><span>{money(item.cost_usd, "USD")}</span><span className="mt-0.5 block text-xs text-emerald-700">{money(item.cost_usd === null ? null : item.cost_usd * inrPerUsd, "INR")}</span></td>
      <td className="px-4 py-3"><span className={`rounded-full px-2 py-1 text-xs ${item.status === "success" ? "bg-emerald-100 text-emerald-700" : "bg-rose-100 text-rose-700"}`}>{item.status === "success" ? "OK" : "Error"}</span></td>
      <td className="px-4 py-3"><button onClick={() => onView(item.id)} className="text-primary hover:underline">View</button></td>
    </tr>)}</tbody>
  </table>;
}

function Pagination({ data, filters, setFilters }: {
  data: ApiCallLogPage | undefined;
  filters: ApiLogFilters;
  setFilters: (filters: ApiLogFilters) => void;
}) {
  const page = filters.page ?? 1;
  const pageSize = filters.page_size ?? 50;
  return <div className="flex items-center justify-between rounded-2xl border bg-card p-4 text-sm shadow-sm"><span>{data?.total ?? 0} total calls</span><div className="flex gap-2"><button disabled={page <= 1} onClick={() => setFilters({ ...filters, page: page - 1 })} className="rounded border px-3 py-1 disabled:opacity-40">Previous</button><button disabled={page * pageSize >= (data?.total ?? 0)} onClick={() => setFilters({ ...filters, page: page + 1 })} className="rounded border px-3 py-1 disabled:opacity-40">Next</button></div></div>;
}

export default function ApiLogsPage() {
  const [filters, setFilters] = useState<ApiLogFilters>({ page: 1, page_size: 50 });
  const [draft, setDraft] = useState<ApiLogFilters>({});
  const [grouped, setGrouped] = useState(true);
  const [collapsedGroups, setCollapsedGroups] = useState<Record<string, boolean>>({});
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [inrPerUsdInput, setInrPerUsdInput] = useState("83");
  const { data, error, isLoading } = useSWR(["api-logs", filters], () => listApiLogs(filters));
  const groups = useMemo(() => {
    const rows = new Map<string, ApiCallLog[]>();
    for (const item of data?.items ?? []) {
      const key = item.document_id ?? `unlinked:${item.job_id ?? item.id}`;
      rows.set(key, [...(rows.get(key) ?? []), item]);
    }
    return Array.from(rows.entries());
  }, [data]);
  const apply = () => setFilters({
    ...draft,
    // Browser date inputs have no timezone. Send an explicit inclusive UTC
    // range so selecting a day includes every call made on that day.
    date_from: draft.date_from ? `${draft.date_from}T00:00:00.000Z` : undefined,
    date_to: draft.date_to ? `${draft.date_to}T23:59:59.999Z` : undefined,
    page: 1,
    page_size: 50,
  });

  if (error) return <div className="flex flex-col gap-6"><PageHeader title="AI API logs" description="Every raw Gemini and DeepSeek provider response, restricted to super admins." /><ErrorCard message={error.message} onRetry={() => apply()} /></div>;
  if (isLoading && !data) return <div className="space-y-6"><Skeleton className="h-16 w-96 max-w-full" /><SkeletonStats /><Skeleton className="h-96 w-full" /></div>;
  const items = data?.items ?? [];
  const totalUsd = items.reduce((sum, item) => sum + (item.cost_usd ?? 0), 0);
  const parsedInrPerUsd = Number(inrPerUsdInput);
  const hasValidInrRate = Number.isFinite(parsedInrPerUsd) && parsedInrPerUsd > 0;
  const inrPerUsd = hasValidInrRate ? parsedInrPerUsd : 83;
  const inrFromUsd = (usd: number | null) => usd === null ? null : usd * inrPerUsd;
  const totalInr = totalUsd * inrPerUsd;
  return <div className="space-y-6">
    <PageHeader title="AI API logs" description="Inspect every raw provider response, usage tokens, latency, and estimated cost." actions={<button onClick={() => apply()} className="rounded-lg border border-input bg-card px-3 py-2 text-sm font-medium hover:bg-accent">Refresh</button>} />
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {[['Calls on this page', String(items.length)], ['Estimated USD', money(totalUsd, 'USD')], ['Estimated INR', money(totalInr, 'INR')], ['Errors', String(items.filter(i => i.status === 'error').length)]].map(([label, value]) => <div key={label} className="rounded-2xl border bg-card p-5 shadow-sm"><p className="text-2xl font-bold text-primary">{value}</p><p className="mt-2 text-[11px] font-semibold uppercase tracking-widest text-muted-foreground">{label}</p></div>)}
    </div>
    <div className="rounded-2xl border bg-card p-4 shadow-sm">
      <div className="mb-4 flex flex-col gap-2 rounded-xl border border-dashed bg-muted/20 p-3 sm:flex-row sm:items-end sm:justify-between">
        <div><p className="text-sm font-semibold">INR conversion rate</p><p className="text-xs text-muted-foreground">Enter the current rupees value for one US dollar. INR estimates update immediately for this view.</p></div>
        <label className="text-xs font-medium">₹ per US$<input type="number" min="0.01" step="0.01" inputMode="decimal" value={inrPerUsdInput} onChange={e => setInrPerUsdInput(e.target.value)} className="mt-1 block h-9 w-36 rounded-md border border-input bg-background px-2 text-sm" /></label>
      </div>
      {!hasValidInrRate && <p className="mb-3 text-xs text-rose-600">Enter a positive conversion rate. Using ₹83.00 per US$ until it is corrected.</p>}
      <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
        {([['tenant_id', 'Tenant ID'], ['document_id', 'Document ID'], ['call_type', 'Call type']] as const).map(([key, label]) => <label key={key} className="text-xs font-medium">{label}<input value={(draft[key] as string) ?? ''} onChange={e => setDraft({ ...draft, [key]: e.target.value })} className="mt-1 h-9 w-full rounded-md border border-input bg-background px-2 text-sm" /></label>)}
        <label className="text-xs font-medium">Provider<select value={draft.provider ?? ''} onChange={e => setDraft({ ...draft, provider: e.target.value })} className="mt-1 h-9 w-full rounded-md border border-input bg-background px-2 text-sm"><option value="">All</option><option value="gemini">Gemini</option><option value="deepseek">DeepSeek</option></select></label>
        <label className="text-xs font-medium">Status<select value={draft.status ?? ''} onChange={e => setDraft({ ...draft, status: e.target.value })} className="mt-1 h-9 w-full rounded-md border border-input bg-background px-2 text-sm"><option value="">All</option><option value="success">Success</option><option value="error">Error</option></select></label>
        <label className="text-xs font-medium">From date<input type="date" value={draft.date_from ?? ''} onChange={e => setDraft({ ...draft, date_from: e.target.value })} className="mt-1 h-9 w-full rounded-md border border-input bg-background px-2 text-sm" /></label>
        <label className="text-xs font-medium">To date<input type="date" value={draft.date_to ?? ''} onChange={e => setDraft({ ...draft, date_to: e.target.value })} className="mt-1 h-9 w-full rounded-md border border-input bg-background px-2 text-sm" /></label>
        <button onClick={apply} className="mt-5 h-9 rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground">Apply filters</button>
      </div>
      <div className="mt-4 flex gap-2"><button onClick={() => setGrouped(true)} className={`rounded-full px-3 py-1.5 text-sm ${grouped ? 'bg-primary text-primary-foreground' : 'border border-input'}`}>By paper</button><button onClick={() => setGrouped(false)} className={`rounded-full px-3 py-1.5 text-sm ${!grouped ? 'bg-primary text-primary-foreground' : 'border border-input'}`}>Flat calls</button></div>
    </div>
    {!grouped ? <div className="overflow-hidden rounded-2xl border bg-card shadow-sm"><CallRows calls={items} inrPerUsd={inrPerUsd} onView={setSelectedId} /><Pagination data={data} filters={filters} setFilters={setFilters} /></div> : <div className="space-y-4">{groups.map(([id, calls], index) => {
      const callUsd = calls.reduce((sum, call) => sum + (call.cost_usd ?? 0), 0);
      const stageTotals = new Map<string, number>();
      for (const call of calls) {
        const stage = callStage(call.call_type);
        stageTotals.set(stage, (stageTotals.get(stage) ?? 0) + 1);
      }
      const linkedPaper = Boolean(calls[0].document_id);
      const inputTokens = calls.reduce((sum, call) => sum + (call.input_tokens ?? 0), 0);
      const outputTokens = calls.reduce((sum, call) => sum + (call.output_tokens ?? 0), 0);
      const thinkingTokens = calls.reduce((sum, call) => sum + (call.thinking_tokens ?? 0), 0);
      const cachedTokens = calls.reduce((sum, call) => sum + (call.cached_tokens ?? 0), 0);
      const startedAt = calls.reduce((first, call) => call.created_at < first ? call.created_at : first, calls[0].created_at);
      const isCollapsed = collapsedGroups[id] === true;
      const groupTitle = calls[0].document_name ?? "No linked paper";
      return <section key={id} className={`overflow-hidden rounded-2xl border shadow-sm ${index % 2 === 0 ? "border-emerald-200" : "border-sky-200"}`}>
        <button type="button" onClick={() => setCollapsedGroups(current => ({ ...current, [id]: !isCollapsed }))} aria-expanded={!isCollapsed} className={`flex w-full flex-col gap-4 px-5 py-4 text-left transition-colors ${index % 2 === 0 ? "bg-emerald-100/75 hover:bg-emerald-100" : "bg-sky-100/75 hover:bg-sky-100"}`}>
          <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
            <div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><h2 className="truncate text-lg font-semibold">{groupTitle}</h2><span className="rounded-full bg-emerald-700/10 px-2 py-0.5 text-xs font-semibold text-emerald-800">{linkedPaper ? "Paper workflow" : "Needs attribution"}</span></div><p className="mt-1 text-sm text-muted-foreground">{linkedPaper ? `Started ${localDateTime(startedAt)}` : "Older provider call not reliably linked to a paper."}</p>{linkedPaper && <p className="mt-1 text-xs text-muted-foreground">Paper ID {calls[0].document_id}</p>}</div>
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-foreground"><span><strong>{calls.length} call{calls.length === 1 ? "" : "s"}</strong> · {stageTotals.size} stage{stageTotals.size === 1 ? "" : "s"}</span><span>Tokens <strong>{compactNumber(inputTokens)} in</strong> · {compactNumber(outputTokens)} out · {compactNumber(thinkingTokens)} thinking · {compactNumber(cachedTokens)} cached</span></div>
            <div className="flex items-center gap-3 self-start lg:text-right"><div><p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Workflow total</p><p className="font-semibold text-emerald-800">{money(callUsd, "USD")} <span className="text-sm font-medium">/ {money(inrFromUsd(callUsd), "INR")}</span></p></div><span className="text-xl leading-none text-muted-foreground" aria-hidden="true">{isCollapsed ? "⌄" : "⌃"}</span></div>
          </div>
          <div className="flex flex-wrap gap-2">{Array.from(stageTotals.entries()).map(([stage, count]) => <span key={stage} className="rounded-full border border-emerald-200 bg-background/60 px-2.5 py-1 text-xs font-medium text-emerald-800">{stage} <span className="text-emerald-700/75">×{count}</span></span>)}</div>
        </button>
        {!isCollapsed && <><div className="border-y bg-background/70 px-5 py-2 text-xs text-muted-foreground">Individual provider calls included in this workflow total.</div><div className="overflow-x-auto bg-card"><CallRows calls={calls} inrPerUsd={inrPerUsd} onView={setSelectedId} /></div></>}
      </section>;
    })}<Pagination data={data} filters={filters} setFilters={setFilters} /></div>}
    {items.length === 0 && <div className="rounded-2xl border bg-card p-10 text-center text-sm text-muted-foreground">No API calls match these filters yet.</div>}
    {selectedId && <><div onClick={() => setSelectedId(null)} className="fixed inset-0 z-30 bg-black/30" /><LogDetail id={selectedId} inrPerUsd={inrPerUsd} onClose={() => setSelectedId(null)} /></>}
  </div>;
}
