"""Published provider token prices used for AI-call cost observability.

Values are USD per one million tokens.  Update this file when a configured
model changes price; unknown models deliberately produce no cost estimate.
"""

from __future__ import annotations

from decimal import Decimal


# input, output, cached input, output price already includes thinking tokens
MODEL_PRICING: dict[str, tuple[Decimal, Decimal, Decimal, bool]] = {
    "gemini-3.5-flash": (Decimal("1.50"), Decimal("9.00"), Decimal("0.15"), True),
    "gemini-3.5-flash-lite": (Decimal("0.30"), Decimal("2.50"), Decimal("0.03"), True),
    # Conservative peak-time rates. DeepSeek's off-peak discount makes actual
    # provider billing lower during discounted windows, never higher.
    "deepseek-flash": (Decimal("0.30"), Decimal("1.20"), Decimal("0.006"), False),
    "deepseek-chat": (Decimal("0.28"), Decimal("0.42"), Decimal("0.028"), False),
}
