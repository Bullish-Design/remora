"""Data loaders for Meridian."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from meridian.models import (
    ForecastPoint,
    InventoryPosition,
    Order,
    PriceRule,
    SKU,
    Supplier,
    Warehouse,
)


class Dataset(BaseModel):
    skus: list[SKU]
    warehouses: list[Warehouse]
    positions: list[InventoryPosition]
    orders: list[Order]
    suppliers: list[Supplier]
    pricing_rules: list[PriceRule]
    baseline_forecast: list[ForecastPoint]


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def load_inventory(path: Path) -> tuple[list[SKU], list[Warehouse], list[InventoryPosition]]:
    data = _load_json(path)
    skus = [SKU(**item) for item in data.get("skus", [])]
    warehouses = [Warehouse(**item) for item in data.get("warehouses", [])]
    positions = [InventoryPosition(**item) for item in data.get("positions", [])]
    return skus, warehouses, positions


def load_orders(path: Path) -> list[Order]:
    data = _load_json(path)
    return [Order(**item) for item in data.get("orders", [])]


def load_suppliers(path: Path) -> list[Supplier]:
    data = _load_json(path)
    return [Supplier(**item) for item in data.get("suppliers", [])]


def load_pricing_rules(path: Path) -> list[PriceRule]:
    data = _load_json(path)
    return [PriceRule(**item) for item in data.get("rules", [])]


def load_baseline_forecast(path: Path) -> list[ForecastPoint]:
    data = _load_json(path)
    return [ForecastPoint(**item) for item in data.get("baseline", [])]


def load_dataset(data_dir: Path) -> Dataset:
    skus, warehouses, positions = load_inventory(data_dir / "inventory.json")
    orders = load_orders(data_dir / "orders.json")
    suppliers = load_suppliers(data_dir / "suppliers.json")
    pricing_rules = load_pricing_rules(data_dir / "pricing_rules.json")
    baseline_forecast = load_baseline_forecast(data_dir / "forecast_baseline.json")

    return Dataset(
        skus=skus,
        warehouses=warehouses,
        positions=positions,
        orders=orders,
        suppliers=suppliers,
        pricing_rules=pricing_rules,
        baseline_forecast=baseline_forecast,
    )


__all__ = ["Dataset", "load_dataset"]
