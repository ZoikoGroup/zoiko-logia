"""ISSUE-4 regression — PATCH /auth/me must not wipe fields the request
omitted.

Previously ProfileUpdateRequest defaulted every name field to "" and the
service assigned both unconditionally, so a partial update like
{"first_name": "New"} silently blanked the existing last_name and rebuilt
full_name from the trash. A self-service profile edit must be a patch, not
a replace.

Contract asserted here:
  * omitted field (None in schema) is preserved byte-for-byte
  * full_name is rebuilt from existing + provided values only
  * the audit fields_changed lists exactly the provided fields
  * only the caller's own row is touched
  * a body with no fields at all is still rejected
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.domains.audit_ledger.models import AuditEvent
from app.domains.identity.models import Tenant, User
from app.domains.identity.router import patch_me
from app.domains.identity.schemas import ProfileUpdateRequest
from app.domains.identity.service import get_user_by_id

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def profile_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as db:
        db.add_all([
            Tenant(id="tenant-1", name="Tenant One"),
            User(
                id="user-1", tenant_id="tenant-1", email="u1@example.com",
                first_name="Ada", last_name="Lovelace", full_name="Ada Lovelace",
                role="Admin", is_active=True,
            ),
            User(
                id="user-2", tenant_id="tenant-1", email="u2@example.com",
                first_name="Grace", last_name="Hopper", full_name="Grace Hopper",
                role="Accountant", is_active=True,
            ),
        ])
        await db.commit()
        yield db
    await engine.dispose()


async def _first_event(db, event_name: str) -> AuditEvent:
    result = await db.execute(
        select(AuditEvent).where(AuditEvent.event_name == event_name).order_by(AuditEvent.ingested_at.desc())
    )
    return result.scalars().first()


async def test_first_name_only_patch_preserves_last_name(profile_db) -> None:
    db = profile_db
    current = await get_user_by_id(db, "user-1")

    result = await patch_me(ProfileUpdateRequest(first_name="Augusta"), db, current)
    assert result.first_name == "Augusta"
    assert result.last_name == "Lovelace", "omitted last_name must survive a first_name-only PATCH"
    assert result.full_name == "Augusta Lovelace"

    persisted = await get_user_by_id(db, "user-1")
    assert persisted.last_name == "Lovelace"


async def test_last_name_only_patch_preserves_first_name(profile_db) -> None:
    db = profile_db
    current = await get_user_by_id(db, "user-1")

    result = await patch_me(ProfileUpdateRequest(last_name="Byron"), db, current)
    assert result.first_name == "Ada", "omitted first_name must survive a last_name-only PATCH"
    assert result.last_name == "Byron"
    assert result.full_name == "Ada Byron"


async def test_empty_body_still_rejected(profile_db) -> None:
    with pytest.raises(ValidationError):
        ProfileUpdateRequest()
    with pytest.raises(ValidationError):
        ProfileUpdateRequest(first_name="", last_name="")


async def test_blank_provided_field_behaves_like_before(profile_db) -> None:
    """Explicit "" for one field is a provided value (clearing allowed); an
    all-blank body is still a validation error, unchanged from before."""
    db = profile_db
    current = await get_user_by_id(db, "user-1")

    result = await patch_me(ProfileUpdateRequest(first_name="", last_name="King"), db, current)
    assert result.first_name == ""
    assert result.last_name == "King"
    assert result.full_name == "King"


async def test_full_name_rebuilt_from_merge_not_from_input_only(profile_db) -> None:
    db = profile_db
    current = await get_user_by_id(db, "user-2")

    result = await patch_me(ProfileUpdateRequest(first_name="Grace B."), db, current)
    assert result.last_name == "Hopper"
    assert result.full_name == "Grace B. Hopper"
    assert result.full_name != "Grace B. "


async def test_partial_patch_touches_only_own_row(profile_db) -> None:
    db = profile_db
    current = await get_user_by_id(db, "user-1")

    await patch_me(ProfileUpdateRequest(first_name="Ada"), db, current)
    neighbour = await get_user_by_id(db, "user-2")
    assert neighbour.full_name == "Grace Hopper"


async def test_partial_patch_audits_only_provided_fields(profile_db) -> None:
    db = profile_db
    current = await get_user_by_id(db, "user-1")

    await patch_me(ProfileUpdateRequest(last_name="King"), db, current)
    event = await _first_event(db, "auth.profile_updated")
    assert event is not None
    assert event.actor_id == "user-1"
    assert event.payload["fields_changed"] == ["last_name"]

    await patch_me(ProfileUpdateRequest(first_name="Augusta", last_name="King"), db, current)
    event = await _first_event(db, "auth.profile_updated")
    assert sorted(event.payload["fields_changed"]) == ["first_name", "last_name"]