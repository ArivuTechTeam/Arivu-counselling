-- Question-level source provenance and verification for subject-neutral quiz generation.
-- Existing questions remain usable and are explicitly marked for teacher review.

alter table public.questions
  add column if not exists source_excerpt text,
  add column if not exists source_page_start integer,
  add column if not exists source_page_end integer,
  add column if not exists grounding_confidence numeric,
  add column if not exists verification_status text not null default 'needs_teacher_review',
  add column if not exists verification_warnings jsonb not null default '[]'::jsonb;

alter table public.questions
  drop constraint if exists questions_source_page_range_check,
  add constraint questions_source_page_range_check check (
    (source_page_start is null and source_page_end is null)
    or (
      source_page_start is not null
      and source_page_end is not null
      and source_page_start > 0
      and source_page_end >= source_page_start
    )
  ),
  drop constraint if exists questions_grounding_confidence_check,
  add constraint questions_grounding_confidence_check check (
    grounding_confidence is null
    or (grounding_confidence >= 0 and grounding_confidence <= 1)
  ),
  drop constraint if exists questions_verification_status_check,
  add constraint questions_verification_status_check check (
    verification_status in (
      'verified', 'needs_teacher_review', 'unsupported', 'ambiguous'
    )
  ),
  drop constraint if exists questions_verification_warnings_array_check,
  add constraint questions_verification_warnings_array_check check (
    jsonb_typeof(verification_warnings) = 'array'
  );

create index if not exists idx_questions_verification_status
  on public.questions(tenant_id, verification_status);

comment on column public.questions.source_excerpt is
  'Verbatim source passage attributed to this generated question.';
comment on column public.questions.verification_status is
  'Grounding verification result; unsupported questions cannot be approved.';
