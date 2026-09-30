"""Leased handwritten-evaluation worker (rubric, transcription, and scoring)."""
from __future__ import annotations

import logging
import os
import signal
import threading
import time
from collections.abc import Callable
from uuid import uuid4

from app.lib.auth import CurrentProfile
from app.lib.config import get_settings
from app.lib.supabase import get_service_client
from app.services.evaluation_access import student_can_access_paper
from app.services.evaluation_stage1 import (
    Stage1PermanentError,
    run_stage1,
    stage1_blocks_grading,
    stage1_requires_review,
)
from app.services.evaluation_rubric import RubricPermanentError, build_rubric
from app.services.evaluation_learning import (
    create_mistakes,
    reconcile_revision_items,
    update_student_analytics,
)
from app.services.evaluation_stage2 import Stage2PermanentError
from app.services.evaluation_stage2_runner import run_stage2, stage2_summary


logger = logging.getLogger(__name__)


def _run_learning_follow_on(service, *, evaluation_id: str, submission: dict,
                            paper: dict) -> None:
    """Run independent, non-fatal learning steps after the score commit."""
    tenant_id = str(submission["tenant_id"])
    student_id = str(submission["student_id"])
    subject_id = str(paper["subject_id"])
    try:
        create_mistakes(service, tenant_id=tenant_id, evaluation_id=evaluation_id)
    except Exception as exc:
        logger.warning("Mistake derivation failed after evaluation commit (%s)", type(exc).__name__)
    try:
        reconcile_revision_items(
            service, tenant_id=tenant_id, student_id=student_id, subject_id=subject_id,
        )
    except Exception as exc:
        logger.warning("Revision reconciliation failed after evaluation commit (%s)", type(exc).__name__)
    try:
        update_student_analytics(
            service, tenant_id=tenant_id, student_id=student_id, subject_id=subject_id,
        )
    except Exception as exc:
        logger.warning("Analytics update failed after evaluation commit (%s)", type(exc).__name__)


def _rpc_bool(service, name: str, parameters: dict) -> bool:
    return bool(service.rpc(name, parameters).execute().data)


def _authorized_submission(service, job: dict) -> bool:
    submission_result = (
        service.table("handwritten_submissions")
        .select("id,tenant_id,student_id,evaluation_paper_id")
        .eq("id", job["submission_id"])
        .eq("tenant_id", job["tenant_id"])
        .eq("student_id", job["owner_student_id"])
        .maybe_single()
        .execute()
    )
    if not submission_result or not submission_result.data:
        return False
    profile_result = (
        service.table("profiles")
        .select("id,tenant_id,role")
        .eq("id", job["owner_student_id"])
        .eq("tenant_id", job["tenant_id"])
        .maybe_single()
        .execute()
    )
    tenant_result = (
        service.table("tenants")
        .select("is_active,handwritten_evaluation_enabled")
        .eq("id", job["tenant_id"])
        .maybe_single()
        .execute()
    )
    if (
        not profile_result
        or not profile_result.data
        or profile_result.data.get("role") != "student"
        or not tenant_result
        or not tenant_result.data
        or not tenant_result.data.get("is_active")
        or not tenant_result.data.get("handwritten_evaluation_enabled")
    ):
        return False
    paper_result = (
        service.table("evaluation_papers")
        .select("id,tenant_id,course_level_id,subject_id,is_active")
        .eq("id", submission_result.data["evaluation_paper_id"])
        .eq("tenant_id", job["tenant_id"])
        .eq("is_active", True)
        .maybe_single()
        .execute()
    )
    if not paper_result or not paper_result.data:
        return False
    profile = CurrentProfile(
        user_id=job["owner_student_id"], tenant_id=job["tenant_id"], role="student"
    )
    return student_can_access_paper(service, profile, paper_result.data)


