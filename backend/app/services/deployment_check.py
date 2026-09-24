"""Read-only deployment preflight: python -m app.services.deployment_check.

Does not execute migrations, queue work, or call AI providers. Database values,
credentials and exception bodies are never included in the report.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.lib.config import get_settings
from app.lib.supabase import get_service_client


def inspect_deployment(service, settings, migration_dir: Path) -> dict:
    checks = []

    def probe(name: str, table: str, columns: str) -> None:
        try:
            service.table(table).select(columns).limit(1).execute()
        except Exception:
            checks.append({"name": name, "status": "fail",
                           "detail": "Required database read failed. Check connectivity, permissions and applied schema."})
        else:
            checks.append({"name": name, "status": "pass"})

    probe("core_schema", "questions", "id,tenant_id,review_status,verification_status")
    probe("attempt_snapshots", "quiz_attempts", "id,question_snapshot")
    probe("analysis_jobs", "quiz_generation_jobs", "id,status,phase,params")
    probe("ai_call_logging", "api_call_logs", "id,tenant_id,job_id,input_tokens,output_tokens")
    if settings.faculty_jobs_enabled:
        probe("faculty_queue_schema", "faculty_jobs",
              "id,tenant_id,status,lease_token,lease_expires_at,checkpoint")
        try:
            from app.services.worker_health import worker_health
            health = worker_health(service, settings)
            status = {"stalled": "fail", "unknown": "warning", "idle": "warning"}.get(
                health.get("status"), "pass")
            checks.append({"name": "faculty_worker_health", "status": status,
                           "detail": health.get("detail", "")})
        except Exception:
            checks.append({"name": "faculty_worker_health", "status": "unverified",
                           "detail": "Could not assess worker health during preflight."})
    else:
        checks.append({"name": "faculty_queue", "status": "warning",
                       "detail": "Dedicated worker queue is disabled; legacy in-process execution is not restart-safe by itself."})
    if getattr(settings, "figure_attach_enabled", False):
        probe("existing_figure_schema", "document_figures", "id,tenant_id")
        probe("existing_figure_link", "questions", "id,figure_id")
    if getattr(settings, "quiz_reuse_enabled", False):
        probe("quiz_release_schema", "quiz_sets", "id,released_at")
        probe("question_reuse_schema", "questions", "id,content_version,release_locked,origin_question_id,source_quiz_id")
        probe("copy_request_schema", "quiz_copy_requests", "tenant_id,actor_id,request_key,quiz_id")
    if getattr(settings, "batches_enabled", False):
        probe("batches_schema", "batches", "id,tenant_id,course_id,course_level_id,status")
        probe("batch_memberships_schema", "batch_memberships", "id,tenant_id,batch_id,profile_id,active")
        probe("quiz_assignments_schema", "quiz_assignments", "id,tenant_id,quiz_set_id,batch_id,status")
        probe("quiz_audience_mode", "quiz_sets", "id,audience_mode")
    if getattr(settings, "scoring_policies_enabled", False):
        probe("scoring_policies_schema", "scoring_policies", "id,tenant_id,name,rules")
        probe("quiz_scoring_policy_link", "quiz_sets", "id,scoring_policy_id")
        probe("attempt_policy_snapshot", "quiz_attempts", "id,scoring_policy_snapshot")
        probe("course_exam_standard", "course_levels", "id,course_id,exam_scoring_policy_id")
    if getattr(settings, "commerce_pack_enabled", False):
        probe("paper_profiles_schema", "paper_profiles",
              "id,tenant_id,course_id,course_level_id,exam_body,level,paper,assessment_year,framework")

    files = sorted(path.name for path in migration_dir.glob("migration-*.sql"))
    checks.append({"name": "runtime_evidence", "status": "unverified",
                   "detail": "This read-only check does not prove worker liveness, RPC definitions, migration history, storage access, or end-to-end completion. Run the documented staging drills."})
    return {"schema_checks_passed": not any(c["status"] == "fail" for c in checks),
            "production_ready": False,
            "final_generation_mode": "faculty_worker" if settings.faculty_jobs_enabled else "legacy_in_process",
            "repository_migrations": files, "checks": checks}


def main() -> None:
    try:
        report = inspect_deployment(get_service_client(), get_settings(),
                                    Path(__file__).resolve().parents[3] / "migrations")
    except Exception:
        print(json.dumps({"schema_checks_passed": False, "production_ready": False,
                          "error": "Preflight could not initialize. Check the backend environment and service connection."}))
        raise SystemExit(1)
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["schema_checks_passed"] else 1)


if __name__ == "__main__":
    main()
