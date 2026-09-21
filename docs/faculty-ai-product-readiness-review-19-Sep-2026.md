# Faculty AI product-readiness review and proposed delivery plan

> Historical point-in-time audit from 19 September 2026. For current behavior,
> use `current-ai-document-workflow.md` and `faculty-approval-workflow.md`.

Date: 19 September 2026. Repository reviewed: `3e04602`.

Implementation subsequently authorized by the founder. The first pilot is one commerce coaching institute and one non-engineering college. See [the implementation tracker](faculty-pilot-phase-1.md) for changes and remaining work; the findings below describe the pre-change baseline.

**Decision:** ArivuPro has a credible faculty-assisted quiz authoring foundation. I would consider a tightly supported design-partner pilot after the critical fixes below. I would not yet market it as a generally reliable, subject-independent institutional assessment platform or as ready for high-stakes examinations.

The missing capability is a dependable path from a customer's source document to a usable, accountable assessment: know what was read, preserve what was imported, make uncertainty visible, let faculty resolve it efficiently, survive interruptions, and measure whether the result actually saved time.

This review proposes work for approval. No application implementation, live migrations, paid model calls, publishing, commits, or deployment were performed.

## 1. Scope, evidence, and assumptions

Reviewed the current faculty upload, topic analysis, per-topic generation, existing-paper extraction, question review, approval/publication, archive, source provenance, model routing, quotas, background execution, exports, tests, and local evaluation harness. Compared these with public product documentation from Wayground, Kahoot!, Quizgecko, Moodle, and Questionmark.

Evidence labels:

- **Confirmed:** directly visible in source or reproduced with synthetic, local inputs.
- **Risk:** a plausible operational failure implied by the implementation; not observed under production load.
- **Product gap:** a capability missing from the reviewed workflow; whether to build it depends on buyers.
- **Unverified:** deployed configuration, real provider quality, actual customer adoption, and account-specific terms were not inspected.

Competitor research is documentation-based, not a paid hands-on benchmark. Vendor capability and adoption claims are attributed as such. Their documentation does not prove their AI is more accurate than yours.

Confirmed founder scope: coaching institutes and colleges, initially 5–10 institutions. Reported problems are weak/repetitive questions, missing document content, slow generation, formatting, and unsupported questions becoming publishable after Edit → Save. Pictures, diagrams, and graphs within questions are an explicit requirement. Faculty count, daily generation volume, simultaneous student attempts, subjects, and whether colleges require graded examinations remain unknown. Institution count alone is not a load estimate. The proposed first release supports faculty-reviewed practice/formative assessments for both buyer groups; formal examinations require additional release controls and validation. Effort estimates assume the two founders develop this together.

## 2. What is already worth keeping

- Two distinct user intents: generate new questions from teaching material, or import an existing question paper.
- Institutional roles, tenant-scoped access, explicit teacher subject assignments, and private source files.
- Exact per-topic/type allocation and one correction opportunity for supported generation failures.
- Source excerpts and approximate page provenance, deterministic answer-shape checks, grounding checks, and an AI verification pass.
- Unsupported generated questions are blocked from direct approval; publication requires resolving all questions and retaining approved questions in every variant.
- DOCX tables and some mathematical-symbol extraction handling already exist.
- Source-linked quiz sets, archive flows, and snapshots for new student attempts.
- Provider fallback, atomic AI rate limits, checkpointed document chunks, and retryable analysis states.
- A useful automated test base and a local quality-evaluation harness.

This does not require a rewrite. Preserve these controls while repairing the contracts between stages.

## 3. Market comparison: what institutions buy beyond generation

| Comparator | Documented capability relevant to faculty | Implication for ArivuPro |
| --- | --- | --- |
| Wayground, formerly Quizizz | Generate/import assessments; edit media; common assessments; standards tagging; rostering and LMS integration | Buyers expect material import to connect to distribution, accessibility, and common reporting, not stop at a generated question list |
| Kahoot! EDU | PDF question extraction, AI generation, question-bank access, and school/district offering | Upload-to-quiz is already a familiar feature; it is insufficient as the sole differentiation |
| Quizgecko | Source-to-quiz authoring with editable output, sharing, exports, and LMS-oriented workflows | An export-first faculty tool can fit institutions without replacing their existing LMS |
| Moodle | Shared question banks, categories, permissions, question versions, imports/exports, and item statistics | Institutional content reuse and maintainable questions are long-term assets, separate from generating a new draft |
| Questionmark / Author Aide | AI drafting inside an assessment lifecycle with human review, item banking, complexity controls, integrations, and data-handling commitments | Quality governance and procurement confidence are part of the product, not documentation added after launch |

