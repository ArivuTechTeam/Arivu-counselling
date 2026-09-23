"""AI-call log retention: blank raw payloads after the retention window.

The ``api_call_logs`` table keeps small, permanent metadata (provider, model,
tokens, cost, latency, status) used for billing and monitoring. It ALSO stores
the large ``raw_request`` (the full prompt, which contains the uploaded
document's text) and ``raw_response`` (the full model output). Those raw fields
are only useful for debugging a recent call, and holding full copies of customer
content indefinitely is a privacy, security-blast-radius and storage-cost
liability.

This job replaces ONLY those two raw fields with a small ``{"redacted": true}``
placeholder on rows older than the window. No row is deleted and no metadata is
touched, so billing, monitoring and analytics are unaffected. It is idempotent
(already-redacted rows are skipped via the ``redacted`` marker) and best-effort.

Run on a schedule (cron / platform scheduler):  python -m app.services.ai_log_retention
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from app.lib.config import get_settings
from app.lib.supabase import get_service_client

logger = logging.getLogger(__name__)

# raw_request is NOT NULL in the schema, so we blank to a placeholder rather than
# NULL — this needs no migration and also marks a row as already-redacted.
_REDACTED = {"redacted": True}
# PostgREST filter selecting rows whose raw_request has no top-level "redacted"
# key, i.e. rows still holding a real payload.
_UNREDACTED_PATH = "raw_request->>redacted"


def retention_cutoff(now: datetime, retention_days: int) -> str:
    """ISO timestamp; rows created strictly before this are eligible."""
    return (now - timedelta(days=retention_days)).isoformat()


def redact_expired_ai_logs(
    service,
    *,
    retention_days: int,
    now: datetime | None = None,
    batch_limit: int = 500,
    max_batches: int = 10_000,
) -> dict:
    """Blank raw payloads on expired, not-yet-redacted rows. Best-effort.

    Works in bounded batches so a large backlog never loads every row into memory
    or returns huge payloads. Returns a JSON-safe summary.
    """
    now = now or datetime.now(timezone.utc)
    cutoff = retention_cutoff(now, retention_days)
    redacted = 0
    for _ in range(max_batches):
        try:
            rows = (
                service.table("api_call_logs")
                .select("id")
                .lt("created_at", cutoff)
                .is_(_UNREDACTED_PATH, "null")
                .limit(batch_limit)
                .execute()
                .data
                or []
            )
        except Exception:  # noqa: BLE001 - retention must never crash the caller
            logger.warning("AI-log retention: could not read the log table")
            return {"redacted": redacted, "cutoff": cutoff,
                    "retention_days": retention_days, "status": "error"}
        ids = [row["id"] for row in rows if row.get("id")]
        if not ids:
            break
        try:
            service.table("api_call_logs").update(
                {"raw_request": _REDACTED, "raw_response": _REDACTED}
            ).in_("id", ids).execute()
        except Exception:  # noqa: BLE001
            logger.warning("AI-log retention: could not redact a batch")
            return {"redacted": redacted, "cutoff": cutoff,
                    "retention_days": retention_days, "status": "error"}
        redacted += len(ids)
        if len(rows) < batch_limit:
            break
    return {"redacted": redacted, "cutoff": cutoff,
            "retention_days": retention_days, "status": "ok"}


def main() -> None:
    settings = get_settings()
    report = redact_expired_ai_logs(
        get_service_client(), retention_days=settings.ai_log_raw_retention_days
    )
    print(json.dumps(report))
    raise SystemExit(0 if report.get("status") == "ok" else 1)


if __name__ == "__main__":
    main()
