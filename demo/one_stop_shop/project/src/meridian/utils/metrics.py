"""Metric helpers for Meridian planning outputs."""

from __future__ import annotations

from typing import Iterable

from meridian.models import InventoryPosition, Order, ReorderRecommendation, PricingResult


def fill_rate(orders: Iterable[Order], positions: Iterable[InventoryPosition]) -> float:
    """Estimate fill rate based on net availability."""
    total = 0
    filled = 0
    availability = {pos.sku: pos.net_available for pos in positions}

    for order in orders:
        total += order.qty
        available = availability.get(order.sku, 0)
        if available <= 0:
            continue
        filled += min(order.qty, available)
    if total == 0:
        return 1.0
    return filled / total


def stockout_risk(net_available: int, reorder_point: float) -> float:
    """Rough stockout risk indicator."""
    if reorder_point <= 0:
        return 0.0
    ratio = max(reorder_point - net_available, 0) / reorder_point
    return min(ratio, 1.0)


def inventory_turns(orders: Iterable[Order], positions: Iterable[InventoryPosition]) -> float:
    """Compute an approximate inventory turns ratio."""
    total_units = sum(order.qty for order in orders)
    positions_list = list(positions)
    avg_inventory = sum(pos.on_hand for pos in positions_list) / max(len(positions_list), 1)
    if avg_inventory <= 0:
        return 0.0
    return total_units / avg_inventory


def summarize_plan(
    recommendations: Iterable[ReorderRecommendation],
    pricing: Iterable[PricingResult],
) -> dict[str, float]:
    """Summarize key outputs for dashboards."""
    recommendations = list(recommendations)
    pricing = list(pricing)

    total_reorder_units = sum(rec.recommended_qty for rec in recommendations)
    high_priority = sum(1 for rec in recommendations if rec.priority >= 4)
    average_discount = 0.0
    if pricing:
        average_discount = sum(result.discount_pct for result in pricing) / len(pricing)

    return {
        "total_reorder_units": float(total_reorder_units),
        "reorder_lines": float(len(recommendations)),
        "high_priority_lines": float(high_priority),
        "average_discount": float(round(average_discount, 4)),
    }


__all__ = ["fill_rate", "stockout_risk", "inventory_turns", "summarize_plan"]
