-- Keep the private documents bucket below the Supabase Free-plan global
-- ceiling and aligned with the frontend/backend 30 MiB upload validation.
-- Existing access settings are preserved when the bucket already exists.

insert into storage.buckets (
  id,
  name,
  public,
  file_size_limit,
  allowed_mime_types
)
values (
  'documents',
  'documents',
  false,
  31457280,
  array[
    'application/pdf',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'image/png',
    'image/jpeg'
  ]
)
on conflict (id) do update
set file_size_limit = excluded.file_size_limit;
