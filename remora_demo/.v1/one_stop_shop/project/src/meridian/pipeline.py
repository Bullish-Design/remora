"""Core planning pipeline for Meridian."""

from __future__ import annotations

from datetime import datetime

from meridian.config import PlannerConfig
from meridian.forecasting import build_forecast
from meridian.inventory import recommend_replenishment
from meridian.io.loader import Dataset
from meridian.models import ForecastPoint, PlanResult
from meridian.pricing import PricingEngine
from meridian.utils.metrics import summarize_plan


class MeridianPlanner:
    """Run the end-to-end planning pipeline."""

    def __init__(self, config: PlannerConfig | None = None) -> None:
        self._config = config or PlannerConfig()

    def plan(self, dataset: Dataset) -> PlanResult:
        forecast_by_sku = build_forecast(
            dataset.orders,
            dataset.baseline_forecast,
            self._config.planning_horizon_days,
            self._config.smoothing_alpha,
        )

        pricing_engine = PricingEngine(dataset.pricing_rules, self._config)
        pricing = [
            pricing_engine.price_for_sku(sku, forecast_by_sku.get(sku.sku, []))
            for sku in dataset.skus
        ]

        recommendations = recommend_replenishment(
            dataset.positions,
            forecast_by_sku,
            dataset.suppliers,
            self._config,
        )

        metrics = summarize_plan(recommendations, pricing)

        snapshot: dict[str, list[ForecastPoint]] = {
            sku: points[:7] for sku, points in forecast_by_sku.items()
        }

        return PlanResult(
            generated_at=datetime.utcnow(),
            recommendations=recommendations,
            pricing=pricing,
            metrics=metrics,
            forecast_snapshot=snapshot,
        )


__all__ = ["MeridianPlanner"]
