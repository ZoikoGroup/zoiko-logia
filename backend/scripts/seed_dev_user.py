"""Seed the dev database with the demo tenant/user and the governance role reference data."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.core.database import AsyncSessionLocal, engine
from app.core.security import hash_password
from app.db.base import Base
from app.domains.identity.models import Role, Tenant, User

DEMO_EMAIL = "dashboard@zoikologia.com"
DEMO_PASSWORD = "Password234@"
DEMO_TENANT_NAME = "ZoikoLogia Demo Tenant"

# Same 6 roles previously hardcoded in frontend/lib/governance-data.ts's ROLES export.
ROLES = [
    ("Governance Ops Lead", "Owns day-to-day governance operations", "Full read/write across all modules"),
    ("Source Admin", "Manages source approvals and licensing", "Source licensing, Compliance calendar"),
    ("Syllabus Admin", "Maintains ontology & syllabus content", "Ontology & syllabus"),
    ("Jurisdiction Lead", "Owns jurisdiction rollout readiness", "Jurisdiction rollout"),
    ("Risk Admin", "Owns risk policy and evaluation gates", "Risk policy, Evaluation gates, Model & prompt registry"),
    ("System Auditor", "Read-only access for audit purposes", "Audit replay, Incident response (read-only)"),
]


async def seed_demo_user(db) -> None:
    existing = await db.execute(select(User).where(User.email == DEMO_EMAIL))
    if existing.scalar_one_or_none() is not None:
        print(f"User {DEMO_EMAIL} already exists, skipping.")
        return

    tenant = Tenant(name=DEMO_TENANT_NAME)
    db.add(tenant)
    await db.flush()

    user = User(
        tenant_id=tenant.id,
        email=DEMO_EMAIL,
        hashed_password=hash_password(DEMO_PASSWORD),
        full_name="Dashboard Admin",
        role="Admin",
        is_active=True,
    )
    db.add(user)
    await db.commit()
    print(f"Seeded tenant '{tenant.name}' and user '{user.email}'.")


async def seed_roles(db) -> None:
    existing = await db.execute(select(Role))
    if existing.scalars().first() is not None:
        print("Roles already seeded, skipping.")
        return

    for name, description, permissions_summary in ROLES:
        db.add(Role(name=name, description=description, permissions_summary=permissions_summary))
    await db.commit()
    print(f"Seeded {len(ROLES)} roles.")


async def seed() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        await seed_demo_user(db)
        await seed_roles(db)


if __name__ == "__main__":
    asyncio.run(seed())
