"""Configuration models for Meridian planning runs."""

from __future__ import annotations

import os
from typing import Mapping

from pydantic import BaseModel, Field, field_validator


class PlannerConfig(BaseModel):
    """Planner settings for inventory and pricing runs."""

    timezone: str = Field(default="UTC")
    currency: str = Field(default="USD")
    review_window_days: int = Field(default=28, ge=7)
    safety_stock_days: int = Field(default=14, ge=0)
    target_service_level: float = Field(default=0.97, gt=0.0, lt=1.0)
    max_lead_time_days: int = Field(default=35, ge=1)
    planning_horizon_days: int = Field(default=90, ge=7)
    smoothing_alpha: float = Field(default=0.35, gt=0.0, lt=1.0)
    price_floor_margin: float = Field(default=0.08, ge=0.0)
    max_discount: float = Field(default=0.2, ge=0.0, le=0.9)

    @field_validator("timezone")
    @classmethod
    def _timezone_not_empty(cls, value: str) -> str:
        if not value:
            raise ValueError("timezone must be set")
        return value

    @field_validator("currency")
    @classmethod
    def _currency_not_empty(cls, value: str) -> str:
        if not value:
            raise ValueError("currency must be set")
        return value

    def with_overrides(self, **kwargs: object) -> "PlannerConfig":
        """Return a copy with the provided overrides applied."""
        return self.model_copy(update=kwargs)

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "PlannerConfig":
        """Load config overrides from environment variables."""
        env = environ or os.environ
        overrides: dict[str, object] = {}
        mapping = {
            "MERIDIAN_TIMEZONE": ("timezone", str),
            "MERIDIAN_CURRENCY": ("currency", str),
            "MERIDIAN_REVIEW_WINDOW_DAYS": ("review_window_days", int),
            "MERIDIAN_SAFETY_STOCK_DAYS": ("safety_stock_days", int),
            "MERIDIAN_TARGET_SERVICE_LEVEL": ("target_service_level", float),
            "MERIDIAN_MAX_LEAD_TIME_DAYS": ("max_lead_time_days", int),
            "MERIDIAN_PLANNING_HORIZON_DAYS": ("planning_horizon_days", int),
            "MERIDIAN_SMOOTHING_ALPHA": ("smoothing_alpha", float),
            "MERIDIAN_PRICE_FLOOR_MARGIN": ("price_floor_margin", float),
            "MERIDIAN_MAX_DISCOUNT": ("max_discount", float),
        }

        for env_key, (field_name, cast_fn) in mapping.items():
            raw = env.get(env_key)
            if raw is None:
                continue
            try:
                overrides[field_name] = cast_fn(raw)
            except ValueError:
                continue

        return cls(**overrides)


__all__ = ["PlannerConfig"]
