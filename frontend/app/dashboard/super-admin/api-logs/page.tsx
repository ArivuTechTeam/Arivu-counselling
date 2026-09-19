"use client";

import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";

import { ErrorCard } from "@/components/ui/error-card";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton, SkeletonStats } from "@/components/ui/skeleton";
import {
  ApiCallLog,
  ApiLogFilters,
  getApiLog,
  getApiLogsByDocument,
  listApiLogs,
} from "@/lib/api";

const money = (value: number | null, currency: "USD" | "INR") =>
  value === null ? "—" : new Intl.NumberFormat("en-IN", {
    style: "currency", currency, maximumFractionDigits: currency === "USD" ? 5 : 2,
  }).format(value);
const number = (value: number | null) => value?.toLocaleString() ?? "—";

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

function LogDetail({ id, onClose }: { id: string; onClose: () => void }) {
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
          {[['Input', number(data.input_tokens)], ['Output', number(data.output_tokens)], ['USD', money(data.cost_usd, 'USD')], ['INR', money(data.cost_inr, 'INR')]].map(([label, value]) => <div key={label} className="rounded-xl border bg-muted/30 p-3"><p className="text-xs text-muted-foreground">{label}</p><p className="mt-1 font-semibold">{value}</p></div>)}
        </div>
        <div className="rounded-xl border bg-muted/30 p-4 text-sm"><span className="font-medium">{data.provider} / {data.model}</span><span className="mx-2 text-muted-foreground">·</span>{data.call_type}<span className="mx-2 text-muted-foreground">·</span>{data.latency_ms} ms</div>
        <section className="rounded-xl border p-4"><h2 className="mb-3 font-semibold">Raw request</h2><JsonTree value={data.raw_request} /></section>
        <section className="rounded-xl border p-4"><h2 className="mb-3 font-semibold">Raw response</h2><JsonTree value={data.raw_response} /></section>
      </div>}
    </aside>
  );
}

