-- Generated or imported questions must require teacher review unless an
-- explicit, trusted workflow sets a different review status.
alter table public.questions
  alter column review_status set default 'pending_review';
  