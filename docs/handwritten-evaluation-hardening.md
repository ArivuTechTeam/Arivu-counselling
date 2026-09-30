# Handwritten evaluation hardening

Migration 84 hardens the Phase A–D pipeline without adding the deferred
FacultyValidationRequest workflow.

## Queue recovery

An evaluation job has four total queue attempts: the initial attempt and three
retries delayed by 30, 60, and 120 seconds. `available_at` prevents an immediate
reclaim. Each processing attempt records `processing_started_at`; the lease
heartbeat does not change it.

The worker fences a job after 780 seconds even when its heartbeat is still
fresh. If provider code has still not returned at 840 seconds, the single-job
worker process exits so its container supervisor can replace it. The poll loop
also invokes the database reaper every 60 seconds, allowing a healthy worker to
recover jobs left behind by a dead or wedged replica.

A submission whose fixed rubric failed ends in `blocked_rubric_failed` with a
clear message. Successfully regenerating that paper's rubric automatically
returns blocked submissions to `stage1_complete` and requeues Stage 2.

Stage 2 `review` results contain committed marks, so Phase D learning derivation
runs after both `evaluated` and scored-`review` results. A wholly illegible Stage
1 extraction can also stop with submission status `review`, but has no evaluation
row or marks; that distinct case does not run learning and remains dependent on
the explicitly deferred FacultyValidationRequest/manual-review workflow.

## Student attempts and source files

`HANDWRITTEN_EVALUATION_ATTEMPTS_PER_PAPER` defaults to 2. Only a committed row
in `handwritten_evaluations` consumes an attempt. Failed provider calls,
timeouts, failed rubrics, and other system failures consume no lifetime attempt.
An unfinished failed submission retries in place; re-evaluating a completed
submission creates a new immutable row linked through `regraded_from`.
New submissions and regrades share an atomic per-student/per-paper lock. Active
jobs reserve the remaining capacity so concurrent requests cannot exceed the
limit, but the reservation disappears when a technical attempt fails.

Additional pages use their own verified upload intent, scoped to the owning
student and submission. Attaching the file clears the cached Stage 1 transcript
and requeues the same submission. Stage 1 then sends the primary script and the
additional document together with distinct document indexes.

## Historical and audit safety

Submissions snapshot the paper title and subject name when created. Deleting a
paper sets `evaluation_paper_id` to null instead of cascading through student
history; reports fall back to the snapshots and persisted evaluation total.
Raw Stage 2 artifacts remain service-role-only in the database and are exposed
only through the tenant-scoped institution-admin audit endpoint.

`mcq_marks` is optional. When present, the fixed rubric and Stage 2 summary use
`total_marks - mcq_marks` as the descriptive grading denominator.

FacultyValidationRequest remains deliberately absent. Nothing in this recovery,
retrigger, or regrade flow assumes a faculty dispute/review record exists.
