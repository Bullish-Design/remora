"""Pricing logic for Meridian."""

from __future__ import annotations

from meridian.config import PlannerConfig
from meridian.models import ForecastPoint, PriceRule, PricingResult, SKU
from meridian.utils.validation import clamp


def _select_rule(rules: list[PriceRule], sku: SKU) -> PriceRule | None:
    by_sku = [rule for rule in rules if rule.sku == sku.sku]
    if by_sku:
        return by_sku[0]
    by_category = [rule for rule in rules if rule.category == sku.category]
    if by_category:
        return by_category[0]
    return None


def _demand_pressure(forecast: list[ForecastPoint]) -> float:
    if not forecast:
        return 0.0
    horizon = forecast[:7]
    avg = sum(point.expected_units for point in horizon) / len(horizon)
    if avg <= 0:
        return -0.1
    if avg >= 200:
        return 0.15
    if avg >= 120:
        return 0.08
    if avg <= 20:
        return -0.05
    return 0.02


class PricingEngine:
    """Compute pricing recommendations with rule constraints."""

    def __init__(self, rules: list[PriceRule], config: PlannerConfig) -> None:
        self._rules = rules
        self._config = config

    def price_for_sku(self, sku: SKU, forecast: list[ForecastPoint]) -> PricingResult:
        rule = _select_rule(self._rules, sku)
        demand_adjust = _demand_pressure(forecast)

        min_margin = rule.min_margin if rule else self._config.price_floor_margin
        max_discount = rule.max_discount if rule else self._config.max_discount
        floor_price = rule.floor_price if rule else 0.0
        elasticity = rule.elasticity if rule else 1.0

        base_price = sku.list_price
        target_price = base_price * (1 + demand_adjust * elasticity)
        min_price = max(sku.unit_cost * (1 + min_margin), floor_price)
        discounted_price = max(min(target_price, base_price * (1 - max_discount)), min_price)

        recommended = round(discounted_price, 2)
        discount_pct = clamp((base_price - recommended) / base_price if base_price else 0.0, 0.0, 1.0)

        notes = "rule-based"
        if rule and rule.sku:
            notes = "sku rule"
        elif rule and rule.category:
            notes = "category rule"

        return PricingResult(
            sku=sku.sku,
            list_price=base_price,
            recommended_price=recommended,
            discount_pct=round(discount_pct, 4),
            notes=notes,
        )


__all__ = ["PricingEngine"]
