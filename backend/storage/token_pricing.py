from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any

PRICING_VERSION = "gemini_pricing_2026_06_plan"
CREDIT_USD_VALUE = 0.01
DEFAULT_INCLUDED_MONTHLY_CREDITS = 1000.0

MODEL_PRICING_USD_PER_1M: dict[str, dict[str, Decimal]] = {
  "gemini-3.5-flash": {
    "input": Decimal("1.50"),
    "output": Decimal("9.00"),
    "cached_input": Decimal("0.15"),
  },
  "gemini-3.1-pro-preview": {
    "input": Decimal("2.00"),
    "output": Decimal("12.00"),
    "cached_input": Decimal("0.20"),
  },
}

DEFAULT_PRICING = MODEL_PRICING_USD_PER_1M["gemini-3.5-flash"]


def pricing_for_model(model: str | None) -> dict[str, Decimal]:
  normalized = str(model or "").strip()
  if normalized in MODEL_PRICING_USD_PER_1M:
    return MODEL_PRICING_USD_PER_1M[normalized]
  for key, pricing in MODEL_PRICING_USD_PER_1M.items():
    if normalized.startswith(key):
      return pricing
  return DEFAULT_PRICING


def estimate_model_usage_cost(
  *,
  model: str | None,
  input_tokens: int | None = None,
  output_tokens: int | None = None,
  thought_tokens: int | None = None,
  cached_tokens: int | None = None,
) -> dict[str, Any]:
  pricing = pricing_for_model(model)
  billable_input = max(0, int(input_tokens or 0) - int(cached_tokens or 0))
  cached_input = max(0, int(cached_tokens or 0))
  billable_output = max(0, int(output_tokens or 0) + int(thought_tokens or 0))
  usd = (
    Decimal(billable_input) * pricing["input"]
    + Decimal(cached_input) * pricing["cached_input"]
    + Decimal(billable_output) * pricing["output"]
  ) / Decimal(1_000_000)
  credits = usd * Decimal(100)
  return {
    "pricing_version": PRICING_VERSION,
    "estimated_cost_usd": float(usd.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)),
    "estimated_credits": float(credits.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)),
    "billable_input_tokens": billable_input,
    "cached_input_tokens": cached_input,
    "billable_output_tokens": billable_output,
  }
