"""Forecasting helpers for Meridian."""

from __future__ import annotations

from datetime import date, timedelta

from meridian.models import ForecastPoint, Order


def aggregate_daily_orders(orders: list[Order]) -> dict[str, dict[date, int]]:
    """Aggregate orders into per-day volumes by SKU."""
    by_sku: dict[str, dict[date, int]] = {}
    for order in orders:
        bucket = by_sku.setdefault(order.sku, {})
        bucket[order.order_date] = bucket.get(order.order_date, 0) + order.qty
    return by_sku


def exponential_smoothing(series: list[float], alpha: float) -> list[float]:
    """Simple exponential smoothing."""
    if not series:
        return []
    smoothed = [series[0]]
    for value in series[1:]:
        smoothed.append(alpha * value + (1 - alpha) * smoothed[-1])
    return smoothed


def build_forecast(
    orders: list[Order],
    baseline: list[ForecastPoint],
    horizon_days: int,
    smoothing: float,
    history_window_days: int = 56,
) -> dict[str, list[ForecastPoint]]:
    """Build a SKU-level forecast for the planning horizon."""
    daily_orders = aggregate_daily_orders(orders)
    baseline_map: dict[str, dict[date, float]] = {}

    for point in baseline:
        bucket = baseline_map.setdefault(point.sku, {})
        bucket[point.date] = point.expected_units

    skus = set(daily_orders.keys()) | set(baseline_map.keys())
    forecasts: dict[str, list[ForecastPoint]] = {}

    for sku in sorted(skus):
        order_days = daily_orders.get(sku, {})
        baseline_days = baseline_map.get(sku, {})
        if order_days:
            last_history = max(order_days.keys())
        elif baseline_days:
            last_history = max(baseline_days.keys())
        else:
            last_history = date.today()

        history_start = last_history - timedelta(days=history_window_days - 1)
        series: list[float] = []
        for offset in range(history_window_days):
            day = history_start + timedelta(days=offset)
            observed = float(order_days.get(day, 0))
            if observed <= 0 and day in baseline_days:
                observed = float(baseline_days[day])
            series.append(observed)

        smoothed = exponential_smoothing(series, smoothing)
        last_value = smoothed[-1] if smoothed else 0.0
        trend = 0.0
        if len(smoothed) > 1:
            trend = (smoothed[-1] - smoothed[0]) / (len(smoothed) - 1)

        start_date = last_history + timedelta(days=1)
        points: list[ForecastPoint] = []
        for step in range(horizon_days):
            projected = max(last_value + trend * step, 0.0)
            points.append(
                ForecastPoint(
                    sku=sku,
                    date=start_date + timedelta(days=step),
                    expected_units=projected,
                )
            )

        forecasts[sku] = points

    return forecasts


__all__ = ["aggregate_daily_orders", "exponential_smoothing", "build_forecast"]
