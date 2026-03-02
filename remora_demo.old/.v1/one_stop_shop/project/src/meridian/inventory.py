"""Inventory planning helpers for Meridian."""

from __future__ import annotations

from meridian.config import PlannerConfig
from meridian.models import ForecastPoint, InventoryPosition, ReorderRecommendation, Supplier
from meridian.utils.metrics import stockout_risk


def compute_reorder_point(daily_demand: float, lead_time_days: int, safety_stock_days: int) -> float:
    """Compute a basic reorder point using demand and lead time."""
    return daily_demand * (lead_time_days + safety_stock_days)


def average_daily_demand(forecast: list[ForecastPoint], window_days: int) -> float:
    """Compute average daily demand from a forecast window."""
    if not forecast:
        return 0.0
    window = forecast[:window_days]
    if not window:
        return 0.0
    return sum(point.expected_units for point in window) / len(window)


def _select_supplier(suppliers: list[Supplier], sku: str) -> Supplier | None:
    if not suppliers:
        return None
    scoped = [supplier for supplier in suppliers if sku in supplier.sku_scope]
    if scoped:
        return sorted(scoped, key=lambda supplier: supplier.lead_time_days)[0]
    return sorted(suppliers, key=lambda supplier: supplier.lead_time_days)[0]


def recommend_replenishment(
    positions: list[InventoryPosition],
    forecast_by_sku: dict[str, list[ForecastPoint]],
    suppliers: list[Supplier],
    config: PlannerConfig,
) -> list[ReorderRecommendation]:
    """Generate replenishment recommendations by SKU and warehouse."""
    recommendations: list[ReorderRecommendation] = []

    for position in positions:
        forecast = forecast_by_sku.get(position.sku, [])
        daily_demand = average_daily_demand(forecast, config.review_window_days)
        supplier = _select_supplier(suppliers, position.sku)
        lead_time_days = supplier.lead_time_days if supplier else config.max_lead_time_days
        reorder_point = compute_reorder_point(daily_demand, lead_time_days, config.safety_stock_days)

        net_available = position.net_available
        if net_available >= reorder_point:
            continue

        target_units = daily_demand * config.planning_horizon_days
        raw_qty = max(int(round(target_units - net_available)), 0)
        if supplier:
            raw_qty = max(raw_qty, supplier.min_order_qty)

        risk = stockout_risk(net_available, reorder_point)
        priority = 5 if risk >= 0.75 else 4 if risk >= 0.5 else 3 if risk >= 0.25 else 2

        recommendations.append(
            ReorderRecommendation(
                sku=position.sku,
                warehouse_id=position.warehouse_id,
                recommended_qty=raw_qty,
                reorder_point=reorder_point,
                priority=priority,
                reason=(
                    f"Net available {net_available} below reorder point {reorder_point:.1f} "
                    f"(lead time {lead_time_days} days)"
                ),
            )
        )

    return recommendations


__all__ = [
    "compute_reorder_point",
    "average_daily_demand",
    "recommend_replenishment",
]