def _authorized_rubric(service, job: dict) -> bool:
    paper = (
        service.table("evaluation_papers")
        .select("id,tenant_id,created_by,is_active,rubric_status")
        .eq("id", job["evaluation_paper_id"])
        .eq("tenant_id", job["tenant_id"])
        .eq("created_by", job["owner_teacher_id"])
        .maybe_single().execute().data
    )
    profile = (
        service.table("profiles").select("id,tenant_id,role")
        .eq("id", job["owner_teacher_id"]).eq("tenant_id", job["tenant_id"])
        .maybe_single().execute().data
    )
    tenant = (
        service.table("tenants").select("is_active,handwritten_evaluation_enabled")
        .eq("id", job["tenant_id"]).maybe_single().execute().data
    )
    return bool(
        paper and paper.get("is_active") and paper.get("rubric_status") != "ready"
        and profile and profile.get("role") == "teacher"
        and tenant and tenant.get("is_active")
        and tenant.get("handwritten_evaluation_enabled")
    )


def _rubric_context(service, job: dict) -> dict:
    paper = (
        service.table("evaluation_papers")
        .select("id,tenant_id,course_level_id,subject_id,total_marks,mcq_marks,created_by,is_active,question_paper_storage_path,suggested_answer_storage_path,question_paper_text,suggested_answer_text")
        .eq("id", job["evaluation_paper_id"])
        .eq("tenant_id", job["tenant_id"])
        .eq("created_by", job["owner_teacher_id"])
        .eq("is_active", True).maybe_single().execute().data
    )
    if not paper:
        raise RubricPermanentError("Evaluation paper is no longer available.")
    return paper


def _stage1_context(service, job: dict) -> tuple[dict, dict]:
    submission = (
        service.table("handwritten_submissions")
        .select("id,tenant_id,student_id,evaluation_paper_id,answer_script_path,additional_pages_path,stage1_extraction,stage1_extraction_source,page_mapping,status")
        .eq("id", job["submission_id"])
        .eq("tenant_id", job["tenant_id"])
        .eq("student_id", job["owner_student_id"])
        .maybe_single().execute().data
    )
    if not submission:
        raise Stage1PermanentError("Submission is no longer available.")
    paper = (
        service.table("evaluation_papers")
        .select("id,tenant_id,generated_paper_id,subject_id,course_level_id,total_marks,mcq_marks,is_active,structured_qa,question_structure,rubric_source,rubric_status")
        .eq("id", submission["evaluation_paper_id"])
        .eq("tenant_id", job["tenant_id"])
        .eq("is_active", True)
        .maybe_single().execute().data
    )
    if not paper:
        raise Stage1PermanentError("Evaluation paper is no longer available.")
    if paper.get("generated_paper_id"):
        generated = (
            service.table("generated_papers").select("paper_payload")
            .eq("id", paper["generated_paper_id"])
            .eq("tenant_id", job["tenant_id"])
            .maybe_single().execute().data
        )
        if generated:
            paper["paper_payload"] = generated.get("paper_payload")
    return submission, paper


