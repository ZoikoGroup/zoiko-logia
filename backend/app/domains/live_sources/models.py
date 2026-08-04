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

from sqlalchemy import Boolean, DateTime, Integer, JSON, String
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

    # ── Catalogue-required source metadata ──────────────────────────────
    # docs/Kriton_Authoritative_Sources_Catalog.md §"Required source
    # metadata" mandates these for every source Kriton relies on. The
    # columns above already covered source_id (provider_key),
    # authority_name (display_name), domain (category), api_base_url
    # (base_url), authentication_type (auth_mode) and tenant_entitlement
    # (tenant_id + is_tenant_private); the rest were documented but never
    # recorded, which made the catalogue unenforceable at runtime.
    #
    # Where the catalogue's field is inherently per-document rather than
    # per-provider (publication/effective/superseded dates), the column here
    # carries the PROVIDER-level meaning: when this integration became
    # authoritative for Kriton and when it stopped being so. Document-level
    # dates belong to the retrieved record, not to the registry row.

    # 1-6 from the catalogue's default authority hierarchy: 1 = enacted
    # legislation/regulation/binding decisions, 6 = commercial or secondary
    # discovery. Finer-grained than authority_level, which stays as the
    # licence gate's three-value vocabulary.
    authority_rank: Mapped[int] = mapped_column(Integer, nullable=False, default=4)
    # ISO-ish scope this provider is authoritative FOR ("GB", "US", "EU",
    # "UN", or "INTL" for an international organisation). Not the same as a
    # query's country: GLEIF is INTL but answers about a UK company.
    jurisdiction: Mapped[str] = mapped_column(String, nullable=False, default="INTL")
    # LIVE_API | SCHEDULED_FEED | VERSIONED_DOC | LICENSED_DOC | DISCOVERY_ONLY
    integration_type: Mapped[str] = mapped_column(String, nullable=False, default="LIVE_API")
    # Human-facing landing page. Distinct from base_url, which is the machine
    # endpoint and is frequently not a page a person can open.
    official_url: Mapped[str] = mapped_column(String, nullable=False, default="")
    licence_terms_url: Mapped[str] = mapped_column(String, nullable=False, default="")
    # free | mixed | paid | restricted — "free access does not remove
    # copyright, attribution, licensing or redistribution obligations", so
    # this is recorded separately from licence_state.
    pricing_model: Mapped[str] = mapped_column(String, nullable=False, default="free")
    # How stale this provider's data may be before an answer built on it
    # should be treated as unsupported. None = no stated SLA.
    freshness_sla_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_successful_sync: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Content hash of the last synchronised payload, for feed-backed
    # providers. Mirrors SanctionsSnapshot.content_sha256.
    last_content_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    # show | summarise | internal_reasoning_only — an explicit override of
    # the state the licence gate would otherwise derive. Empty means derive.
    display_permission: Mapped[str] = mapped_column(String, nullable=False, default="")
    # permitted | attribution_required | prohibited — whether content from
    # this source may leave Kriton in an export.
    export_permission: Mapped[str] = mapped_column(String, nullable=False, default="attribution_required")
    effective_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    superseded_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LiveFetchCache(Base):
    __tablename__ = "live_fetch_cache"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    provider_key: Mapped[str] = mapped_column(String, nullable=False, index=True)
    cache_key: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
