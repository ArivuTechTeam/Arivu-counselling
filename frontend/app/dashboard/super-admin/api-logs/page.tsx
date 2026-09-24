"use client";

import useSWR from "swr";

import { ErrorCard } from "@/components/ui/error-card";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiCallLogPage, ApiLogFilters, listApiLogs } from "@/lib/api";
import { useSessionStorageState } from "@/lib/use-session-storage-state";

const money = (value: number | null, currency: "USD" | "INR") => value === null
  ? "—"
  : new Intl.NumberFormat("en-IN", { style: "currency", currency, maximumFractionDigits: 5 }).format(value);
const number = (value: number | null) => value?.toLocaleString() ?? "—";
const localDateTime = (value: string) => new Intl.DateTimeFormat("en-IN", {
  day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZoneName: "short",
}).format(new Date(value));

function Pagination({ data, filters, setFilters }: {
  data: ApiCallLogPage | undefined;
  filters: ApiLogFilters;
  setFilters: (filters: ApiLogFilters) => void;
}) {
  const page = filters.page ?? 1;
  const pageSize = filters.page_size ?? 50;
  return <div className="flex items-center justify-between border-t p-4 text-sm">
    <span>{data?.total ?? 0} total calls</span>
    <div className="flex gap-2">
      <button disabled={page <= 1} onClick={() => setFilters({ ...filters, page: page - 1 })} className="rounded border px-3 py-1 disabled:opacity-40">Previous</button>
      <button disabled={page * pageSize >= (data?.total ?? 0)} onClick={() => setFilters({ ...filters, page: page + 1 })} className="rounded border px-3 py-1 disabled:opacity-40">Next</button>
    </div>
  </div>;
}

export default function ApiLogsPage() {
  const [filters, setFilters] = useSessionStorageState<ApiLogFilters>(
    "super-admin-api-logs-filters", { page: 1, page_size: 50 },
    (value): value is ApiLogFilters => !!value && typeof value === "object",
  );
  const [draft, setDraft] = useSessionStorageState<ApiLogFilters>(
    "super-admin-api-logs-filter-draft", {},
    (value): value is ApiLogFilters => !!value && typeof value === "object",
  );
  const { data, error, isLoading } = useSWR(["api-logs", filters], () => listApiLogs(filters));
  const apply = () => setFilters({
    ...draft,
    date_from: draft.date_from ? `${draft.date_from}T00:00:00.000Z` : undefined,
    date_to: draft.date_to ? `${draft.date_to}T23:59:59.999Z` : undefined,
    page: 1,
    page_size: 50,
  });
  if (error) return <div className="space-y-6"><PageHeader title="AI API logs" description="Metadata-only provider observability." /><ErrorCard message={error.message} onRetry={apply} /></div>;
  if (isLoading && !data) return <Skeleton className="h-96 w-full" />;
  const items = data?.items ?? [];
  const totalUsd = items.reduce((sum, item) => sum + (item.cost_usd ?? 0), 0);
  const totalInr = items.reduce((sum, item) => sum + (item.cost_inr ?? 0), 0);
  return <div className="space-y-6">
    <PageHeader title="AI API logs" description="Usage, latency, status, and cost only. Prompts and provider responses are never stored." actions={<button onClick={apply} className="rounded-lg border px-3 py-2 text-sm">Refresh</button>} />
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {[["Calls on this page", String(items.length)], ["Estimated USD", money(totalUsd, "USD")], ["Estimated INR", money(totalInr, "INR")], ["Errors", String(items.filter(item => item.status === "error").length)]].map(([label, value]) => <div key={label} className="rounded-2xl border bg-card p-5"><p className="text-2xl font-bold text-primary">{value}</p><p className="mt-2 text-xs text-muted-foreground">{label}</p></div>)}
    </div>
    <div className="rounded-2xl border bg-card p-4">
      <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-5">
        <label className="text-xs font-medium">Call type<input value={draft.call_type ?? ""} onChange={event => setDraft({ ...draft, call_type: event.target.value })} className="mt-1 h-9 w-full rounded-md border bg-background px-2" /></label>
        <label className="text-xs font-medium">Provider<select value={draft.provider ?? ""} onChange={event => setDraft({ ...draft, provider: event.target.value })} className="mt-1 h-9 w-full rounded-md border bg-background px-2"><option value="">All</option><option value="gemini">Gemini</option><option value="deepseek">DeepSeek</option></select></label>
        <label className="text-xs font-medium">Status<select value={draft.status ?? ""} onChange={event => setDraft({ ...draft, status: event.target.value })} className="mt-1 h-9 w-full rounded-md border bg-background px-2"><option value="">All</option><option value="success">Success</option><option value="error">Error</option></select></label>
        <label className="text-xs font-medium">From<input type="date" value={draft.date_from ?? ""} onChange={event => setDraft({ ...draft, date_from: event.target.value })} className="mt-1 h-9 w-full rounded-md border bg-background px-2" /></label>
        <label className="text-xs font-medium">To<input type="date" value={draft.date_to ?? ""} onChange={event => setDraft({ ...draft, date_to: event.target.value })} className="mt-1 h-9 w-full rounded-md border bg-background px-2" /></label>
      </div>
      <button onClick={apply} className="mt-3 h-9 rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground">Apply filters</button>
    </div>
    <div className="overflow-x-auto rounded-2xl border bg-card">
      <table className="w-full min-w-[1000px] text-left text-sm">
        <thead className="bg-muted/50 text-xs uppercase text-muted-foreground"><tr>{["Time", "Call type", "Model", "Route", "In", "Out", "Thinking", "Cached", "Cost", "Result"].map(label => <th key={label} className="px-4 py-3">{label}</th>)}</tr></thead>
        <tbody>{items.map((item, index) => <tr key={`${item.created_at}-${item.provider}-${index}`} className="border-t">
          <td className="whitespace-nowrap px-4 py-3 text-xs">{localDateTime(item.created_at)}</td><td className="px-4 py-3">{item.call_type.replaceAll("_", " ")}</td><td className="px-4 py-3"><strong>{item.model}</strong><span className="block text-xs text-muted-foreground">{item.provider}</span></td><td className="px-4 py-3">{item.was_fallback ? "Fallback" : "Primary"}</td><td className="px-4 py-3">{number(item.input_tokens)}</td><td className="px-4 py-3">{number(item.output_tokens)}</td><td className="px-4 py-3">{number(item.thinking_tokens)}</td><td className="px-4 py-3">{number(item.cached_tokens)}</td><td className="whitespace-nowrap px-4 py-3">{money(item.cost_usd, "USD")}<span className="block text-xs text-muted-foreground">{money(item.cost_inr, "INR")}</span></td><td className="px-4 py-3">{item.status}</td>
        </tr>)}</tbody>
      </table>
      <Pagination data={data} filters={filters} setFilters={setFilters} />
    </div>
    {!items.length && <p className="rounded-2xl border p-10 text-center text-sm text-muted-foreground">No matching calls.</p>}
  </div>;
}
