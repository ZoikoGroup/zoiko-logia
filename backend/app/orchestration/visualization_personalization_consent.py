"""V10 — explicit, tenant/user-scoped consent for personalized visualization
ranking. Mirrors visualization_preferences.py's shape deliberately: a
missing row means "never consented" and returns an all-defaults/disabled
object rather than implicitly creating one — personalization_enabled
defaults False, so continued product use alone can never turn this on.

Three distinct actions, matching the DATA RETENTION requirements:
  - put_consent(): change settings (may enable/disable/change scope).
  - reset_learned_profile() [visualization_personalization.py]: clears the
    LEARNED profile only, keeps consent settings as-is.
  - delete_personalization(): removes consent AND the learned profile —
    the full "disable and delete" teardown.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.orchestration.models import VisualizationPersonalizationConsent, VisualizationPersonalizationProfile

CONSENT_SCHEMA_VERSION = "1.0"

PersonalizationScope = Literal["visualization_only"]
HistoryWindow = Literal["30_days", "90_days", "180_days"]

HISTORY_WINDOW_DAYS: dict[str, int] = {"30_days": 30, "90_days": 90, "180_days": 180}


class PersonalizationConsent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    personalization_enabled: bool = False
    personalization_scope: PersonalizationScope = "visualization_only"
    personalization_history_window: HistoryWindow = "90_days"
    allow_view_switch_learning: bool = True
    allow_export_learning: bool = True
    allow_save_learning: bool = True
    consent_updated_at: datetime | None = None
    schema_version: Literal["1.0"] = CONSENT_SCHEMA_VERSION


async def _get_row(db: AsyncSession, tenant_id: str, actor_id: str) -> VisualizationPersonalizationConsent | None:
    return await db.scalar(select(VisualizationPersonalizationConsent).where(
        VisualizationPersonalizationConsent.tenant_id == tenant_id,
        VisualizationPersonalizationConsent.actor_id == actor_id,
    ))


async def get_consent(db: AsyncSession, tenant_id: str, actor_id: str) -> PersonalizationConsent:
    row = await _get_row(db, tenant_id, actor_id)
    if row is None:
        return PersonalizationConsent()
    return PersonalizationConsent(
        personalization_enabled=row.personalization_enabled,
        personalization_scope=row.personalization_scope,
        personalization_history_window=row.personalization_history_window,
        allow_view_switch_learning=row.allow_view_switch_learning,
        allow_export_learning=row.allow_export_learning,
        allow_save_learning=row.allow_save_learning,
        consent_updated_at=row.consent_updated_at,
    )


async def put_consent(db: AsyncSession, tenant_id: str, actor_id: str, value: PersonalizationConsent) -> PersonalizationConsent:
    """Requirement 4: consent is never inferred — this is the ONLY write
    path, and it always requires an explicit caller-supplied payload.
    Disabling here (personalization_enabled=False) takes effect on the
    very next request, since resolve_personalization_hint reads consent
    live every time — no separate "stop learning" step is needed beyond
    this call, satisfying requirement 5."""
    row = await _get_row(db, tenant_id, actor_id)
    now = datetime.now(timezone.utc)
    if row:
        row.personalization_enabled = value.personalization_enabled
        row.personalization_scope = value.personalization_scope
        row.personalization_history_window = value.personalization_history_window
        row.allow_view_switch_learning = value.allow_view_switch_learning
        row.allow_export_learning = value.allow_export_learning
        row.allow_save_learning = value.allow_save_learning
        row.consent_updated_at = now
    else:
        row = VisualizationPersonalizationConsent(
            tenant_id=tenant_id, actor_id=actor_id,
            personalization_enabled=value.personalization_enabled,
            personalization_scope=value.personalization_scope,
            personalization_history_window=value.personalization_history_window,
            allow_view_switch_learning=value.allow_view_switch_learning,
            allow_export_learning=value.allow_export_learning,
            allow_save_learning=value.allow_save_learning,
            consent_updated_at=now,
        )
        db.add(row)
    await db.commit()
    return await get_consent(db, tenant_id, actor_id)


async def delete_personalization(db: AsyncSession, tenant_id: str, actor_id: str) -> None:
    """Requirement (DATA RETENTION #5): removes the consent record AND the
    learned profile — the full "disable and delete" teardown the frontend's
    combined action triggers. Idempotent: deleting an already-absent
    profile/consent is a no-op, not an error."""
    consent_row = await _get_row(db, tenant_id, actor_id)
    if consent_row is not None:
        await db.delete(consent_row)
    profile_row = await db.scalar(select(VisualizationPersonalizationProfile).where(
        VisualizationPersonalizationProfile.tenant_id == tenant_id,
        VisualizationPersonalizationProfile.actor_id == actor_id,
    ))
    if profile_row is not None:
        await db.delete(profile_row)
    await db.commit()


async def delete_tenant_personalization(db: AsyncSession, tenant_id: str) -> None:
    """Requirement (DATA RETENTION #6): tenant deletion must remove every
    tenant-scoped personalization record, not just one actor's."""
    consents = (await db.execute(select(VisualizationPersonalizationConsent).where(
        VisualizationPersonalizationConsent.tenant_id == tenant_id,
    ))).scalars().all()
    for row in consents:
        await db.delete(row)
    profiles = (await db.execute(select(VisualizationPersonalizationProfile).where(
        VisualizationPersonalizationProfile.tenant_id == tenant_id,
    ))).scalars().all()
    for row in profiles:
        await db.delete(row)
    await db.commit()
