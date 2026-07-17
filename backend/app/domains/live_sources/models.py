"""
Live/dynamic external data source registry + fetch cache.

LiveSourceProvider mirrors app.domains.source_library.models.Source's
governance vocabulary (licence_state/authority_level/is_tenant_private) so
license_gate.py can apply the same eligibility rules to a live connector as
it does to a governed document — a live source is just a different kind of
governed thing, not an ungoverned one.

LiveFetchCache is a plain Postgres-backed TTL cache (cache_key -> payload).
No Redis: at MVP scale (a handful of provider/indicator/country
combinations, refreshed hours-to-quarters apart) an indexed row lookup is
not a bottleneck. See app/domains/live_sources/cache.py.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class LiveSourceProvider(Base):
    __tablename__ = "live_source_providers"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, default="GLOBAL_CONTROL", index=True)
    provider_key: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)
    base_url: Mapped[str] = mapped_column(String, nullable=False)
    auth_mode: Mapped[str] = mapped_column(String, nullable=False, default="none")  # none | api_key
    # Name of the env var holding the key, never the key itself.
    api_key_env_var: Mapped[str | None] = mapped_column(String, nullable=True)
    licence_state: Mapped[str] = mapped_column(String, nullable=False, default="permitted")  # permitted | restricted | unknown
    authority_level: Mapped[str] = mapped_column(String, nullable=False, default="primary")  # primary | secondary | internal
    is_tenant_private: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="ACTIVE")  # ACTIVE | DISABLED
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class LiveFetchCache(Base):
    __tablename__ = "live_fetch_cache"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    provider_key: Mapped[str] = mapped_column(String, nullable=False, index=True)
    cache_key: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