def run_one(
    service=None,
    *,
    worker_id: str | None = None,
    heartbeat_seconds: float = 20,
    soft_timeout_seconds: float | None = None,
    hard_timeout_seconds: float | None = None,
    hard_exit: Callable[[int], object] = os._exit,
) -> bool:
    """Claim one job and lease-safely persist its output."""
    service = service or get_service_client()
    worker_id = worker_id or str(uuid4())
    claimed = service.rpc("claim_evaluation_job", {"p_worker": worker_id}).execute().data
    if not claimed:
        return False
    job = claimed[0] if isinstance(claimed, list) else claimed
    done = threading.Event()
    settings = get_settings()
    soft_timeout = float(
        soft_timeout_seconds
        if soft_timeout_seconds is not None
        else settings.evaluation_job_soft_timeout_seconds
    )
    hard_timeout = float(
        hard_timeout_seconds
        if hard_timeout_seconds is not None
        else settings.evaluation_job_hard_timeout_seconds
    )
    if hard_timeout <= soft_timeout:
        raise ValueError("Evaluation hard timeout must be greater than soft timeout.")

    def heartbeat() -> None:
        while not done.wait(heartbeat_seconds):
            try:
                if not _rpc_bool(service, "heartbeat_evaluation_job", {
                    "p_id": job["id"], "p_worker": worker_id,
                }):
                    return
            except Exception as exc:
                logger.warning("Evaluation heartbeat failed (%s)", type(exc).__name__)

    def watchdog() -> None:
        if done.wait(soft_timeout):
            return
        try:
            watchdog_service = get_service_client()
            response = watchdog_service.rpc(
                "timeout_evaluation_job",
                {
                    "p_id": job["id"],
                    "p_worker": worker_id,
                    "p_reason": "Evaluation processing exceeded its safe duration.",
                },
            ).execute().data
            logger.error("Evaluation job soft timeout fenced job=%s result=%s", job["id"], response)
        except Exception as exc:
            logger.error("Could not fence timed-out evaluation job (%s)", type(exc).__name__)
        if done.wait(hard_timeout - soft_timeout):
            return
        logger.critical("Evaluation job hard timeout; terminating worker job=%s", job["id"])
        hard_exit(70)

    thread: threading.Thread | None = None
    watchdog_thread: threading.Thread | None = None
    try:
        rubric_job = job.get("kind") == "build_rubric"
        authorized = _authorized_rubric(service, job) if rubric_job else _authorized_submission(service, job)
        if not authorized:
            failure_rpc = "fail_evaluation_rubric_job" if rubric_job else "fail_evaluation_job"
            parameters = {"p_id": job["id"], "p_worker": worker_id, "p_retryable": False}
            if rubric_job:
                parameters["p_error"] = "Rubric job is no longer authorized."
            _rpc_bool(service, failure_rpc, parameters)
            return True
        if not _rpc_bool(
            service,
            "start_evaluation_job",
            {"p_id": job["id"], "p_worker": worker_id},
        ):
            return True
        thread = threading.Thread(target=heartbeat, daemon=True, name="evaluation-job-heartbeat")
        thread.start()
        watchdog_thread = threading.Thread(
            target=watchdog, daemon=True, name="evaluation-job-watchdog"
        )
        watchdog_thread.start()
        if rubric_job:
            paper = _rubric_context(service, job)

            def checkpoint(question_text: str, answer_text: str) -> None:
                if not _rpc_bool(service, "checkpoint_evaluation_rubric_texts", {
                    "p_id": job["id"], "p_worker": worker_id,
                    "p_question_text": question_text, "p_answer_text": answer_text,
                }):
                    raise RuntimeError("Rubric worker lease no longer held.")

            outcome = build_rubric(
                service, paper, job_id=job["id"], on_extracted=checkpoint,
            )
            finished = _rpc_bool(service, "finish_evaluation_rubric_job", {
                "p_id": job["id"], "p_worker": worker_id,
                "p_structured_qa": outcome.questions,
                "p_structure": outcome.question_structure,
                "p_source": outcome.source,
            })
        else:
            submission, paper = _stage1_context(service, job)
            stage1 = submission.get("stage1_extraction")
            requires_review = False
            if not isinstance(stage1, dict) or not stage1:
                outcome = run_stage1(service, submission, paper, job_id=job["id"])
                blocks_grading = stage1_blocks_grading(outcome.extraction)
                requires_review = outcome.requires_review
                finished = _rpc_bool(service, "finish_evaluation_stage1_job", {
                    "p_id": job["id"], "p_worker": worker_id,
                    "p_extraction": outcome.extraction, "p_source": outcome.source,
                    "p_mapping": outcome.page_mapping,
                    # The existing RPC's flag means stop before Stage 2. As in
                    # ExamApp, only a wholly illegible script does that; other
                    # extraction uncertainty completes grading and flags the report.
                    "p_requires_review": blocks_grading,
                })
                if not finished or blocks_grading:
                    return True
                submission["stage1_extraction"] = outcome.extraction
                submission["stage1_extraction_source"] = outcome.source
                submission["page_mapping"] = outcome.page_mapping
                if paper.get("rubric_status") != "ready":
                    return True
            else:
                blocks_grading = stage1_blocks_grading(stage1)
                requires_review = stage1_requires_review(stage1)
                if blocks_grading:
                    _rpc_bool(service, "finish_evaluation_stage1_job", {
                        "p_id": job["id"], "p_worker": worker_id,
                        "p_extraction": stage1,
                        "p_source": submission.get("stage1_extraction_source")
                        or submission.get("answer_script_path"),
                        "p_mapping": submission.get("page_mapping") or {},
                        "p_requires_review": True,
                    })
                    return True
            if paper.get("rubric_status") == "failed":
                _rpc_bool(service, "block_submission_for_failed_rubric", {
                    "p_id": job["id"], "p_worker": worker_id,
                })
                return True
            if paper.get("rubric_status") != "ready":
                _rpc_bool(service, "finish_evaluation_stage1_job", {
                    "p_id": job["id"], "p_worker": worker_id,
                    "p_extraction": stage1,
                    "p_source": submission.get("stage1_extraction_source")
                    or submission.get("answer_script_path"),
                    "p_mapping": submission.get("page_mapping") or {},
                    "p_requires_review": False,
                })
                return True
            if not _rpc_bool(service, "begin_evaluation_stage2", {
                "p_id": job["id"], "p_worker": worker_id,
            }):
                return True
            scored = run_stage2(
                service,
                submission,
                paper,
                job_id=job["id"],
                force_review=requires_review,
            )
            evaluation_id = str(uuid4())
            finished = _rpc_bool(service, "finish_evaluation_stage2_job", {
                "p_id": job["id"], "p_worker": worker_id,
                "p_evaluation": evaluation_id, "p_summary": stage2_summary(scored),
                "p_questions": scored.questions, "p_artifacts": scored.artifacts,
                "p_review": scored.requires_review,
            })
            if finished:
                _run_learning_follow_on(
                    service, evaluation_id=evaluation_id,
                    submission=submission, paper=paper,
                )
        if not finished:
            logger.info("Evaluation worker lease no longer held")
    except Exception as exc:
        rubric_job = job.get("kind") == "build_rubric"
        logger.warning(
            "Evaluation %s failed (%s): %s",
            "rubric" if rubric_job else "pipeline",
            type(exc).__name__,
            str(exc) or "no diagnostic detail",
        )
        try:
            if rubric_job:
                _rpc_bool(service, "fail_evaluation_rubric_job", {
                    "p_id": job["id"], "p_worker": worker_id,
                    "p_retryable": not isinstance(exc, RubricPermanentError),
                    "p_error": str(exc) or "Rubric generation failed.",
                })
            else:
                _rpc_bool(service, "fail_evaluation_job", {
                    "p_id": job["id"], "p_worker": worker_id,
                    "p_retryable": not isinstance(exc, (Stage1PermanentError, Stage2PermanentError)),
                })
        except Exception:
            logger.warning("Could not record evaluation job failure; lease recovery will retry it")
    finally:
        done.set()
        if thread is not None:
            thread.join(timeout=1)
        if watchdog_thread is not None:
            watchdog_thread.join(timeout=1)
    return True


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    settings = get_settings()
    if not settings.evaluation_jobs_enabled:
        raise SystemExit(
            "Set EVALUATION_JOBS_ENABLED=true after applying the evaluation migration."
        )
    stop = threading.Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: stop.set())
    worker_id = str(uuid4())
    logger.info(
        "Evaluation worker starting poll_seconds=%s",
        settings.evaluation_worker_poll_seconds,
    )
    connection_logged = False
    next_reaper_at = 0.0
    while not stop.is_set():
        try:
            now = time.monotonic()
            if now >= next_reaper_at:
                reaped = get_service_client().rpc(
                    "reap_stuck_evaluation_jobs",
                    {"p_soft_timeout_seconds": settings.evaluation_job_soft_timeout_seconds},
                ).execute().data
                if reaped:
                    logger.warning("Reaped %s stuck evaluation job(s)", reaped)
                next_reaper_at = now + settings.evaluation_reaper_interval_seconds
            worked = run_one(worker_id=worker_id)
            if not connection_logged:
                logger.info("Evaluation worker connected; polling evaluation jobs")
                connection_logged = True
        except Exception as exc:
            logger.warning("Evaluation queue unavailable (%s)", type(exc).__name__)
            worked = False
        if not worked:
            stop.wait(settings.evaluation_worker_poll_seconds)


if __name__ == "__main__":
    main()
