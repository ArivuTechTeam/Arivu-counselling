"""Small, dependency-free helpers for correlating API requests with logs."""

from __future__ import annotations

import re
from uuid import uuid4


_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


def request_id_for_header(supplied_id: str | None) -> str:
    """Keep safe client IDs; replace missing or log-unsafe values."""
    if supplied_id and _SAFE_REQUEST_ID.fullmatch(supplied_id):
        return supplied_id
    return uuid4().hex
