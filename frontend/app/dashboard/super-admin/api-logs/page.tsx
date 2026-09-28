"use client";

import { useEffect, useState } from "react";
import useSWR, { useSWRConfig } from "swr";

import { ErrorCard } from "@/components/ui/error-card";
import { Dialog } from "@/components/ui/dialog";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton, SkeletonStats } from "@/components/ui/skeleton";
import {
  ApiCallLog,
  ApiCallLogPage,
  ApiLogFilters,
  listApiLogs,
} from "@/lib/api";
import { QuizCostWorkflows } from "@/components/admin/quiz-cost-workflows";
import { callStage, conversionRate } from "@/lib/api-log-display";
import { useSessionStorageState } from "@/lib/use-session-storage-state";

const INR_RATE_STORAGE_KEY = "super-admin-api-logs-inr-rate";
const DEFAULT_INR_PER_USD = "83";

const money = (value: number | null, currency: "USD" | "INR") =>
  value === null ? "—" : new Intl.NumberFormat("en-IN", {
    style: "currency", currency, maximumFractionDigits: currency === "USD" ? 5 : 2,
  }).format(value);
const number = (value: number | null) => value?.toLocaleString() ?? "—";
const localDateTime = (value: string) => new Intl.DateTimeFormat("en-IN", {
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
  timeZoneName: "short",
  timeZone: "Asia/Kolkata",
}).format(new Date(value));


function LogDetail({ data, inrPerUsd, onClose }: {
  data: ApiCallLog; inrPerUsd: number; onClose: () => void;
}) {
  return <Dialog onClose={onClose} ariaLabelledBy="api-call-detail-title"
    overlayClassName="fixed inset-0 z-50 flex justify-end bg-black/30"
    contentClassName="h-full w-full max-w-2xl overflow-y-auto border-l bg-card p-5 shadow-2xl sm:p-6">
    <div className="mb-5 flex items-start justify-between gap-4">
      <div><h2 id="api-call-detail-title" className="text-lg font-semibold">API call detail</h2>
        <p className="mt-1 text-sm text-muted-foreground">Operational metadata only. Prompts, responses and filenames are excluded.</p></div>
      <button onClick={onClose} className="rounded-lg border px-3 py-1.5 text-sm">Close</button>
    </div>
    <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2">
      {[
        ["Stage", callStage(data.call_type)], ["Model", data.model], ["Provider", data.provider],
        ["Routing", data.was_fallback ? "Fallback" : "Primary"], ["Result", data.status],
        ["Time (IST)", localDateTime(data.created_at)], ["Latency", `${data.latency_ms.toLocaleString()} ms`],
        ["Input tokens", number(data.input_tokens)], ["Output tokens", number(data.output_tokens)],
        ["Thinking tokens", number(data.thinking_tokens)], ["Cached tokens", number(data.cached_tokens)],
        ["Estimated USD", money(data.cost_usd, "USD")],
        ["View estimate INR", money(data.cost_usd === null ? null : data.cost_usd * inrPerUsd, "INR")],
        ["Recorded INR", money(data.cost_inr, "INR")],
        ["Call ID", data.id], ["Tenant ID", data.tenant_id ?? "Unlinked"],
        ["Document ID", data.document_id ?? "Not recorded"], ["Job ID", data.job_id ?? "Not recorded"],
      ].map(([label, value]) => <div key={label} className="rounded-xl border bg-muted/30 p-3">
        <dt className="text-xs text-muted-foreground">{label}</dt><dd className="mt-1 break-all font-medium">{value}</dd>
      </div>)}
    </dl>
    {data.status === "error" && <p className="mt-4 rounded-xl border p-4 text-sm">Provider call failed. Check provider availability and configuration.</p>}
  </Dialog>;
}

