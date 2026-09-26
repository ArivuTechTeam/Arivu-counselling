-- Migration 72 — one transactional commit for synchronous generated/imported quizzes.
-- Apply after migration 71 before deploying the matching API/worker code.
begin;

create or replace function public.persist_generated_quiz(
  p_tenant uuid,
  p_actor uuid,
  p_payload jsonb
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_questions jsonb := p_payload->'questions';
  v_item jsonb;
  v_topic_name text;
  v_document uuid := nullif(p_payload->>'document_id', '')::uuid;
  v_subject uuid := nullif(p_payload->>'subject_id', '')::uuid;
  v_chapter uuid := nullif(p_payload->>'chapter_id', '')::uuid;
  v_extraction uuid := nullif(p_payload->>'extraction_job_id', '')::uuid;
  v_quiz uuid;
  v_variant uuid;
  v_question uuid;
  v_topic uuid;
  v_position integer := 0;
  v_count integer;
  v_total numeric := 0;
  v_stored jsonb := '[]'::jsonb;
begin
  if p_payload is null or jsonb_typeof(p_payload) <> 'object'
     or jsonb_typeof(v_questions) <> 'array' then
    raise exception 'Invalid quiz persistence payload';
  end if;
  v_count := jsonb_array_length(v_questions);
  if v_count < 1 or v_count > 1000 then
    raise exception 'Quiz persistence requires between 1 and 1000 questions';
  end if;
  if nullif(btrim(p_payload->>'title'), '') is null
     or nullif(p_payload->>'variant_type', '') is null
     or nullif(p_payload->>'source', '') is null then
    raise exception 'Quiz persistence metadata is incomplete';
  end if;

  if not exists (
    select 1
    from public.profiles profile
    join public.tenants tenant on tenant.id = profile.tenant_id
    where profile.id = p_actor
      and profile.tenant_id = p_tenant
      and profile.role = 'teacher'
      and tenant.is_active
  ) then
    raise exception 'Teacher or institution is unavailable';
  end if;
  if v_document is not null and not exists (
    select 1 from public.documents document
    where document.id = v_document
      and document.tenant_id = p_tenant
      and document.uploaded_by = p_actor
      and document.status::text <> 'archived'
  ) then
    raise exception 'Source document is unavailable';
  end if;
  if v_subject is not null and not exists (
    select 1 from public.teacher_subjects assignment
    where assignment.tenant_id = p_tenant
      and assignment.teacher_id = p_actor
      and assignment.subject_id = v_subject
  ) then
    raise exception 'Subject assignment is unavailable';
  end if;

  -- Serialize the short chapter/topic get-or-create section for one tenant.
  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended(p_tenant::text, 72)
  );
  if v_chapter is not null then
    if not exists (
      select 1 from public.chapters chapter
      where chapter.id = v_chapter
        and chapter.tenant_id = p_tenant
        and (v_subject is null or chapter.subject_id = v_subject)
    ) then
      raise exception 'Chapter is unavailable';
    end if;
  elsif v_subject is not null
        and nullif(btrim(p_payload->>'chapter_name'), '') is not null then
    select chapter.id into v_chapter
    from public.chapters chapter
    where chapter.tenant_id = p_tenant
      and chapter.subject_id = v_subject
      and chapter.name = btrim(p_payload->>'chapter_name')
    order by chapter.id
    limit 1;
    if v_chapter is null then
      insert into public.chapters(tenant_id, subject_id, name)
      values (p_tenant, v_subject, btrim(p_payload->>'chapter_name'))
      returning id into v_chapter;
    end if;
  end if;

  if p_payload ? 'selected_topics' then
    if jsonb_typeof(p_payload->'selected_topics') <> 'array' then
      raise exception 'Selected topics must be an array';
    end if;
    if v_chapter is null then
      raise exception 'Selected topics require a chapter';
    end if;
    for v_topic_name in
      select distinct btrim(value)
      from jsonb_array_elements_text(p_payload->'selected_topics')
      where nullif(btrim(value), '') is not null
    loop
      if not exists (
        select 1 from public.topics topic
        where topic.tenant_id = p_tenant
          and topic.chapter_id = v_chapter
          and topic.name = v_topic_name
      ) then
        insert into public.topics(tenant_id, chapter_id, name)
        values (p_tenant, v_chapter, v_topic_name);
      end if;
    end loop;
  end if;

  for v_item in select value from jsonb_array_elements(v_questions)
  loop
    if jsonb_typeof(v_item) <> 'object'
       or nullif(btrim(v_item->>'question_text'), '') is null
       or v_item->'correct_answer' is null
       or v_item->'correct_answer' = 'null'::jsonb
       or coalesce((v_item->>'marks')::numeric, 1) <= 0 then
      raise exception 'Invalid generated question';
    end if;
    v_total := v_total + coalesce((v_item->>'marks')::numeric, 1);
  end loop;

  insert into public.quiz_sets(
    tenant_id, created_by, document_id, subject_id, chapter_id, title, status
  ) values (
    p_tenant, p_actor, v_document, v_subject, v_chapter,
    btrim(p_payload->>'title'), 'draft'
  ) returning id into v_quiz;

  insert into public.quiz_variants(
    tenant_id, quiz_set_id, variant_type, total_marks
  ) values (
    p_tenant, v_quiz,
    (p_payload->>'variant_type')::public.variant_type,
    v_total
  ) returning id into v_variant;

  for v_item in select value from jsonb_array_elements(v_questions)
  loop
    v_topic := null;
    if v_chapter is not null and nullif(btrim(v_item->>'topic'), '') is not null then
      select topic.id into v_topic
      from public.topics topic
      where topic.tenant_id = p_tenant
        and topic.chapter_id = v_chapter
        and lower(topic.name) = lower(btrim(v_item->>'topic'))
      order by topic.id
      limit 1;
    end if;

    insert into public.questions(
      tenant_id, created_by, chapter_id, topic_id, extraction_job_id,
      type, question_text, options, correct_answer, explanation, difficulty,
      marks, source, review_status, source_excerpt, source_page_start,
      source_page_end, grounding_confidence, verification_status,
      verification_warnings, confidence_score, paper_type, paper_year,
      paper_exam, paper_source_note, model_answer, answer_summary
    ) values (
      p_tenant, p_actor, v_chapter, v_topic, v_extraction,
      (v_item->>'type')::public.question_type,
      btrim(v_item->>'question_text'),
      nullif(v_item->'options', 'null'::jsonb),
      v_item->'correct_answer',
      v_item->>'explanation',
      coalesce(nullif(v_item->>'difficulty', ''), 'medium'),
      coalesce((v_item->>'marks')::numeric, 1),
      (p_payload->>'source')::public.question_source,
      'pending_review',
      coalesce(v_item->>'source_excerpt', ''),
      nullif(v_item->>'source_page_start', '')::integer,
      nullif(v_item->>'source_page_end', '')::integer,
      nullif(v_item->>'grounding_confidence', '')::numeric,
      coalesce(nullif(v_item->>'verification_status', ''), 'needs_teacher_review'),
      case
        when jsonb_typeof(v_item->'verification_warnings') = 'array'
          then v_item->'verification_warnings'
        else '[]'::jsonb
      end,
      nullif(v_item->>'confidence', '')::numeric,
      nullif(v_item->>'paper_type', ''),
      nullif(coalesce(v_item->>'paper_year', v_item->>'year'), ''),
      nullif(coalesce(v_item->>'paper_exam', v_item->>'exam'), ''),
      nullif(v_item->>'paper_source_note', ''),
      nullif(v_item->>'model_answer', ''),
      nullif(v_item->>'answer_summary', '')
    ) returning id into v_question;

    insert into public.quiz_variant_questions(
      tenant_id, variant_id, question_id, order_index
    ) values (p_tenant, v_variant, v_question, v_position);

    v_stored := v_stored || jsonb_build_array(
      v_item || jsonb_build_object(
        'id', v_question,
        'review_status', 'pending_review'
      )
    );
    v_position := v_position + 1;
  end loop;

  if v_document is not null and v_chapter is not null then
    update public.documents
    set chapter_id = v_chapter
    where id = v_document
      and tenant_id = p_tenant
      and uploaded_by = p_actor;
  end if;

  if v_extraction is not null then
    update public.ai_extraction_jobs
    set status = 'succeeded',
      raw_output = coalesce(p_payload->'extraction_raw_output', p_payload),
      model_used = p_payload->>'provider',
      overall_confidence = nullif(p_payload->>'overall_confidence', '')::numeric,
      error_message = null,
      completed_at = pg_catalog.now()
    where id = v_extraction
      and tenant_id = p_tenant
      and document_id = v_document
      and status = 'running';
    if not found then
      raise exception 'Extraction job is unavailable';
    end if;
  end if;

  return jsonb_build_object(
    'quiz_set_id', v_quiz,
    'variant_id', v_variant,
    'provider', p_payload->>'provider',
    'blueprint', p_payload->'blueprint',
    'questions', v_stored,
    'extracted', v_position,
    'skipped', coalesce((p_payload->'import_summary'->>'skipped')::integer, 0),
    'import_summary', p_payload->'import_summary',
    'overall_confidence', p_payload->'overall_confidence',
    'extraction_job_id', v_extraction
  );
end;
$$;

revoke all on function public.persist_generated_quiz(uuid, uuid, jsonb)
  from public, anon, authenticated;
grant execute on function public.persist_generated_quiz(uuid, uuid, jsonb)
  to service_role;

commit;
notify pgrst, 'reload schema';
