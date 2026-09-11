-- Composite indexes for the tenant-scoped filters used by the staff dashboards.
-- Safe to run repeatedly; no data or constraints are changed.

create index if not exists idx_profiles_tenant_role
  on profiles(tenant_id, role);
create index if not exists idx_subjects_tenant_course
  on subjects(tenant_id, course_id);
create index if not exists idx_enrollments_tenant_course_profile
  on enrollments(tenant_id, course_id, profile_id);
create index if not exists idx_teacher_subjects_tenant_teacher_subject
  on teacher_subjects(tenant_id, teacher_id, subject_id);
create index if not exists idx_chapters_tenant_subject
  on chapters(tenant_id, subject_id);
create index if not exists idx_documents_tenant_uploader_created
  on documents(tenant_id, uploaded_by, created_at desc);
create index if not exists idx_questions_tenant_creator_chapter
  on questions(tenant_id, created_by, chapter_id);
create index if not exists idx_questions_tenant_review
  on questions(tenant_id, review_status);
create index if not exists idx_quizsets_tenant_creator_status
  on quiz_sets(tenant_id, created_by, status);
create index if not exists idx_quizsets_tenant_subject
  on quiz_sets(tenant_id, subject_id);
create index if not exists idx_variants_tenant_quizset
  on quiz_variants(tenant_id, quiz_set_id);
create index if not exists idx_vq_tenant_variant
  on quiz_variant_questions(tenant_id, variant_id);
create index if not exists idx_attempts_tenant_variant_status
  on quiz_attempts(tenant_id, variant_id, status);
create index if not exists idx_attempts_tenant_student_status_submitted
  on quiz_attempts(tenant_id, student_id, status, submitted_at desc);
