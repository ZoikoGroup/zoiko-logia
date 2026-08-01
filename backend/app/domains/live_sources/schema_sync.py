"""
In-place column reconciliation for `live_source_providers`.

The table is created by Base.metadata.create_all rather than by an Alembic
revision, and create_all only ever creates missing TABLES — it never alters
an existing one. So adding a column to the model leaves every database that
already has the table on the old schema, failing at the first INSERT.

Kept here rather than inline in app/main.py so the test suite can apply the
same reconciliation against the same definitions. A test database that
drifts from the runtime's schema tests a schema nobody deploys.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

# (column, sqlite type, postgres type, default literal or None)
# docs/Kriton_Authoritative_Sources_Catalog.md §"Required source metadata".
PROVIDER_COLUMNS: tuple[tuple[str, str, str, str | None], ...] = (
    ("authority_rank", "INTEGER", "INTEGER", "4"),
    ("jurisdiction", "VARCHAR", "VARCHAR", "'INTL'"),
    ("integration_type", "VARCHAR", "VARCHAR", "'LIVE_API'"),
    ("official_url", "VARCHAR", "VARCHAR", "''"),
    ("licence_terms_url", "VARCHAR", "VARCHAR", "''"),
    ("pricing_model", "VARCHAR", "VARCHAR", "'free'"),
    ("freshness_sla_seconds", "INTEGER", "INTEGER", None),
    ("last_successful_sync", "TIMESTAMP", "TIMESTAMPTZ", None),
    ("last_content_hash", "VARCHAR", "VARCHAR", None),
    ("display_permission", "VARCHAR", "VARCHAR", "''"),
    ("export_permission", "VARCHAR", "VARCHAR", "'attribution_required'"),
    ("effective_date", "TIMESTAMP", "TIMESTAMPTZ", None),
    ("superseded_date", "TIMESTAMP", "TIMESTAMPTZ", None),
)


async def ensure_provider_columns(engine: AsyncEngine, *, is_sqlite: bool) -> None:
    async with engine.begin() as conn:
        if is_sqlite:
            result = await conn.execute(text("PRAGMA table_info(live_source_providers)"))
            existing = {row[1] for row in result}
            if not existing:
                # No table yet — create_all owns creating it, and it will do
                # so with every column already present.
                return
            for column, sqlite_type, _, default in PROVIDER_COLUMNS:
                if column in existing:
                    continue
                suffix = f" NOT NULL DEFAULT {default}" if default else ""
                await conn.execute(text(
                    f"ALTER TABLE live_source_providers ADD COLUMN {column} {sqlite_type}{suffix}"
                ))
        else:
            for column, _, pg_type, default in PROVIDER_COLUMNS:
                suffix = f" NOT NULL DEFAULT {default}" if default else ""
                await conn.execute(text(
                    f"ALTER TABLE live_source_providers ADD COLUMN IF NOT EXISTS {column} {pg_type}{suffix}"
                ))
