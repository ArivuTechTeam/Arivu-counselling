"""Independent numerical-answer verification (Phase 6.3-A).

A BOUNDED registry of tested commerce calculators. The generator emits the
question's inputs; we recompute the answer here with our own audited code and
compare — so the AI never grades its own math, and no model-produced code is
ever executed. Anything outside these families is reported ``not_checked`` (never
a false "verified"). Calculators are currency-agnostic (plain numbers), so they
serve CA, CMA, CS, ACCA and CMA-US equally.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal, InvalidOperation

_HUNDRED = Decimal(100)
_DEFAULT_TOLERANCE = Decimal("0.01")


def _dec(value) -> Decimal | None:
    """Parse to a FINITE Decimal, or None (never raises)."""
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _inputs(raw: dict, *keys: str) -> list[Decimal] | None:
    """All requested inputs as finite Decimals, or None if any is missing/bad."""
    values: list[Decimal] = []
    for key in keys:
        parsed = _dec(raw.get(key))
        if parsed is None:
            return None
        values.append(parsed)
    return values


def _simple_interest(raw: dict) -> Decimal | None:
    got = _inputs(raw, "principal", "rate", "time")
    if got is None:
        return None
    principal, rate, time = got
    return principal * rate * time / _HUNDRED


def _compound_interest(raw: dict) -> Decimal | None:
    got = _inputs(raw, "principal", "rate", "time")
    if got is None:
        return None
    principal, rate, time = got
    if time != time.to_integral_value() or time < 0:
        return None  # only whole, non-negative periods are supported
    amount = principal * (Decimal(1) + rate / _HUNDRED) ** int(time)
    return amount - principal


def _straight_line_depreciation(raw: dict) -> Decimal | None:
    got = _inputs(raw, "cost", "salvage", "useful_life")
    if got is None:
        return None
    cost, salvage, life = got
    if life == 0:
        return None
    return (cost - salvage) / life


def _break_even_units(raw: dict) -> Decimal | None:
    got = _inputs(raw, "fixed_costs", "price_per_unit", "variable_cost_per_unit")
    if got is None:
        return None
    fixed, price, variable = got
    contribution = price - variable
    if contribution == 0:
        return None
    return fixed / contribution


def _percentage(raw: dict) -> Decimal | None:
    got = _inputs(raw, "part", "whole")
    if got is None:
        return None
    part, whole = got
    if whole == 0:
        return None
    return part / whole * _HUNDRED


def _ratio(raw: dict) -> Decimal | None:
    got = _inputs(raw, "numerator", "denominator")
    if got is None:
        return None
    numerator, denominator = got
    if denominator == 0:
        return None
    return numerator / denominator


CALCULATORS: dict[str, Callable[[dict], "Decimal | None"]] = {
    "simple_interest": _simple_interest,
    "compound_interest": _compound_interest,
    "straight_line_depreciation": _straight_line_depreciation,
    "break_even_units": _break_even_units,
    "percentage": _percentage,
    "ratio": _ratio,
}

SUPPORTED_FAMILIES = tuple(CALCULATORS)

# The exact input keys each family expects, in order. This is the single source
# of truth used to describe the optional "calc" object to the generator, so the
# prompt can never drift from what the calculators actually read.
FAMILY_INPUT_KEYS: dict[str, tuple[str, ...]] = {
    "simple_interest": ("principal", "rate", "time"),
    "compound_interest": ("principal", "rate", "time"),
    "straight_line_depreciation": ("cost", "salvage", "useful_life"),
    "break_even_units": ("fixed_costs", "price_per_unit", "variable_cost_per_unit"),
    "percentage": ("part", "whole"),
    "ratio": ("numerator", "denominator"),
}


def recompute(family: str, inputs: dict) -> Decimal | None:
    """The independently computed answer for a supported family, or None when the
    family is unsupported or the inputs are missing/invalid. Never raises."""
    calculator = CALCULATORS.get(family)
    if calculator is None or not isinstance(inputs, dict):
        return None
    try:
        return calculator(inputs)
    except (InvalidOperation, TypeError, ValueError, ZeroDivisionError):
        return None


def check_answer(
    family: str, inputs: dict, expected_value, tolerance=_DEFAULT_TOLERANCE
) -> str:
    """Verify a numerical answer against an independent recompute.

    Returns ``"ok"`` (agrees within tolerance), ``"mismatch"`` (disagrees — the
    AI math is likely wrong), or ``"not_checked"`` (unsupported family, bad
    inputs, or unparseable expected value — never a false pass).
    """
    computed = recompute(family, inputs)
    if computed is None:
        return "not_checked"
    expected = _dec(expected_value)
    if expected is None:
        return "not_checked"
    try:
        tol = Decimal(str(tolerance))
    except (InvalidOperation, TypeError, ValueError):
        tol = _DEFAULT_TOLERANCE
    return "ok" if abs(computed - expected) <= tol else "mismatch"