export default function ApiLogsPage() {
  const [filters, setFilters] = useState<ApiLogFilters>({ page: 1, page_size: 50 });
  const [draft, setDraft] = useState<ApiLogFilters>({});
  const [grouped, setGrouped] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [expandedDocument, setExpandedDocument] = useState<string | null>(null);
  const { data, error, isLoading } = useSWR(["api-logs", filters], () => listApiLogs(filters));
  const { data: expanded } = useSWR(
    expandedDocument ? ["api-log-document", expandedDocument] : null,
    () => getApiLogsByDocument(expandedDocument!),
  );
  const groups = useMemo(() => {
    const rows = new Map<string, ApiCallLog[]>();
    for (const item of data?.items ?? []) {
      const key = item.document_id ?? `unlinked:${item.job_id ?? item.id}`;
      rows.set(key, [...(rows.get(key) ?? []), item]);
    }
    return Array.from(rows.entries());
  }, [data]);
  useEffect(() => { if (!grouped) setExpandedDocument(null); }, [grouped]);
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
  const totalInr = items.reduce((sum, item) => sum + (item.cost_inr ?? 0), 0);
  return <div className="space-y-6">
    <PageHeader title="AI API logs" description="Inspect every raw provider response, usage tokens, latency, and estimated cost." actions={<button onClick={() => apply()} className="rounded-lg border border-input bg-card px-3 py-2 text-sm font-medium hover:bg-accent">Refresh</button>} />
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {[['Calls on this page', String(items.length)], ['Estimated USD', money(totalUsd, 'USD')], ['Estimated INR', money(totalInr, 'INR')], ['Errors', String(items.filter(i => i.status === 'error').length)]].map(([label, value]) => <div key={label} className="rounded-2xl border bg-card p-5 shadow-sm"><p className="text-2xl font-bold text-primary">{value}</p><p className="mt-2 text-[11px] font-semibold uppercase tracking-widest text-muted-foreground">{label}</p></div>)}
    </div>
    <div className="rounded-2xl border bg-card p-4 shadow-sm">
      <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
        {([['tenant_id', 'Tenant ID'], ['document_id', 'Document ID'], ['call_type', 'Call type']] as const).map(([key, label]) => <label key={key} className="text-xs font-medium">{label}<input value={(draft[key] as string) ?? ''} onChange={e => setDraft({ ...draft, [key]: e.target.value })} className="mt-1 h-9 w-full rounded-md border border-input bg-background px-2 text-sm" /></label>)}
        <label className="text-xs font-medium">Provider<select value={draft.provider ?? ''} onChange={e => setDraft({ ...draft, provider: e.target.value })} className="mt-1 h-9 w-full rounded-md border border-input bg-background px-2 text-sm"><option value="">All</option><option value="gemini">Gemini</option><option value="deepseek">DeepSeek</option></select></label>
        <label className="text-xs font-medium">Status<select value={draft.status ?? ''} onChange={e => setDraft({ ...draft, status: e.target.value })} className="mt-1 h-9 w-full rounded-md border border-input bg-background px-2 text-sm"><option value="">All</option><option value="success">Success</option><option value="error">Error</option></select></label>
        <label className="text-xs font-medium">From date<input type="date" value={draft.date_from ?? ''} onChange={e => setDraft({ ...draft, date_from: e.target.value })} className="mt-1 h-9 w-full rounded-md border border-input bg-background px-2 text-sm" /></label>
        <label className="text-xs font-medium">To date<input type="date" value={draft.date_to ?? ''} onChange={e => setDraft({ ...draft, date_to: e.target.value })} className="mt-1 h-9 w-full rounded-md border border-input bg-background px-2 text-sm" /></label>
        <button onClick={apply} className="mt-5 h-9 rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground">Apply filters</button>
      </div>
      <div className="mt-4 flex gap-2"><button onClick={() => setGrouped(false)} className={`rounded-full px-3 py-1.5 text-sm ${!grouped ? 'bg-primary text-primary-foreground' : 'border border-input'}`}>Flat calls</button><button onClick={() => setGrouped(true)} className={`rounded-full px-3 py-1.5 text-sm ${grouped ? 'bg-primary text-primary-foreground' : 'border border-input'}`}>Grouped by paper</button></div>
    </div>
    <div className="overflow-hidden rounded-2xl border bg-card shadow-sm">
      {!grouped ? <table className="w-full min-w-[1050px] text-left text-sm"><thead className="bg-muted/50 text-xs uppercase tracking-wide text-muted-foreground"><tr>{['Time','Paper','Type','Provider / model','Tokens (in / out / cache / think)','USD','INR','Status',''].map(x => <th key={x} className="px-4 py-3 font-medium">{x}</th>)}</tr></thead><tbody>{items.map(item => <tr key={item.id} className="border-t hover:bg-muted/30"><td className="px-4 py-3 whitespace-nowrap">{new Date(item.created_at).toLocaleString()}</td><td className="max-w-40 truncate px-4 py-3">{item.document_name ?? 'Unlinked call'}</td><td className="px-4 py-3">{item.call_type}</td><td className="px-4 py-3">{item.provider}<br/><span className="text-xs text-muted-foreground">{item.model}</span></td><td className="px-4 py-3">{number(item.input_tokens)} / {number(item.output_tokens)} / {number(item.cached_tokens)} / {number(item.thinking_tokens)}</td><td className="px-4 py-3">{money(item.cost_usd, 'USD')}</td><td className="px-4 py-3">{money(item.cost_inr, 'INR')}</td><td className="px-4 py-3"><span className={`rounded-full px-2 py-1 text-xs ${item.status === 'success' ? 'bg-emerald-100 text-emerald-700' : 'bg-rose-100 text-rose-700'}`}>{item.status}</span></td><td className="px-4 py-3"><button onClick={() => setSelectedId(item.id)} className="text-primary hover:underline">View</button></td></tr>)}</tbody></table> : <div className="divide-y">{groups.map(([id, calls]) => <div key={id} className="p-4"><button className="flex w-full items-center justify-between text-left" onClick={() => setExpandedDocument(expandedDocument === calls[0].document_id ? null : calls[0].document_id)}><span><span className="font-semibold">{calls[0].document_name ?? 'Unlinked calls'}</span><span className="ml-2 text-sm text-muted-foreground">{calls.length} call(s) on this page</span></span><span className="text-sm text-primary">{money(calls.reduce((s,c)=>s+(c.cost_inr ?? 0),0),'INR')}</span></button>{expandedDocument === calls[0].document_id && <div className="mt-3 rounded-lg bg-muted/40 p-3 text-sm">{expanded ? <><p className="mb-2 text-muted-foreground">{expanded.summary.call_count} calls · {number(expanded.summary.input_tokens)} input · {money(expanded.summary.cost_usd,'USD')}</p>{expanded.items.map(call => <button key={call.id} onClick={() => setSelectedId(call.id)} className="mr-2 mb-2 rounded border bg-card px-2 py-1 hover:bg-accent">{call.call_type} · {call.provider}</button>)}</> : 'Loading paper rollup…'}</div>}</div>)}</div>}
      {items.length === 0 && <p className="p-10 text-center text-sm text-muted-foreground">No API calls match these filters yet.</p>}
      <div className="flex items-center justify-between border-t p-4 text-sm"><span>{data?.total ?? 0} total calls</span><div className="flex gap-2"><button disabled={(filters.page ?? 1) <= 1} onClick={() => setFilters({...filters, page: (filters.page ?? 1) - 1})} className="rounded border px-3 py-1 disabled:opacity-40">Previous</button><button disabled={(filters.page ?? 1) * (filters.page_size ?? 50) >= (data?.total ?? 0)} onClick={() => setFilters({...filters, page: (filters.page ?? 1) + 1})} className="rounded border px-3 py-1 disabled:opacity-40">Next</button></div></div>
    </div>
    {selectedId && <><div onClick={() => setSelectedId(null)} className="fixed inset-0 z-30 bg-black/30" /><LogDetail id={selectedId} onClose={() => setSelectedId(null)} /></>}
  </div>;
}
