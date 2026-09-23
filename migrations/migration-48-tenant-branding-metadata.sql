-- Preserve display metadata for institution branding and make the platform
-- green the default for tenants that have never selected a custom colour.
alter table public.tenants
  add column if not exists logo_filename text;

update public.tenants
set primary_color = '#2E8857'
where primary_color is null
   or primary_color !~ '^#[0-9A-Fa-f]{6}$'
   or upper(primary_color) = '#0EA5E9';

alter table public.tenants
  alter column primary_color set default '#2E8857';

alter table public.tenants
  alter column primary_color set not null;

alter table public.tenants
  drop constraint if exists tenants_primary_color_hex;

alter table public.tenants
  add constraint tenants_primary_color_hex
  check (primary_color ~ '^#[0-9A-Fa-f]{6}$');

alter table public.tenants
  drop constraint if exists tenants_logo_filename_length;

alter table public.tenants
  add constraint tenants_logo_filename_length
  check (logo_filename is null or char_length(logo_filename) <= 255);
