"""Domain models for Meridian planning."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class SKU(BaseModel):
    sku: str
    description: str
    category: str
    unit_cost: float = Field(ge=0.0)
    list_price: float = Field(ge=0.0)
    unit_weight: float = Field(ge=0.0)
    min_order_qty: int = Field(default=1, ge=1)


class Warehouse(BaseModel):
    warehouse_id: str
    name: str
    region: str
    capacity_units: int = Field(ge=0)


class InventoryPosition(BaseModel):
    sku: str
    warehouse_id: str
    on_hand: int = Field(ge=0)
    inbound: int = Field(ge=0)
    reserved: int = Field(ge=0)

    @property
    def net_available(self) -> int:
        return self.on_hand + self.inbound - self.reserved


class Supplier(BaseModel):
    supplier_id: str
    name: str
    lead_time_days: int = Field(ge=1)
    min_order_qty: int = Field(default=1, ge=1)
    reliability_score: float = Field(ge=0.0, le=1.0)
    sku_scope: list[str] = Field(default_factory=list)


class Order(BaseModel):
    order_id: str
    sku: str
    qty: int = Field(ge=1)
    order_date: date
    warehouse_id: str
    channel: Literal["b2b", "ecom", "retail"]


class ForecastPoint(BaseModel):
    sku: str
    date: date
    expected_units: float = Field(ge=0.0)


class PriceRule(BaseModel):
    sku: str | None = None
    category: str | None = None
    min_margin: float = Field(default=0.05, ge=0.0)
    max_discount: float = Field(default=0.2, ge=0.0, le=0.9)
    floor_price: float = Field(default=0.0, ge=0.0)
    elasticity: float = Field(default=1.0, ge=0.1)

    @field_validator("sku", "category")
    @classmethod
    def _at_least_one_selector(cls, value: str | None, info) -> str | None:
        if info.field_name == "sku" and value:
            return value
        if info.field_name == "category" and value:
            return value
        return value


class ReorderRecommendation(BaseModel):
    sku: str
    warehouse_id: str
    recommended_qty: int = Field(ge=0)
    reorder_point: float = Field(ge=0.0)
    priority: int = Field(ge=1, le=5)
    reason: str


class PricingResult(BaseModel):
    sku: str
    list_price: float = Field(ge=0.0)
    recommended_price: float = Field(ge=0.0)
    discount_pct: float = Field(ge=0.0, le=1.0)
    notes: str


class PlanResult(BaseModel):
    generated_at: datetime
    recommendations: list[ReorderRecommendation]
    pricing: list[PricingResult]
    metrics: dict[str, float]
    forecast_snapshot: dict[str, list[ForecastPoint]]


__all__ = [
    "SKU",
    "Warehouse",
    "InventoryPosition",
    "Supplier",
    "Order",
    "ForecastPoint",
    "PriceRule",
    "ReorderRecommendation",
    "PricingResult",
    "PlanResult",
]
