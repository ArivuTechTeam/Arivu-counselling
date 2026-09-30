import itertools
import random

from app.services.paper_selection import COUNT_TOLERANCE, HALF_MARK_UNIT, bias_order, pick_exact_marks


def _row(marks, kind="x", identifier=None):
    return {"id": identifier or f"{kind}-{marks}-{random.random()}", "marks": marks, "type": kind}


def _units(marks):
    return round(marks * HALF_MARK_UNIT)


def _valid(selected, pool, total, count, tolerance=COUNT_TOLERANCE):
    assert selected is not None
    assert len({id(item) for item in selected}) == len(selected)
    assert all(any(item is candidate for candidate in pool) for item in selected)
    assert sum(_units(item["marks"]) for item in selected) == _units(total)
    assert abs(len(selected) - count) <= tolerance


def test_exact_sum_and_half_marks():
    pool = [_row(2.5), _row(5), _row(10), _row(20)]
    selected = pick_exact_marks(pool, 7.5, 2)
    _valid(selected, pool, 7.5, 2)


def test_infeasible_and_invalid_inputs_return_none():
    assert pick_exact_marks([_row(3)] * 3, 100, 3) is None
    assert pick_exact_marks([], 10, 2) is None
    assert pick_exact_marks([_row(5)], 0, 1) is None
    assert pick_exact_marks([_row(5)], 5, 0) is None
    assert pick_exact_marks([_row(0), _row(-1), _row(3.3)], 3.3, 1) is None


def test_count_tolerance_and_no_item_reuse():
    pool = [_row(5) for _ in range(4)]
    _valid(pick_exact_marks(pool, 20, 5), pool, 20, 5)
    assert pick_exact_marks(pool, 20, 10) is None


def test_bias_order_preserves_multiset_and_round_robins():
    pool = [_row(1, "a", "a1"), _row(1, "a", "a2"), _row(1, "b", "b1"), _row(1, "c", "c1")]
    ordered = bias_order(pool, lambda row: row["type"], rng=random.Random(7))
    assert {row["id"] for row in ordered} == {row["id"] for row in pool}
    assert len({row["type"] for row in ordered[:3]}) == 3


def test_randomized_result_matches_brute_force_feasibility():
    rng = random.Random(91)
    for _ in range(100):
        pool = [_row(rng.choice([0.5, 1, 1.5, 2, 2.5, 3, 4])) for _ in range(rng.randint(1, 9))]
        total = rng.randint(1, 14) / 2
        count = rng.randint(1, 7)
        selected = pick_exact_marks(pool, total, count)
        feasible = any(
            sum(_units(item["marks"]) for item in combo) == _units(total)
            for size in range(1, min(len(pool), count + COUNT_TOLERANCE) + 1)
            if abs(size - count) <= COUNT_TOLERANCE
            for combo in itertools.combinations(pool, size)
        )
        assert (selected is not None) is feasible
        if selected:
            _valid(selected, pool, total, count)