function CallRows({
  calls,
  inrPerUsd,
  onView,
}: {
  calls: ApiCallLog[];
  inrPerUsd: number;
  onView: (call: ApiCallLog) => void;
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
      <td className="px-4 py-3"><button onClick={() => onView(item)} className="text-primary hover:underline">View</button></td>
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
  const { mutate: mutateCache } = useSWRConfig();
  const [filters, setFilters] = useSessionStorageState<ApiLogFilters>(
    "super-admin-api-logs-filters",
    { page: 1, page_size: 50 },
    (value): value is ApiLogFilters => !!value && typeof value === "object",
  );
  const [draft, setDraft] = useSessionStorageState<ApiLogFilters>(
    "super-admin-api-logs-filter-draft",
    {},
    (value): value is ApiLogFilters => !!value && typeof value === "object",
  );
  const [grouped, setGrouped] = useSessionStorageState(
    "super-admin-api-logs-grouped",
    true,
    (value): value is boolean => typeof value === "boolean",
  );
  const [selectedCall, setSelectedCall] = useState<ApiCallLog | null>(null);
  const [inrPerUsdInput, setInrPerUsdInput] = useState(DEFAULT_INR_PER_USD);
  const [inrRateHydrated, setInrRateHydrated] = useState(false);
  useEffect(() => {
    try {
      const saved = window.sessionStorage.getItem(INR_RATE_STORAGE_KEY);
      if (saved) setInrPerUsdInput(saved);
    } catch {
      // The live calculation still works when browser storage is unavailable.
    } finally {
      setInrRateHydrated(true);
    }
  }, []);
  useEffect(() => {
    if (!inrRateHydrated) return;
    try {
      window.sessionStorage.setItem(INR_RATE_STORAGE_KEY, inrPerUsdInput);
    } catch {
      // The live calculation still works when browser storage is unavailable.
    }
  }, [inrPerUsdInput, inrRateHydrated]);
  const [filterError, setFilterError] = useState<string | null>(null);
  const { data, error, isLoading, mutate } = useSWR(grouped ? null : ["api-logs", filters], () => listApiLogs(filters));
  const apply = () => {
    for (const [field, label] of [["tenant_id", "Tenant ID"], ["document_id", "Document ID"]] as const) {
      const value = draft[field]?.trim();
      if (value && !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value)) {
        setFilterError(`Enter a valid ${label}, or leave it empty to show all calls.`);
        return;
      }
    }
    if (draft.date_from && draft.date_to && draft.date_from > draft.date_to) {
      setFilterError("The From date must be on or before the To date.");
      return;
    }
    setFilterError(null);
    setSelectedCall(null);
    setFilters({
    ...draft,
    tenant_id: draft.tenant_id?.trim() || undefined,
    document_id: draft.document_id?.trim() || undefined,
    // Browser date inputs have no timezone. Send an explicit inclusive UTC
    // range so selecting a day includes every call made on that day.
    date_from: draft.date_from ? `${draft.date_from}T00:00:00.000Z` : undefined,
    date_to: draft.date_to ? `${draft.date_to}T23:59:59.999Z` : undefined,
    page: 1,
    page_size: 50,
    });
  };

  if (isLoading && !data) return <div className="space-y-6"><Skeleton className="h-16 w-96 max-w-full" /><SkeletonStats /><Skeleton className="h-96 w-full" /></div>;
  const items = data?.items ?? [];
  const totalUsd = items.reduce((sum, item) => sum + (item.cost_usd ?? 0), 0);
  const parsedInrPerUsd = conversionRate(inrPerUsdInput);
  const hasValidInrRate = parsedInrPerUsd !== null;
  const inrPerUsd = parsedInrPerUsd ?? Number(DEFAULT_INR_PER_USD);
  const totalInr = totalUsd * inrPerUsd;
  return <div className="space-y-6">
    <PageHeader title="AI API logs" description="Track each quiz generation or import run, its stages and estimated cost. Prompts and provider responses are never stored." actions={<button onClick={() => {
      if (grouped) void mutateCache(key => Array.isArray(key) && ["quiz-cost-workflows", "quiz-cost-calls"].includes(key[0]));
      else void mutate();
    }} className="rounded-lg border border-input bg-card px-3 py-2 text-sm font-medium hover:bg-accent">Refresh</button>} />
    {error && <ErrorCard message={error.message} onRetry={() => void mutate()} />}
    {!grouped && <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {[['Calls on this page', String(items.length)], ['Estimated USD', money(totalUsd, 'USD')], ['View estimate INR', money(totalInr, 'INR')], ['Errors', String(items.filter(i => i.status === 'error').length)]].map(([label, value]) => <div key={label} className="rounded-2xl border bg-card p-5 shadow-sm"><p className="text-2xl font-bold text-primary">{value}</p><p className="mt-2 text-[11px] font-semibold uppercase tracking-widest text-muted-foreground">{label}</p></div>)}
    </div>}
    <div className="rounded-2xl border bg-card p-4 shadow-sm">
      <div className="mb-4 flex flex-col gap-2 rounded-xl border border-dashed bg-muted/20 p-3 sm:flex-row sm:items-end sm:justify-between">
        <div><p className="text-sm font-semibold">INR conversion rate</p><p className="text-xs text-muted-foreground">Enter the current rupees value for one US dollar. INR estimates update immediately for this view.</p></div>
        <label className="text-xs font-medium">₹ per US$<input type="number" min="0.01" step="0.01" inputMode="decimal" value={inrPerUsdInput} onChange={e => setInrPerUsdInput(e.target.value)} className="mt-1 block h-9 w-36 rounded-md border border-input bg-background px-2 text-sm" /></label>
      </div>
      {!hasValidInrRate && <p className="mb-3 text-xs text-rose-600">Enter a positive conversion rate. Using ₹83.00 per US$ until it is corrected.</p>}
      {filterError && <p role="alert" className="mb-3 text-sm text-rose-600">{filterError}</p>}
      <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
        {!grouped && <label className="text-xs font-medium">Call type<input value={draft.call_type ?? ""} onChange={event => setDraft({ ...draft, call_type: event.target.value })} className="mt-1 h-9 w-full rounded-md border border-input bg-background px-2 text-sm" /></label>}
        {([['tenant_id', 'Institution ID'], ['document_id', 'Document ID']] as const).map(([key, label]) => <label key={key} className="text-xs font-medium">{label}<input value={(draft[key] as string) ?? ''} onChange={e => setDraft({ ...draft, [key]: e.target.value })} className="mt-1 h-9 w-full rounded-md border border-input bg-background px-2 text-sm" /></label>)}
        <label className="text-xs font-medium">Provider<select value={draft.provider ?? ''} onChange={e => setDraft({ ...draft, provider: e.target.value })} className="mt-1 h-9 w-full rounded-md border border-input bg-background px-2 text-sm"><option value="">All</option><option value="gemini">Gemini</option><option value="deepseek">DeepSeek</option></select></label>
        <label className="text-xs font-medium">Status<select value={draft.status ?? ''} onChange={e => setDraft({ ...draft, status: e.target.value })} className="mt-1 h-9 w-full rounded-md border border-input bg-background px-2 text-sm"><option value="">All</option><option value="success">Success</option><option value="error">Error</option></select></label>
        <label className="text-xs font-medium">From date<input type="date" value={draft.date_from ?? ''} onChange={e => setDraft({ ...draft, date_from: e.target.value })} className="mt-1 h-9 w-full rounded-md border border-input bg-background px-2 text-sm" /></label>
        <label className="text-xs font-medium">To date<input type="date" value={draft.date_to ?? ''} onChange={e => setDraft({ ...draft, date_to: e.target.value })} className="mt-1 h-9 w-full rounded-md border border-input bg-background px-2 text-sm" /></label>
        <button onClick={apply} className="mt-5 h-9 rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground">Apply filters</button>
        <button onClick={() => { setDraft({}); setFilters({ page: 1, page_size: 50 }); setFilterError(null); setSelectedCall(null); }} className="mt-5 h-9 rounded-md border px-3 text-sm">Clear filters</button>
      </div>
      <div className="mt-4 flex gap-2"><button onClick={() => setGrouped(true)} className={`rounded-full px-3 py-1.5 text-sm ${grouped ? 'bg-primary text-primary-foreground' : 'border border-input'}`}>Costs by activity</button><button onClick={() => setGrouped(false)} className={`rounded-full px-3 py-1.5 text-sm ${!grouped ? 'bg-primary text-primary-foreground' : 'border border-input'}`}>Individual AI requests</button></div>
      <p className="mt-2 text-xs text-muted-foreground">Date filters use UTC days; call timestamps are displayed in IST.</p>
    </div>
    {grouped ? <QuizCostWorkflows key={JSON.stringify(filters)} filters={filters} inrPerUsd={inrPerUsd} onView={setSelectedCall} />
      : <div className="overflow-x-auto rounded-2xl border bg-card shadow-sm">
        <CallRows calls={items} inrPerUsd={inrPerUsd} onView={setSelectedCall} />
        <Pagination data={data} filters={filters} setFilters={setFilters} />
        {!error && items.length === 0 && <p className="p-10 text-center text-sm text-muted-foreground">No matching calls.</p>}
      </div>}
    {selectedCall && <LogDetail data={selectedCall} inrPerUsd={inrPerUsd} onClose={() => setSelectedCall(null)} />}
  </div>;
}
