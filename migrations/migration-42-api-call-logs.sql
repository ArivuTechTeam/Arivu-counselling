-- Raw provider responses are operationally sensitive. The trusted backend
-- writes them and the application enforces super-admin-only reads.
create table public.api_call_logs (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid references public.tenants(id) on delete set null,
  document_id uuid references public.documents(id) on delete set null,
  job_id uuid references public.quiz_generation_jobs(id) on delete set null,
  call_type text not null,
  provider text not null check (provider in ('gemini', 'deepseek')),
  model text not null,
  was_fallback boolean not null default false,
  input_tokens integer,
  output_tokens integer,
  cached_tokens integer,
  thinking_tokens integer,
  cost_usd numeric(18, 8),
  cost_inr numeric(18, 8),
  raw_request jsonb not null,
  raw_response jsonb,
  latency_ms integer not null,
  status text not null check (status in ('success', 'error')),
  error_message text,
  created_at timestamptz not null default now()
);

create index api_call_logs_document_id_idx on public.api_call_logs(document_id);
create index api_call_logs_tenant_created_at_idx on public.api_call_logs(tenant_id, created_at desc);
create index api_call_logs_created_at_idx on public.api_call_logs(created_at desc);
create index api_call_logs_call_type_idx on public.api_call_logs(call_type);

alter table public.api_call_logs enable row level security;
revoke all on table public.api_call_logs from public, anon, authenticated;
grant select, insert, update, delete on table public.api_call_logs to service_role;
