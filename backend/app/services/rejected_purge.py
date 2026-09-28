"""Transactional rejected-question cleanup used by legacy publication paths."""

from __future__ import annotations

import logging

log = logging.getLogger("rejected_purge")


def purge_rejected_for_quiz_set(
    service, tenant_id: str, created_by: str, quiz_set_id: str
) -> dict[str, int]:
    """Delete eligible rejected questions in one database transaction.

    New atomic publication RPCs perform this operation inside publication
    itself. This wrapper remains for the feature-flagged legacy publish path.
    It is deliberately best-effort because that path has already published by
    the time cleanup runs.
    """
    try:
        result = service.rpc(
            "purge_rejected_quiz_questions_atomic",
            {
                "p_id": quiz_set_id,
                "p_tenant": tenant_id,
                "p_actor": created_by,
            },
        ).execute().data
    except Exception as exc:  # noqa: BLE001 - cleanup cannot undo legacy publish
        log.warning("Rejected-question cleanup failed (%s)", type(exc).__name__)
        return {"purged": 0, "kept": 0}
    if not isinstance(result, dict):
        return {"purged": 0, "kept": 0}
    return {
        "purged": int(result.get("purged") or 0),
        "kept": int(result.get("kept") or 0),
    }
