"""One-round-trip transactional persistence for generated quiz content."""

from __future__ import annotations

from typing import Any


MAX_PERSISTED_QUESTIONS = 1000


class QuizPersistenceError(RuntimeError):
    """The database did not confirm a complete atomic quiz commit."""


def persist_generated_quiz(
    service,
    *,
    tenant_id: str,
    actor_id: str,
    payload: dict[str, Any],
) -> dict:
    """Commit set, variant, questions, links, and optional extraction receipt.

    PostgreSQL owns the transaction. The application sends one bounded payload
    and never attempts compensating deletes after a partial Data API sequence.
    """
    questions = payload.get("questions") if isinstance(payload, dict) else None
    if not isinstance(questions, list) or not 1 <= len(questions) <= MAX_PERSISTED_QUESTIONS:
        raise QuizPersistenceError(
            f"Atomic quiz persistence requires 1-{MAX_PERSISTED_QUESTIONS} questions."
        )
    response = service.rpc(
        "persist_generated_quiz",
        {
            "p_tenant": tenant_id,
            "p_actor": actor_id,
            "p_payload": payload,
        },
    ).execute()
    result = response.data if response else None
    if not isinstance(result, dict) or not result.get("quiz_set_id"):
        raise QuizPersistenceError("The database did not confirm the quiz commit.")
    return result