Sources: [Wayground document import](https://help.wayground.com/support/solutions/articles/158000405095-wayground-ai-turn-worksheets-question-banks-more-into-interactive-assessments), [Wayground common assessments](https://help.wayground.com/support/solutions/articles/158000411400-create-a-common-assessment-for-admins-coordinators), [Wayground integrations](https://help.wayground.com/support/solutions/158000380622), [Kahoot! EDU](https://kahoot.com/schools/edu-school-and-district/), [Quizgecko for schools](https://quizgecko.com/for/schools), [Moodle question banks](https://docs.moodle.org/502/en/Question_bank), [Questionmark Author Aide](https://www.questionmark.com/platform/author-aide/).

These are established institutional offerings. Questionmark reports 750+ organizational customers; Wayground reports teachers in 90% of US schools and 150+ countries. Treat those as vendor claims, and do not confuse teacher presence with paid district contracts. The University of Bristol also documents historical use of Questionmark for practice and examinations; that is independent customer evidence of institutional use, not proof of its current AI quality. [Questionmark platform](https://www.questionmark.com/platform/), [Wayground schools](https://wayground.com/home/schools-and-districts), [Bristol case study](https://www.bristol.ac.uk/digital-education/case-studies/pre-2018/online-assessment-for-practice-and-exams/)

**Positioning hypothesis to test:** "Turn your institution's own notes and past papers into source-linked, faculty-approved practice assessments, with less checking and no lost work." Start with a defined curriculum and supported file types. Do not initially promise every subject, every document, and examination-grade correctness.

Competitors also have limits. Wayground's cited import documentation states that only the first 16,000 characters of an uploaded file are processed and instructs teachers to review generated content. The same page documents preserving existing images and adding media during editing. Treat transparent long-document coverage and faithful visual imports as opportunities to validate, rather than assuming established products already solve every source-reliability problem. [Wayground import capabilities and limits](https://help.wayground.com/support/solutions/articles/158000405095-wayground-ai-turn-worksheets-question-banks-more-into-interactive-assessments)

An institution may buy for faculty time saved, a reusable owned question bank, curriculum alignment, or digitizing legacy papers. Those are different products with different priorities. Interview buyers before expanding all four simultaneously.

## 4. Critical faculty/AI findings

### F01 — Existing-paper imports can lose the evidence that identifies the answer

**Confirmed; pilot blocker for affected formats.**

The extraction prompt says bold/underlined choices can identify the correct answer. The typed-document path first flattens the document into text. DOCX extraction uses `Paragraph.text` and table-cell text, which discard bold and underline markers. Plain PDF text likewise does not preserve all visual answer markings.

Local reproduction: a DOCX with bold `B. 4` and an otherwise identical DOCX with no bold mark produced exactly the same extracted text. The downstream model cannot recover a distinction that no longer exists in its input.

**Customer consequence:** a faithful import turns into an undisclosed answer-inference task. A teacher who trusts the original paper must now re-solve its questions.

**Required behavior:** preserve formatting/layout evidence where supported; record whether an answer was copied from a key, copied from a marking, inferred, missing, or contradictory. Missing/inferred answers must remain unresolved until explicitly reviewed. A vision fallback should be triggered by page/document evidence, not just a filename.

Evidence: `backend/app/services/extraction.py:158`; `backend/app/services/extraction_prompts.py`; `backend/app/services/quiz_extraction.py:179`.

### F02 — Chunked extraction cannot reliably match a separate answer key

**Confirmed architectural limitation; pilot blocker for long papers with keys.**

`_chunk_text` divides text by character/paragraph budget. Each chunk is independently sent to the extractor. There is no separate full-document answer-key parser and no stable original question/section identifier in the output contract. Questions near the beginning may never be processed with the key at the end. Oversized paragraphs can be split inside a question or option list.

A synthetic probe confirmed that the first question's chunk excludes the final answer key. This proves missing context, not a measured rate of wrong model answers.

**Required behavior:** detect document sections and question boundaries; identify source numbers including section prefixes; extract the key independently; join it deterministically; preserve disagreements and unmatched keys. Importing an answer is distinct from solving a question.

Evidence: `quiz_extraction.py:93`, `:139`, `:151`; `extraction_prompts.py`.

### F03 — Deduplication deletes distinct questions with identical stems

**Confirmed by local reproduction; pilot blocker.**

Extraction deduplicates only normalized `question_text`. Two items reading "Which statement is correct?" with different options were reduced from two questions to one in an isolated probe. Such repeated stems are legitimate in papers.

**Required behavior:** preserve source occurrence IDs and deduplicate only proven repeated extraction of the same occurrence. Include passage, options, source location, type, and answer when assessing content similarity. Never delete a source question merely because its stem repeats.

Evidence: `quiz_extraction.py:119`.

### F04 — Faculty cannot see a complete import reconciliation report

**Confirmed; pilot blocker.**

Malformed extracted items are skipped; a numerical `skipped` count is returned, but the upload UI immediately navigates to review without showing a reconciliation summary. Per-item confidence is stored as `confidence_score`, while the review-detail query does not select it. The main review card displays generation grounding fields instead.

**Customer consequence:** "Quiz extracted" can mean some items were omitted and some answers were uncertain, without telling faculty which originals require attention.

**Required behavior:** an import receipt listing detected source items, imported items, unresolved items, unsupported items, and every exclusion with a reason/source location. Make confidence/provenance visible as actionable review states. Preserve incomplete question drafts rather than discarding them silently. Model confidence is not a calibrated accuracy percentage.

Evidence: `quiz_extraction.py:298`, `:364`; `backend/app/services/review.py:70`; `frontend/components/teacher/quiz-extractor.tsx:123`.

### F05 — Mixed scanned/text PDFs can be treated as fully readable text

**Confirmed routing behavior; document-dependent risk.**

The importer chooses the text path when the PDF's total extracted text exceeds a threshold. A readable cover/introduction can satisfy that threshold even when the actual questions are scanned. Study-material upload separately rejects wholly unreadable scans, but that is not a page-by-page completeness check.

**Required behavior:** compute a per-page extraction manifest. Classify readable text, scanned/low-text, tables, and image-dependent content; route pages appropriately or clearly mark unsupported coverage. Initially rejecting an unsupported document is preferable to implying full coverage.

Evidence: `quiz_extraction.py:179`; `backend/app/api/documents.py`; `backend/app/services/extraction.py`.

### F06 — Review controls allow uncertainty to disappear into bulk approval

**Confirmed product-policy weakness, not an authorization bypass.**

Bulk approval excludes only `unsupported`; `ambiguous` and `needs_teacher_review` are eligible. The edit form sends question text and explanation on every save, even if unchanged. The backend checks whether those fields were submitted, not whether their values changed, and changes verification status to `needs_teacher_review`, which is then approvable. Answer-shape validation runs, but the original evidence/quality issue is not reverified. This directly explains the founder's Edit → Save workaround at the code level. Saving does not establish that the question has become correct. The code deliberately provides an edit escape hatch, but there is no recorded resolution reason or evidence acknowledgment separating intentional teacher correction from a no-change save. Bulk approval also lacks the per-question event trail used by individual approvals.

`Unsupported` is an umbrella validation outcome, not necessarily an unsupported question type or a wrong answer. Causes include invalid answer structure, absent/unmatched source evidence, generic explanations, and duplicate checks. The exact reason for the founder's three blocked questions cannot be established without their warning records and source content. Some rules can also reject legitimate questions; the formula example in F08 demonstrates one overly broad policy. Show specific, actionable reasons rather than encouraging faculty to clear a label.

**Required behavior:** a no-change save preserves verification status. A meaningful edit invalidates the old check and runs the relevant validation again. Bulk-approve only explicitly eligible low-risk items. For ambiguous, missing-key, edited-after-verification, or verifier-unavailable items, require an individual resolution action and record reason, reviewer, item version, and time. Provide a deliberate teacher resolution/override with evidence and a reason where policy permits it; keep that separate from automatic verification. Recheck publication eligibility server-side against the exact version being published. Do not solve this by simply running another model and trusting its label.

Evidence: `backend/app/api/quiz.py:874`; `backend/app/api/questions.py:145`, `approve_question`; review-page approvability filter.

### F07 — The verifier supports trust, but its label is stronger than its evidence

**Confirmed architecture; quality risk requires human benchmarking.**

Generation and verification use the same general provider routing. The deterministic check establishes that an excerpt occurs in supplied material. The AI verifier receives the generated question, answer, explanation, and selected excerpt; it does not receive the complete original passage context. A real quote can still omit a limiting condition. Related models can also share errors.

The UI renders the generator's own `grounding_confidence` as a percentage. That number has not been demonstrated to mean probability of correctness. "Evidence verified" must not imply that mathematical correctness, pedagogy, source truth, and learner suitability are all proven.

**Required behavior:** distinguish source match, answer validation, ambiguity, formatting, and teacher approval. Pass sufficient original context to verification. Use deterministic arithmetic/unit checks where feasible and a separately evaluated reviewer for difficult items. Calibrate any confidence presentation using human labels; otherwise use descriptive statuses. Human review remains authoritative.

Evidence: `question_verification.py:73`, `:93`; `question_grounding.py`; `question-review-card.tsx:273`.

### F08 — Pedagogical policy is too rigid in some places and too weak in others

**Confirmed constraints; product gap.**

The API exposes one global easy/medium/hard choice and theory/practical/mixed, rather than a blueprint of learning objectives and cognitive demand. Topic capacity is a heuristic (for example, one formula contributes three possible questions), not a measured guarantee of usable variety.

The system prompt says to write fewer questions when material is thin, while the request contract requires exact counts. The result can be retries/failure, or low-value variants. The correction request rewrites the entire batch, potentially replacing otherwise good items.

A synthetic probe also confirmed that a valid provided-formula application question is rejected because the stem contains its source formula. That rule is suitable for some recall tests but is not universal: an open-book application question can legitimately provide a formula.

**Required behavior:** capture assessment intent, learner level, objectives, allowed supports, and difficulty mix; provide presets rather than forcing faculty to populate an enormous grid. Run evidence-capacity checks before promising counts. Return an explicit shortfall for the teacher to accept or resolve. Repair individual failed slots and preserve accepted items.

Evidence: `topic_capacity.py:6`; `question_validation.py:59`; `blueprint_prompts.py`; `blueprint.py:218`; `api/quiz.py:111`.

### F09 — Long operations remain dependent on browser connections and process lifetime

**Confirmed design; pilot blocker at institutional use.**

Final generation is synchronous with a 90-second frontend deadline. Provider attempts, correction, verification, and fallback can exceed it. Paper extraction also remains a request-bound multi-call operation. A browser timeout does not establish whether a draft was eventually saved, and retry is not protected by a complete idempotent job/result contract.

Large-document analysis uses daemon threads. Polling-based stale detection is an improvement, but it is not a durable scheduler. The current defaults permit 600-second large-provider attempts and a 900-second stale-job cutoff. Multiple fallbacks/retries or a long map phase can outlast that cutoff without a job heartbeat, so polling can declare live work failed. Late workers can still write results.

**Required behavior:** durable jobs for analysis, generation, extraction, and regeneration where slow; atomic claims, leases/heartbeats, bounded retries, fencing against late writers, idempotent final persistence, cancellation, and restart recovery. The browser should recover job status after reload and receive a stable result ID.

Evidence: `frontend/lib/api.ts:1784`, `:1849`; `generation_jobs.py:290`; `api/quiz.py:406`; `config.py:262`, `:273`.

### F10 — Rate limiting is not a commercial usage or cost model

**Confirmed implementation; operational/economic risk.**

Large-document profiling, map chunks, and reduction consume the same topic-extraction bucket. Its current code default is 30/hour. A no-retry run with 29 chunks plus profiling and reduction needs at least 31 reservations, even when the user performed only one logical analysis. Other recent calls make the boundary smaller. Conversely, one top-level generation request may incur several paid provider calls.

There is no measured end-to-end per-job token/cost ledger in the reviewed provider interface. The configured `gemini_blueprint_model` is not used by the standard blueprint path: it calls `complete_json_with_fallback`, which routes through `GeminiProvider` using `gemini_model`. Configuration comments describing a cheaper blueprint model can therefore mislead cost planning.

**Required behavior:** separate abuse limits, concurrent-job limits, provider limits, and purchased institutional credits. Estimate/reserve a job budget, meter every provider attempt, settle actual usage, and release unused reservations. Bound work per tenant so one large upload cannot dominate the service. Expose fair, understandable usage to admins.

Evidence: `topic_extraction_pipeline.py:167`; `master_blueprint_synthesizer.py` reduction quota; `generation_jobs.py` profiling quota; `config.py:286`; `llm/structured.py:96`; `llm/gemini.py:42`.

### F11 — The quality harness does not test the main faculty journey

**Confirmed; release-readiness gap.**

The local harness is valuable, but untracked. `evals/sut.py` invokes small-document blueprint generation directly with `selected_topics=[]`. It does not establish quality for the actual per-topic UI, large-document route, existing-paper import, or interrupted/retried requests. Its estimated generation cost approximates input/output size and does not meter all profiling/correction/verification/fallback calls.

AI judging is also not equivalent to subject-expert labels. Ordinary unit tests protect contracts but cannot establish that questions are educationally appropriate.

**Required behavior:** version a sanitized evaluation runner and licensed/synthetic fixtures; keep confidential customer documents outside source control. Cover real user routes and all document paths. Create human-reviewed reference sets and a holdout set; use AI judges as assistance with measured agreement. Record domain/type-specific error rates and reviewer effort, not just an average judge score.

Evidence: `evals/sut.py:170`; `evals/runner.py:44`; `.github/workflows/ci.yml`.

### F12 — Question reuse and departmental collaboration are incomplete

**Product gap; early-sales priority when institutions request it.**

Questions and quizzes persist, but faculty workflows center on their own created quizzes. There is no equivalent faculty-facing shared institutional item-bank workflow with permissioned collaboration, reviewer assignment, item history, search by objective/evidence, and deliberate assembly of new assessments from approved items. The super-admin question-bank view is not a substitute for this workflow.

**Required behavior:** start with a searchable teacher library and reuse/duplicate actions, then permissioned department sharing. Introduce question versions and immutable published assessment versions; existing attempt snapshots should remain. Do not broaden `created_by` filters without designing subject/department authorization and testing cross-tenant boundaries.

Moodle demonstrates shared banks and selectable question versions; Questionmark places reviewed items into an institutional assessment lifecycle. [Moodle banks](https://docs.moodle.org/502/en/Question_bank), [Questionmark authoring](https://www.questionmark.com/platform/flexible-authoring/)

### F13 — Faculty review still requires unnecessary context switching

**Product gap and confirmed interface limitation.**

The review card shows excerpts/pages and provides edit/approve/reject/regenerate. It does not provide a synchronized source-page viewer or the missing import reconciliation described above. Generation settings and active job state are primarily component state. Standard HTML text and PDF text components are used rather than structured math/code/media rendering.

**Required behavior:** source beside question; unresolved issues first; keyboard-efficient review; replace one item with a reason; preserve instructor edits and generation briefs; preview exactly what students and exported papers will see. Math and media rendering must cover the promised pilot domains; required pictures/diagrams/graphs are specified in F17. A new visual theme is not the priority.

Evidence: `frontend/components/teacher/question-review-card.tsx`; `blueprint-generator.tsx`; `frontend/lib/pdf/documents.tsx`.

### F14 — Student weaknesses and question defects need different analytics

**Product gap.**

Existing class and student analytics are useful. A low score, however, might indicate poor teaching, an unclear question, an incorrect key, or an unhelpful distractor. Faculty need item-level response distributions, omission rates, revision history, and later discrimination statistics tied to stable item versions. Small cohorts and prior question exposure limit interpretation.

**Required behavior:** initially show per-option choices, accuracy, sample count, and reported defects; add teacher decisions to revise/retire. Add psychometric indicators only with sample-size warnings. Support an auditable correction/regrade policy before positioning for graded examinations. Snapshots preserve history but do not themselves supply a grade-correction workflow.

Moodle explicitly supports investigating potentially broken questions through item statistics and handling variants with different observed difficulty. This is an assessment-maintenance capability, not another AI generation feature. [Moodle statistics](https://docs.moodle.org/502/en/Quiz_statistics_report)

### F15 — Distribution and procurement need a deliberately scoped first version

**Product gap; customer-dependent priority.**

PDF exports already exist. I did not find QTI/Moodle export or an LMS grade-passback workflow in the reviewed application. Institutions also need documented onboarding, content ownership, role assignment, support, backups, deletion/retention, and usage limits. Account-erasure code and archive features exist; they should not be described as absent. What remains unverified is a complete operational policy and evidence that it works across storage, jobs, backups, and providers.

**Required behavior:** choose one delivery route required by the first customer: existing in-app student delivery, printable paper, or one tested LMS export. QTI is a standard for exchanging assessment content, but compatibility must be tested with a specific LMS/version and supported question types; it is not a universal one-click guarantee. [1EdTech QTI](https://www.1edtech.org/standards/qti)

Provider fallback also sends source material to another provider. Do not promise particular data handling until the customer's allowed provider list, actual paid account settings, and terms are confirmed. Google's Gemini API terms distinguish unpaid and paid-service data use and include regional qualifications; a paid ChatGPT/Gemini consumer subscription is not proof of the API project's data terms. This review did not inspect your account. [Gemini API terms](https://ai.google.dev/gemini-api/terms)

### F16 — Publication and practice-bank visibility have different rules

**Confirmed behavior; policy decision needed before formal assessments.**

Published quiz attempts require a published set. Practice selection instead draws approved questions in enrolled subjects/chapters, without requiring a published parent quiz. A teacher can therefore approve material intended for a future test and make it eligible for practice before formally publishing that test.

**Required behavior:** separate authoring/review status from delivery eligibility. Define whether an item is practice-eligible, assessment-only, scheduled, retired, or embargoed. Apply that policy consistently to practice, challenges, tutor/revision access, and exports. Do not represent the current system as protecting exam secrecy through publication alone.

Evidence: `backend/app/services/selector.py`, both selection functions; `backend/app/api/student.py` published-attempt checks.

### F17 — Pictures, diagrams, and graphs require support across the whole question lifecycle

**Confirmed current text-oriented limitation; explicit founder requirement for the first product scope.**

Adding an image upload button alone will not preserve a source diagram during extraction, give the generator access to it, or keep it attached in student delivery and printed papers. A graph's axes, units, legend, and numerical values are part of the assessment, not decoration. Image-dependent questions must not silently become text-only questions.

**Required behavior, delivered in increments:**

1. Faculty can attach an existing picture/diagram to a question or answer option, preview it, replace it, and provide an appropriate accessible description. Support safe image formats, size/dimension limits, private tenant storage, authorized access, and immutable asset references in released question versions and attempt snapshots.
2. Supported paper imports preserve source figures using page/region references and image assets, with a teacher confirming which question/options each figure belongs to. Unsupported or unreadable figures appear explicitly in reconciliation. Multi-question passages can share a figure without losing that relationship. Source extraction and generation must actually receive the required image/context; storing an attachment alone is insufficient.
3. For newly authored data graphs, use editable structured data and deterministic rendering so axes, scales, units, plotted values, and answer calculations agree. Validate common chart types before expanding. AI may suggest data/specifications, but a generated bitmap is not evidence of numerical correctness.
4. Use the same versioned question content in faculty review, student attempts, PDF/print, and supported exports. Test image choices, page breaks, mathematical notation, zoom, accessible descriptions, and mobile display. Descriptions must enable access without inadvertently disclosing an answer.

Arbitrary AI-drawn scientific diagrams and unrestricted visual reasoning can follow later after subject-specific validation. The first release must already support faculty-supplied visuals and a documented subset of source-preserved figures and graphs. If an LMS export cannot represent a supported item, report that limitation explicitly.

Evidence: `frontend/components/teacher/question-review-card.tsx`; `frontend/lib/pdf/documents.tsx`; extraction output/persistence in `backend/app/services/quiz_extraction.py`.

## 5. Recommended architecture changes, without a rewrite

Keep Next.js, FastAPI, Supabase, and the existing question types. Extend the validated question schema with versioned media/content blocks and add explicit lifecycle contracts around the pipeline.

1. **Document intake:** store a document version/hash and immutable source blocks with page/location, text, formatting/media references, extraction method, and coverage warnings. Document content is untrusted data; include prompt-injection fixtures and constrain model output to the task. Never give document text authority over system instructions or tool actions.
2. **Two processing paths:** authored-paper import preserves occurrences/keys and reports reconciliation; new-question generation takes a teacher-approved assessment brief and evidence selection. Share source/provenance infrastructure, not conflicting answer policies.
3. **Durable job execution:** a database-backed queue with a separate worker process is a reasonable initial fit. Use atomic claim/lease operations, heartbeats, lease generations, bounded retries, tenant limits, and transactional result creation. Avoid introducing several infrastructure systems merely to solve background work. Evaluate a managed queue if measured needs justify it.
4. **Generation brief:** persist curriculum version, learner level, objective/topic/type counts, difficulty distribution, permitted formula/reference supports, language, and source scope. Keep a short preset-driven default UI.
5. **Candidate and validation stages:** generate evidence-linked candidates; enforce structure, key validity, provenance, counts, duplicates, and domain-specific checks; use model review where beneficial; repair failed slots within a bounded budget. Explicitly report insufficient evidence.
6. **Review and release:** source-assisted resolution of warnings; draft item versions; deliberate human overrides; immutable release versions; independent practice eligibility; retained attempt snapshots.
7. **Measurement:** durable run and review metadata: tenant, request/job ID, source/version IDs, prompt/config version, actual model/provider, tokens, attempts, latency, validation outcomes, faculty changes, and final item/result IDs. Avoid storing full source text in operational logs. Best-effort analytics events are not an adequate billing/audit ledger.

**RAG decision:** retrieval is a means of choosing evidence, not an accuracy guarantee. Short clean chapters can continue using bounded full context. For large/multiple documents, first use stable source blocks and topic mappings to retrieve original passages; add lexical/vector retrieval only where benchmarks show missed relevant evidence. Your current map/reduce pipeline can remain a topic index, but the question writer should be able to obtain verified original context. Do not add a vector database or fine-tune a model before measuring this need.

## 6. Proposed implementation sequence for approval

Estimates are planning ranges for two developers familiar with this repository, not commitments. Dependencies, customer document complexity, and review availability can change them. Keep changes in small reviewable PRs, apply migrations additively, and pilot behind institution-level feature flags.

| Phase | Scope and deliverables | Exit evidence | Rough effort |
| --- | --- | --- | --- |
| 0 — Baseline and pilot definition | Pick one buyer/use case, document supported inputs, collect representative permissioned materials, instrument existing run/review metrics, promote sanitized evaluation runner | Written acceptance criteria; timed manual-versus-product baseline; labeled fixtures for all promised routes | 3–5 engineer-days plus faculty sessions |
| 1 — Stop silent errors | Fix extraction dedup; expose skipped/unresolved items and confidence/provenance; restrict bulk approval; distinguish practice eligibility; provide controlled errors for malformed answers | Every known synthetic failure has a regression; unresolved answer cannot reach release accidentally; draft/embargoed content excluded from practice by policy | 5–8 engineer-days |
| 2 — Reliable asynchronous jobs | Shared lifecycle for final generation and paper extraction; durable worker, idempotency, leases/fencing, cancellation, status recovery, quotas and usage records | Refresh/restart/concurrent retry/worker crash tests pass; one request produces one saved result; no stale worker overwrites | 8–12 engineer-days |
| 3 — Faithful sources and better candidates | Question-aware import, independent key join, formatting/page manifest, mixed-PDF handling or explicit rejection, evidence-capacity/shortfall behavior, selective repair, verification context | Human-labeled import/generation fixtures pass agreed gates; no unexplained missing source items; preserved numbering/options/key provenance | 8–15 engineer-days |
| 4 — Required visual questions | Versioned images for stems/options, private asset delivery, supported source-figure preservation, initial structured graphs, consistent review/student/PDF rendering | Representative diagrams/graphs retain labels, values, association, and answer correctness across the complete journey; cross-tenant asset denial and historical snapshots verified | 10–16 engineer-days |
| 5 — Faculty adoption and reuse | Persist briefs, source-assisted review, warning resolution, teacher item library, edit/reuse/version workflow, one buyer-required export path | Faculty complete repeated end-to-end tasks without developer help; measured reduction in review/creation time | 7–12 engineer-days |
| 6 — Paid-pilot operations | Staging migration validation, backup/restore drill, tenant-boundary and deletion tests, support runbook, usage dashboard, customer-specific provider/data policy | Successful real-institution pilot, restore proof, incident drill, documented service limits and onboarding | 4–7 engineer-days plus 2–4 calendar weeks observing use |

Total planning range with required visual support: 45–75 engineer-days. For two people also handling support and product work, roughly 8–12 calendar weeks is a provisional planning window, not a delivery promise. Define subjects, supported document layouts, graph types, and actual workload during Phase 0 before committing dates. Pilot preparation and measurement can overlap development. Validate with one coaching institute and one college first, then expand to the intended 5–10 institutions. Do not authorize this entire backlog as one oversized PR.

**First implementation tranche to approve:** Phases 0 and 1, with the Phase 2 job interface and Phase 4 content/asset contract designed early. They produce measurable quality baselines and prevent avoidable silent failures, including the no-change-save approval gap. Complete Phase 2, the supported-input portion of Phase 3, and the agreed visual scope in Phase 4 before calling the requested product ready for self-service use. Media is required scope, not an optional cosmetic enhancement.

## 7. Acceptance tests and product metrics

The following are proposed gates to negotiate with pilot faculty, not measured current performance.

### Source/import gates

- Gold fixtures include inline keys, end-of-paper keys, repeated numbering by section, bold/underline answers, absent keys, conflicting keys, repeated stems with different options, tables, multi-column layouts, mixed scanned/text pages, long papers, supported diagrams/graphs/image choices, and clearly unsupported visual formats.
- Every detected source item has an imported/unresolved/unsupported/excluded state and a location. Automated detection recall is separately checked against human enumeration; a reconciliation total cannot prove recall by itself.
- No inferred answer is labeled as source-provided. In the release fixtures, no source-provided key is silently changed; conflicts block ordinary approval until resolved.
- Review/display/export preserve the supported symbols, option order, and evidence. Maintain round-trip fixtures for the selected export target.
- A no-change edit/save cannot turn an unsupported item into an ordinarily approvable item. A genuine correction receives relevant revalidation; a permitted teacher override records its reason and the exact item version.
- Visual fixtures preserve figure-to-question association, axes/units/legends, image choices, and expected numeric answers. Replacing an asset does not alter an already released assessment or historical attempt.

### AI quality gates

- Initial benchmark: 30–50 representative permissioned/synthetic documents and at least 300 human-reviewed items spread across the pilot's supported subjects and input types; expand for long/multimodal documents. Include all faculty paths, not only direct service calls.
- Score answer correctness, ambiguity, distractor validity, objective match, source support, difficulty fit, duplicate rate, and notation fidelity separately.
- Suggested formative-pilot target: at least 95% human-judged answer correctness before faculty edits on the supported benchmark; no known unresolved wrong keys in the final release candidate; explicit review of every high-risk item. Adjust upward for higher-stakes use.
- Report confidence intervals and results by domain, file route, and question type. A clean sample is not proof of zero errors; question clusters from the same source reduce effective sample size.
- Calibrate model-judge agreement against expert judgments and audit disagreements. Keep a held-out document set so prompt tweaks cannot merely overfit familiar examples.

### Reliability and tenancy gates

- Repeating the same submission/idempotency key returns the same job/result; intentionally starting a new quiz uses a new key.
- Kill a worker during extraction, generation, and final save; restart and recover without duplicate quizzes or double usage settlement.
- A late response from a cancelled/expired lease cannot modify the new job result.
- Client refresh/network loss resumes status and preserved faculty inputs.
- Provider 429/5xx/timeout/malformed JSON produces bounded retry or a resumable terminal state, not an endless spinner.
- Cross-tenant jobs, documents, item-bank entries, signed-source access, shared-review actions, and exports deny unauthorized access.
- Queue acknowledgement target: p95 under two seconds in the agreed load fixture, separate from total processing time. Set total generation latency promises only after measurement, by document size/type.
- Agree pilot concurrency with founders; until then use a synthetic 10-simultaneous-job fixture for engineering validation, explicitly not a capacity claim.

### Faculty value and commercial gates

- North-star outcome: **teacher minutes to an approved, usable 20-question assessment**, including checking, corrections, and export—not time until the first draft appears.
- Track usable approved questions per teacher minute, edit/reject rate by reason, unresolved-import rate, first successful assessment, weekly returning faculty, support contacts, and repeat use on a second document.
- Suggested pilot business gate: median end-to-end faculty time at least 30% lower than the same faculty's normal workflow, with no regression in expert-reviewed output quality. This is a proposed target, not a current claim.
- Observe 3–5 faculty per design-partner institution across at least two cycles of creating, assigning/exporting, reviewing results, and reusing content.
- Record actual model usage, OCR/extraction, retries, storage, and support cost. Define cost per **approved usable question**, including failed/discarded candidates. The existing approximate token-cost report is not sufficient for pricing.

## 8. Forward-deployed pilot playbook

1. Interview the purchaser, department lead, and two working faculty members separately. Ask for the last real paper they created, their current workflow, review responsibility, delivery method, and time spent.
2. Obtain permissioned representative files before a demo. Include a normal document, the institution's hardest common document, and an existing keyed paper. Agree unsupported cases explicitly.
3. Have a subject expert prepare source-item/answer references and time the normal workflow. Do not substitute a generic AI judge for the faculty's curriculum expectations.
4. Run an observed end-to-end session in a staging/pilot tenant. Capture where faculty stop, distrust the output, or need help. Measure active review time separately from waiting time.
5. Repair repeated blockers, not every one-off customization. Record institution settings separately from general product behavior.
6. Demonstrate the second-use journey: same teacher returns, reuses source/items, changes an assessment, and gets the required export. This reveals retention value better than a polished first upload.
7. Review metrics weekly with the customer. Agree who responds to incorrect questions, recovery failures, and content-deletion requests. Keep support access explicit and audited.
8. Convert to a broader paid rollout only after quality, reliability, privacy, and measurable time-saving gates are met. A managed paid design partnership is a different promise from unrestricted self-service SaaS.

## 9. Build now, validate first, defer

**Build now after approval, in the phases above:** silent-loss fixes; uncertainty/provenance visibility; safe approval rules; durable/idempotent jobs; real usage tracking; source reconciliation; required pictures/diagrams/graphs and associated rendering; actual faculty-path evaluations; saved work and support diagnostics.

**Validate with the first buyers:** shared department banks, learning-outcome mappings, bilingual output, breadth of mathematical notation and scanned-paper support, semester/section workflows, LMS export, co-review approval roles, graded-exam requirements, and actual concurrency. These can become release blockers for a college buyer even if they are not needed by a narrow coaching pilot. This discovery refines visual scope; it does not remove the founder's explicit visual requirement.

**Defer unless contracted:** replacing an LMS, building proctoring, unrestricted essay grading, every language/subject, fine-tuning, elaborate multi-agent generation, a large integration catalog, and additional gamification. Do not build formal-exam controls by treating browser focus detection as proof of academic integrity.

A payment gateway is not the first blocker. A small pilot can use agreed institutional invoicing while you establish usage entitlements, support expectations, and measured unit economics.

## 10. Verification performed for this review

- Focused faculty/AI suite: **112 tests passed, 9 subtests passed**, using UTF-8 Python mode and disabling pytest cache writes.
- Synthetic in-memory DOCX probe: bold-answer and unmarked documents produce identical extracted text.
- Synthetic extraction merge: two legitimate same-stem/different-option questions become one.
- Synthetic long-paper split: the question chunk does not contain the terminal answer key.
- Presentation-policy probe: a provided-formula application question is rejected by the universal formula rule.
- Code traced for quota accounting, confidence persistence versus review display, approval gates, model routing, job recovery, source selection, and evaluation-path coverage.

No live AI generations, customer-data experiments, production load tests, live DB inspection, or paid competitor trials were run. Existing unit-test success is not evidence of question quality or deployed readiness. The synthetic probes demonstrate deterministic behavior; the report does not invent real-world error rates.

## 11. Approval boundary

Approve a bounded tranche and its acceptance criteria before implementation. The recommended starting scope is Phases 0–1, followed immediately by durable jobs, source/import reliability, and required visual support. Buyer categories and institution count are now confirmed; supported subjects/content, faculty workload, student concurrency, and examination stakes still determine final sequencing. No application changes should begin on the basis of this document alone.
