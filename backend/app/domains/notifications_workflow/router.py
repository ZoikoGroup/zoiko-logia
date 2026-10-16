"""Notification bell and per-user settings.

  GET  /notifications/summary     — unread count + "needs your action" (polled by the bell)
  GET  /notifications             — the viewer's notifications, newest first
  POST /notifications/{id}/read   — mark one read
  POST /notifications/read-all    — mark all read
  GET  /me/settings               — the viewer's saved settings + notification kinds
  PATCH /me/settings              — update them
"""
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.identity.models import User
from app.domains.identity.rbac import get_current_user
from app.domains.notifications_workflow import service
from app.domains.notifications_workflow.models import UserSettings

router = APIRouter(tags=["Notifications & settings"])

# Matches the Ask Kriton jurisdiction picker (frontend Composer).
JURISDICTIONS = ("UK", "US", "US-CA", "IFRS", "UAE", "India", "EU")


@router.get("/notifications/summary")
async def get_summary(background: BackgroundTasks, user: User = Depends(get_current_user),
                      db: AsyncSession = Depends(get_db)) -> dict:
    # The ledger sweep runs after the response is sent, so the bell never
    # waits for it; anything it creates shows on the next check.
    background.add_task(service.sync_tenant_safely, user.tenant_id)
    return {
        "unread": await service.unread_count(db, user),
        "action_items": await service.action_items(db, user),
    }


@router.get("/notifications")
async def get_notifications(
    unread_only: bool = False,
    kind: str | None = Query(default=None, max_length=64),
    before: datetime | None = None,
    limit: int = Query(default=30, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    return await service.list_notifications(db, user, unread_only=unread_only, kind=kind, limit=limit, before=before)


@router.post("/notifications/read-all")
async def post_read_all(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    return {"updated": await service.mark_read(db, user)}


@router.post("/notifications/{notification_id}/read")
async def post_read(notification_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    return {"updated": await service.mark_read(db, user, notification_id)}


class SettingsUpdate(BaseModel):
    default_jurisdiction: Literal["", "UK", "US", "US-CA", "IFRS", "UAE", "India", "EU"] | None = None
    muted_notifications: list[str] | None = Field(default=None, max_length=50)

    @field_validator("muted_notifications")
    @classmethod
    def known_kinds(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        unknown = sorted(set(value) - set(service.NOTIFICATION_KINDS))
        if unknown:
            raise ValueError(f"Unknown notification types: {', '.join(unknown)}")
        return sorted(set(value))


def _settings_view(row: UserSettings | None) -> dict:
    prefs = (row.preferences if row else None) or {}
    return {
        "default_jurisdiction": prefs.get("default_jurisdiction", ""),
        "muted_notifications": prefs.get("muted_notifications", []),
        "notification_kinds": [{"kind": kind, "label": label} for kind, label in service.NOTIFICATION_KINDS.items()],
        "jurisdictions": list(JURISDICTIONS),
    }


@router.get("/me/settings")
async def get_settings(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    return _settings_view(await db.get(UserSettings, user.id))


@router.patch("/me/settings")
async def patch_settings(payload: SettingsUpdate, user: User = Depends(get_current_user),
                         db: AsyncSession = Depends(get_db)) -> dict:
    changes = payload.model_dump(exclude_none=True)
    if not changes:
        raise HTTPException(status_code=422, detail="Nothing to update.")
    row = await db.get(UserSettings, user.id)
    if row is None:
        row = UserSettings(user_id=user.id, tenant_id=user.tenant_id, preferences={})
        db.add(row)
    # Reassign (not mutate) so the JSON column is marked changed.
    row.preferences = {**(row.preferences or {}), **changes}
    await db.commit()
    await db.refresh(row)
    return _settings_view(row)
