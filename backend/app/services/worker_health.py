"""Faculty-worker health: detect a stalled/absent durable worker.

With FACULTY_JOBS_ENABLED=true, final generation/import run in a SEPARATE worker
process (``python -m app.services.faculty_worker``). If that process is never
started or has died, jobs sit in ``queued`` forever with no visible error — the
exact silent hang we want to catch and alert on.

This module reads only counts/ages from ``faculty_jobs`` (never tenant content)
and is consumed by the read-only deployment preflight and a super-admin-only
monitoring endpoint. The evaluator is pure so the detection logic is unit-tested
without a database.

A worker is considered ALIVE when some job currently holds a non-expired lease
(the worker heartbeats to extend its lease every ~20s). Work that needs a worker
is: ``queued`` jobs, plus ``running`` jobs whose lease has expired (a worker died
mid-job). If such backlog is older than the stale threshold and no live lease
exists, the worker is stalled/absent.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Only these statuses bear on worker liveness; completed/cancelled are terminal.
_ACTIVE_STATUSES = ("queued", "running")


def _parse_iso(value) -> datetime | None:
    """Parse a Postgres/ISO-8601 timestamp to an aware datetime, or None."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def evaluate_worker_health(
    jobs: list[dict], *, now: datetime, stale_seconds: int
) -> dict:
    """Pure health assessment from a snapshot of faculty_jobs rows.

    Each row needs: status, created_at, lease_expires_at (updated_at optional).
    Returns a JSON-safe dict; never raises for malformed rows.
    """
    queued = 0
    running = 0
    worker_active = False
    backlog_ages: list[float] = []  # seconds a piece of unclaimed work has waited

    for job in jobs or []:
        status = job.get("status")
        lease_until = _parse_iso(job.get("lease_expires_at"))
        lease_live = lease_until is not None and lease_until > now
        if lease_live:
            worker_active = True  # some worker is holding + heartbeating a lease
        if status == "queued":
            queued += 1
            created = _parse_iso(job.get("created_at"))
            if created is not None:
                backlog_ages.append((now - created).total_seconds())
        elif status == "running":
            running += 1
            if not lease_live:
                # A running job with no live lease = worker died mid-job; the
                # work is effectively unclaimed until another worker recovers it.
                started = _parse_iso(job.get("updated_at")) or _parse_iso(
                    job.get("created_at")
                )
                if started is not None:
                    backlog_ages.append((now - started).total_seconds())

    oldest_backlog = max(backlog_ages) if backlog_ages else None
    stalled = (
        not worker_active
        and oldest_backlog is not None
        and oldest_backlog > stale_seconds
    )

    if queued == 0 and running == 0:
        status = "idle"
        detail = "No queued or running jobs; worker liveness cannot be confirmed from the queue alone."
    elif stalled:
        status = "stalled"
        detail = (
            f"{len(backlog_ages)} job(s) waiting up to {int(oldest_backlog)}s with no "
            "active worker lease. Start or restart the faculty worker process."
        )
    else:
        status = "ok"
        detail = "A worker holds a live lease and is processing the queue."

    return {
        "status": status,  # ok | stalled | idle
        "healthy": status != "stalled",
        "worker_active": worker_active,
        "queued": queued,
        "running": running,
        "oldest_backlog_seconds": int(oldest_backlog) if oldest_backlog is not None else None,
        "stale_threshold_seconds": stale_seconds,
        "detail": detail,
    }


def worker_health(service, settings, *, now: datetime | None = None) -> dict:
    """Live worker-health assessment. Best-effort: never raises.

    Returns ``{"status": "disabled"}`` when the durable worker is off, and a
    safe ``"unknown"`` status if the queue cannot be read.
    """
    if not getattr(settings, "faculty_jobs_enabled", False):
        return {
            "status": "disabled",
            "healthy": True,
            "detail": "Durable faculty worker is disabled; final generation runs in-process.",
        }
    now = now or datetime.now(timezone.utc)
    stale_seconds = getattr(settings, "faculty_worker_stale_seconds", 120)
    try:
        rows = (
            service.table("faculty_jobs")
            .select("status, created_at, updated_at, lease_expires_at")
            .in_("status", list(_ACTIVE_STATUSES))
            .limit(500)
            .execute()
            .data
            or []
        )
    except Exception:  # noqa: BLE001 - monitoring must never crash on a read error
        logger.warning("Worker-health queue read failed")
        return {
            "status": "unknown",
            "healthy": True,
            "detail": "Could not read the job queue to assess worker health.",
        }
    return evaluate_worker_health(rows, now=now, stale_seconds=stale_seconds)
