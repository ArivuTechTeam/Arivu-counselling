-- Migration 45 — Document figures (Phase 1 of document-figure support)
-- Apply after migrations 01–44. Additive and safe; no existing table is changed.
-- Feature is gated by the backend flag FIGURE_ATTACH_ENABLED (default false), so
-- creating these objects has no effect until the flag is turned on per tenant.
begin;

-- Private bucket for extracted figure PNGs. Served ONLY via short-lived signed
-- URLs minted by the trusted backend — never public. 5 MiB/PNG ceiling.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('question-figures', 'question-figures', false, 5242880, array['image/png'])
on conflict (id) do nothing;

-- One row per CAPTIONED figure extracted from a source document. The catalog the
-- (later) text-only generator reads to reference a real figure by id. Deleting
-- the source document cascades its figures.
create table if not exists public.document_figures (
  id            uuid primary key default gen_random_uuid(),
  tenant_id     uuid not null references public.tenants(id) on delete cascade,
  document_id   uuid not null references public.documents(id) on delete cascade,
  page          int,                    -- 1-based source page
  bbox          jsonb,                  -- {x0,y0,x1,y1} in PDF points (provenance)
  label         text,                   -- e.g. "Figure 8.1" / "Fig 3.4"
  caption       text,                   -- full caption text
  nearby_text   text,                   -- textual description for the catalog
  storage_path  text not null,          -- question-figures/{tenant}/{document}/{id}.png
  width         int,
  height        int,
  created_at    timestamptz not null default now()
);
create index if not exists idx_docfig_document on public.document_figures(document_id);
create index if not exists idx_docfig_tenant   on public.document_figures(tenant_id);

alter table public.document_figures enable row level security;

-- Staff read only their own tenant's figures. All writes happen from the trusted
-- backend using the service_role key (which bypasses RLS), so there is no
-- client-facing write policy — same model as ai_extraction_jobs / faculty_jobs.
drop policy if exists "staff read own tenant figures" on public.document_figures;
create policy "staff read own tenant figures" on public.document_figures
  for select using (tenant_id = current_tenant_id() and is_staff());

commit;
