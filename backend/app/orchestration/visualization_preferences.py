"""Explicit, tenant/user-scoped presentation preferences (DVS v8)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.orchestration.models import VisualizationPreference

PREFERENCE_SCHEMA_VERSION = "1.0"


class VisualizationPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preferred_output: Literal["auto", "chart", "table"] = "auto"
    comparison_preference: Literal["auto", "grouped_bar", "dumbbell", "lollipop", "diverging_bar"] = "auto"
    trend_preference: Literal["auto", "line", "area"] = "auto"
    composition_preference: Literal["auto", "donut", "composition_bar", "stacked_bar", "percentage_stacked_bar"] = "auto"
    value_display: Literal["auto", "absolute", "percentage"] = "auto"
    label_orientation: Literal["auto", "horizontal", "vertical"] = "auto"
    visual_density: Literal["compact", "standard", "detailed"] = "standard"
    contrast_preference: Literal["system", "standard", "high"] = "system"
    reduced_motion: bool = False
    table_alternative_default_open: bool = False
    schema_version: Literal["1.0"] = PREFERENCE_SCHEMA_VERSION


async def get_preferences(db: AsyncSession, tenant_id: str, actor_id: str) -> VisualizationPreferences:
    row = await db.scalar(select(VisualizationPreference).where(
        VisualizationPreference.tenant_id == tenant_id,
        VisualizationPreference.actor_id == actor_id,
    ))
    return VisualizationPreferences.model_validate(row.preferences if row else {})


async def put_preferences(db: AsyncSession, tenant_id: str, actor_id: str, value: VisualizationPreferences) -> VisualizationPreferences:
    row = await db.scalar(select(VisualizationPreference).where(
        VisualizationPreference.tenant_id == tenant_id,
        VisualizationPreference.actor_id == actor_id,
    ))
    payload = value.model_dump()
    if row:
        row.preferences = payload
        row.schema_version = PREFERENCE_SCHEMA_VERSION
    else:
        db.add(VisualizationPreference(tenant_id=tenant_id, actor_id=actor_id, preferences=payload))
    await db.commit()
    return value


async def reset_preferences(db: AsyncSession, tenant_id: str, actor_id: str) -> VisualizationPreferences:
    row = await db.scalar(select(VisualizationPreference).where(
        VisualizationPreference.tenant_id == tenant_id,
        VisualizationPreference.actor_id == actor_id,
    ))
    if row:
        await db.delete(row)
        await db.commit()
    return VisualizationPreferences()


def preferred_chart_for_intent(preferences: VisualizationPreferences, intent: str) -> str | None:
    value = {
        "comparison": preferences.comparison_preference,
        "target_variance": preferences.comparison_preference,
        "trend": preferences.trend_preference,
        "composition": preferences.composition_preference,
    }.get(intent, "auto")
    return None if value == "auto" else value
