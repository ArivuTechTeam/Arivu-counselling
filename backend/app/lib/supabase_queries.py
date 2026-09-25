"""Reusable, bounded helpers for complete Supabase Data API reads."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar


POSTGREST_PAGE_SIZE = 500
POSTGREST_FILTER_BATCH_SIZE = 100
JsonContainer = TypeVar("JsonContainer", dict, list)


def rpc_json_value(
    service,
    function_name: str,
    params: dict,
    expected_type: type[JsonContainer],
) -> JsonContainer:
    """Return a JSON object/array from a PostgREST RPC without shape guessing.

    ``supabase-py`` normally returns a JSONB function result directly. Some
    PostgREST/client combinations wrap a scalar result in a one-row/one-column
    result, so accept that representation too and reject every other shape.
    """
    data = service.rpc(function_name, params).execute().data
    if isinstance(data, list) and len(data) == 1 and isinstance(data[0], dict):
        row = data[0]
        if len(row) == 1:
            value = next(iter(row.values()))
            if isinstance(value, expected_type):
                return value
    if isinstance(data, expected_type):
        return data
    raise RuntimeError(f"{function_name} returned an invalid analytics payload")


def select_all(
    service,
    table: str,
    columns: str,
    *,
    configure: Callable | None = None,
    order_column: str = "id",
    order_desc: bool = False,
) -> list[dict]:
    """Return every matching row without relying on PostgREST's row ceiling.

    A fresh query is built for each page because the Supabase query builder is
    mutable. Lightweight in-memory test doubles that do not implement
    ``range`` still execute once, preserving their intended behaviour.
    """

    rows: list[dict] = []
    start = 0
    while True:
        query = service.table(table).select(columns)
        if configure is not None:
            query = configure(query)
        if hasattr(query, "order"):
            query = query.order(order_column, desc=order_desc)
        if not hasattr(query, "range"):
            return query.execute().data or []
        page = (
            query.range(start, start + POSTGREST_PAGE_SIZE - 1).execute().data
            or []
        )
        rows.extend(page)
        if len(page) < POSTGREST_PAGE_SIZE:
            return rows
        start += POSTGREST_PAGE_SIZE


def select_all_in(
    service,
    table: str,
    columns: str,
    *,
    in_column: str,
    values,
    configure: Callable | None = None,
    order_column: str = "id",
    order_desc: bool = False,
) -> list[dict]:
    """Return all rows matching a potentially large ``IN`` filter.

    PostgREST filters are encoded in the request URL. A long list of UUIDs can
    exceed an upstream proxy's request-line limit before PostgREST sees it, so
    split the filter as well as paginating each response.
    """

    unique_values = list(dict.fromkeys(values))
    if not unique_values:
        return []

    rows: list[dict] = []
    for start in range(0, len(unique_values), POSTGREST_FILTER_BATCH_SIZE):
        batch = unique_values[start : start + POSTGREST_FILTER_BATCH_SIZE]

        def configure_batch(query, batch=batch):
            if configure is not None:
                query = configure(query)
            return query.in_(in_column, batch)

        rows.extend(
            select_all(
                service,
                table,
                columns,
                configure=configure_batch,
                order_column=order_column,
                order_desc=order_desc,
            )
        )

    return sorted(
        rows,
        key=lambda row: (
            row.get(order_column) is None,
            str(row.get(order_column) or ""),
        ),
        reverse=order_desc,
    )
