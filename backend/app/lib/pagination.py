"""Opaque keyset cursor helpers shared by bounded catalogue endpoints."""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException


DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100


@dataclass(frozen=True)
class CursorPosition:
    occurred_at: datetime
    row_id: str


def bounded_page_size(value: int) -> int:
    if value < 1 or value > MAX_PAGE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"page_size must be between 1 and {MAX_PAGE_SIZE}.",
        )
    return value


def _utc(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid cursor timestamp") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def encode_cursor(occurred_at: datetime | str, row_id: str) -> str:
    payload = json.dumps(
        {"at": _utc(occurred_at).isoformat(), "id": str(UUID(str(row_id)))},
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def decode_cursor(value: str | None) -> CursorPosition | None:
    if not value:
        return None
    try:
        padding = "=" * (-len(value) % 4)
        payload = json.loads(base64.urlsafe_b64decode(value + padding))
        if not isinstance(payload, dict) or set(payload) != {"at", "id"}:
            raise ValueError("invalid cursor shape")
        occurred_at = _utc(payload["at"])
        row_id = str(UUID(str(payload["id"])))
    except (binascii.Error, json.JSONDecodeError, KeyError, TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid pagination cursor.")
    return CursorPosition(occurred_at=occurred_at, row_id=row_id)


def apply_descending_cursor(query, column: str, cursor: CursorPosition | None):
    """Apply ``(column, id) < (cursor timestamp, cursor id)`` in PostgREST."""
    if cursor is None:
        return query
    timestamp = cursor.occurred_at.isoformat()
    return query.or_(
        f"{column}.lt.{timestamp},and({column}.eq.{timestamp},id.lt.{cursor.row_id})"
    )


def descending_page(query, column: str, page_size: int, cursor: CursorPosition | None):
    query = apply_descending_cursor(query, column, cursor)
    return query.order(column, desc=True).order("id", desc=True).limit(page_size + 1)


def split_page(rows: list[dict], page_size: int, *, timestamp_key: str) -> tuple[list[dict], str | None]:
    has_more = len(rows) > page_size
    items = rows[:page_size]
    if not has_more or not items:
        return items, None
    last = items[-1]
    return items, encode_cursor(last[timestamp_key], last["id"])
