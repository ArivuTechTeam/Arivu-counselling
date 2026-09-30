"""Deterministic exact-mark selection and candidate diversification."""
from __future__ import annotations

import random as _random
from collections.abc import Callable, Iterable, Mapping
from typing import Any


HALF_MARK_UNIT = 2
COUNT_TOLERANCE = 2


def _marks(item: Mapping[str, Any] | Any) -> float:
    value = item.get("marks", 0) if isinstance(item, Mapping) else getattr(item, "marks", 0)
    return float(value or 0)


def bias_order(
    candidates: Iterable[Any], key_fn: Callable[[Any], Any], *, rng: _random.Random | None = None
) -> list[Any]:
    """Shuffle within groups, then round-robin across groups."""
    randomizer = rng or _random
    groups: dict[Any, list[Any]] = {}
    for candidate in candidates:
        groups.setdefault(key_fn(candidate), []).append(candidate)
    for group in groups.values():
        randomizer.shuffle(group)

    ordered: list[Any] = []
    keys = list(groups)
    while any(groups[key] for key in keys):
        for key in keys:
            if groups[key]:
                ordered.append(groups[key].pop())
    return ordered


def pick_exact_marks(
    candidates: Iterable[Any],
    total_marks: float,
    num_questions: int,
    count_tolerance: int = COUNT_TOLERANCE,
) -> list[Any] | None:
    """Return a 0/1 subset on the half-mark grid, or ``None`` if infeasible."""
    target_units = round(float(total_marks) * HALF_MARK_UNIT)
    if target_units <= 0 or num_questions <= 0:
        return None

    items: list[tuple[Any, int]] = []
    for question in candidates:
        marks = _marks(question)
        units = round(marks * HALF_MARK_UNIT)
        if units <= 0 or abs(units - marks * HALF_MARK_UNIT) > 1e-6:
            continue
        items.append((question, units))
    if not items:
        return None

    max_count = min(num_questions + count_tolerance, len(items))
    if max_count <= 0:
        return None
    reached = [[False] * (target_units + 1) for _ in range(max_count + 1)]
    chosen: list[list[int | None]] = [
        [None] * (target_units + 1) for _ in range(max_count + 1)
    ]
    reached[0][0] = True

    for index, (_question, units) in enumerate(items):
        if units > target_units:
            continue
        for count in range(max_count, 0, -1):
            for subtotal in range(target_units, units - 1, -1):
                if not reached[count][subtotal] and reached[count - 1][subtotal - units]:
                    reached[count][subtotal] = True
                    chosen[count][subtotal] = index

    best_count: int | None = None
    for offset in range(count_tolerance + 1):
        for count in (num_questions + offset, num_questions - offset):
            if 0 < count <= max_count and reached[count][target_units]:
                best_count = count
                break
        if best_count is not None:
            break
    if best_count is None:
        return None

    selected: list[Any] = []
    count, subtotal = best_count, target_units
    while count > 0:
        index = chosen[count][subtotal]
        if index is None:
            return None
        question, units = items[index]
        selected.append(question)
        subtotal -= units
        count -= 1
    if subtotal != 0 or len(selected) != best_count:
        return None
    return selected
