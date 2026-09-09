"""Public API error helpers that never expose internal exception text."""

from __future__ import annotations

import logging

from fastapi import HTTPException

logger = logging.getLogger("app.api")


def public_error(
    status_code: int,
    detail: str,
    *,
    operation: str,
    exception: Exception,
) -> HTTPException:
    """Record a safe diagnostic and return a client-facing HTTP error.

    Database/provider exception strings can contain schema details, upstream
    response fragments, or user content. Log only the operation and exception
    class; keep the stable, friendly detail in the response payload.
    """
    logger.warning(
        "API operation failed: %s (%s)",
        operation,
        type(exception).__name__,
    )
    return HTTPException(status_code=status_code, detail=detail)
