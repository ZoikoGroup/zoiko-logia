"""Seed the dev database with the demo tenant/user and reference/sample data."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.core import supabase_admin
from app.core.database import AsyncSessionLocal, async_engine
from app.db.base import Base
from app.domains.identity.models import Role, Tenant, User
from app.domains.learning_cpd.models import SyllabusPathway, TopicMapNode
from app.domains.model_gateway.models import ModelDefinition, PromptTemplate
from app.domains.source_library.models import Source, SourceVersion
from app.domains.support_incident.models import SecurityIncident, SupportTicket

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

# Sample incidents matching the shape previously hardcoded in
# frontend/lib/governance-data.ts's INCIDENTS export.
INCIDENTS = [
    ("Unsafe answer theme detected in AU tax queries", "High", "Investigating"),
    ("Source dispute: IFRS 15 revenue example outdated", "Medium", "Investigating"),
    ("Evidence export delay for enterprise tenant", "Medium", "Resolved"),
]

SYLLABUS_PATHWAYS = [
    ("ACCA", "Financial Reporting", "Revenue Recognition", "Deferred Revenue", "Apply IFRS 15 to multi-period contracts"),
    ("AICPA", "FAR", "Accruals", "Accrued Expenses", "Record period-end accrual adjustments"),
]

TOPIC_MAP_NODES = [
    ("Deferred Revenue", "Accruals, Revenue Recognition, Contract Terms", "IFRS 15, ASC 606, Local GAAP variants"),
    ("Accrued Expenses", "Accruals, Matching Principle", "IFRS, US GAAP"),
]

# (category, title, source_class, status, note)
SOURCES = [
    ("standards", "FASB ASC", "Professional standard-setter", "ACTIVE", "Citation + export allowed"),
    ("standards", "AICPA practice aid", "Licensed professional content", "PROPOSED", "Display limited"),
    ("tax", "Local tax bulletin", "Official administrative guidance", "UNDER_REVIEW", "Effective date changed"),
]

# (name, role, environment, version, status, provider) - same shape previously
# hardcoded in frontend/lib/governance-data.ts's MODEL_REGISTRY export.
MODELS = [
    ("GPT-4 Turbo", "Primary reasoning model", "Production", "v2026.06", "Active", "openai"),
    ("Claude 3.5", "Secondary / fallback model", "Production", "v2026.05", "Active", "anthropic"),
    ("Internal Embedding Model", "Vector search embeddings", "Staging", "v0.9", "Testing", "self_hosted"),
]

# (name, version, status, mode) - same shape previously hardcoded in
# frontend/lib/governance-data.ts's PROMPT_REGISTRY export.
PROMPTS = [
    ("Policy Q&A v4", "v4.2", "Approved", "Workflow"),
    ("Risk Classification v2", "v2.1", "PendingReview", "Review"),
    ("Escalation Summarizer", "v1.0", "Approved", "Review"),
]


def _get_or_create_auth_user(email: str, password: str) -> dict:
    """Supabase now owns credentials — the local `users` row must be keyed
    by the id Supabase's Admin API assigns, not a locally-generated uuid."""
    return supabase_admin.get_user_by_email(email) or supabase_admin.create_user(email, password, email_confirm=True)


async def seed_demo_user(db) -> User:
    existing = await db.execute(select(User).where(User.email == DEMO_EMAIL))
    user = existing.scalar_one_or_none()
    if user is not None:
        print(f"User {DEMO_EMAIL} already exists, skipping.")
        return user

    if not supabase_admin.is_configured():
        raise RuntimeError(
            "SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY must be set in backend/.env — "
            "Supabase now owns credentials, so seeding a login-capable demo user "
            "requires creating it via the Supabase Admin API."
        )

    tenant = Tenant(name=DEMO_TENANT_NAME)
    db.add(tenant)
    await db.flush()

    admin_auth_user = _get_or_create_auth_user(DEMO_EMAIL, DEMO_PASSWORD)
    user = User(
        id=admin_auth_user["id"],
        tenant_id=tenant.id,
        email=DEMO_EMAIL,
        first_name="Dashboard",
        last_name="Admin",
        full_name="Dashboard Admin",
        role="Admin",
        is_active=True,
    )
    db.add(user)

    # Second account required by scripts/ingest_reference_sources.py's maker-checker
    # flow: the submitting admin (above) cannot approve its own source versions.
    reviewer_auth_user = _get_or_create_auth_user("source.reviewer@zoikologia.com", DEMO_PASSWORD)
    db.add(User(
        id=reviewer_auth_user["id"],
        tenant_id=tenant.id,
        email="source.reviewer@zoikologia.com",
        first_name="Source",
        last_name="Reviewer",
        full_name="Source Reviewer",
        role="Admin",
        is_active=True,
    ))

    await db.commit()
    await db.refresh(user)
    supabase_admin.update_app_metadata(admin_auth_user["id"], user.tenant_id, user.role)
    supabase_admin.update_app_metadata(reviewer_auth_user["id"], user.tenant_id, "Admin")
    print(f"Seeded tenant '{tenant.name}', user '{user.email}', and reviewer 'source.reviewer@zoikologia.com'.")
    return user


async def seed_roles(db) -> None:
    existing = await db.execute(select(Role))
    if existing.scalars().first() is not None:
        print("Roles already seeded, skipping.")
        return

    for name, description, permissions_summary in ROLES:
        db.add(Role(name=name, description=description, permissions_summary=permissions_summary))
    await db.commit()
    print(f"Seeded {len(ROLES)} roles.")


async def seed_support_data(db, user: User) -> None:
    existing = await db.execute(select(SecurityIncident))
    if existing.scalars().first() is not None:
        print("Support/incident sample data already seeded, skipping.")
        return

    for title, severity, status in INCIDENTS:
        db.add(SecurityIncident(
            tenant_id=user.tenant_id,
            title=title,
            severity=severity,
            containment_status="RESOLVED" if status == "Resolved" else "OPEN",
            source="dev_seed",
        ))

    db.add(
        SupportTicket(
            tenant_id=user.tenant_id,
            category="accuracy",
            severity="P2",
            status="Open",
            created_by=user.id,
        )
    )
    await db.commit()
    print(f"Seeded {len(INCIDENTS)} incidents and 1 sample support ticket.")


async def seed_learning_data(db) -> None:
    existing = await db.execute(select(SyllabusPathway))
    if existing.scalars().first() is not None:
        print("Learning/CPD reference data already seeded, skipping.")
        return

    for body, qualification, module, topic, outcome in SYLLABUS_PATHWAYS:
        db.add(
            SyllabusPathway(
                body=body, qualification=qualification, module=module, topic=topic, learning_outcome=outcome
            )
        )
    for topic, prerequisites, standards in TOPIC_MAP_NODES:
        db.add(TopicMapNode(topic=topic, prerequisites=prerequisites, standards_summary=standards))
    await db.commit()
    print(f"Seeded {len(SYLLABUS_PATHWAYS)} syllabus pathways and {len(TOPIC_MAP_NODES)} topic map nodes.")


async def seed_source_data(db, user: User) -> None:
    existing = await db.execute(select(Source))
    if existing.scalars().first() is not None:
        print("Source library sample data already seeded, skipping.")
        return

    for category, title, source_class, status, note in SOURCES:
        source = Source(category=category, title=title, source_class=source_class)
        db.add(source)
        await db.flush()
        db.add(
            SourceVersion(
                source_id=source.id,
                status=status,
                note=note,
                submitted_by=user.id,
                approved_by=user.id if status == "ACTIVE" else None,
            )
        )
    await db.commit()
    print(f"Seeded {len(SOURCES)} sources.")


async def seed_model_gateway_data(db, user: User) -> None:
    existing = await db.execute(select(ModelDefinition))
    if existing.scalars().first() is not None:
        print("Model/prompt registry sample data already seeded, skipping.")
        return

    for name, role, environment, version, status, provider in MODELS:
        db.add(
            ModelDefinition(
                name=name, role=role, environment=environment, version=version, status=status, provider=provider
            )
        )
    for name, version, status, mode in PROMPTS:
        db.add(
            PromptTemplate(
                name=name,
                version=version,
                status=status,
                mode=mode,
                submitted_by=user.id,
                approved_by=user.id if status == "Approved" else None,
            )
        )
    await db.commit()
    print(f"Seeded {len(MODELS)} models and {len(PROMPTS)} prompt templates.")


async def seed() -> None:
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        user = await seed_demo_user(db)
        await seed_roles(db)
        await seed_support_data(db, user)
        await seed_learning_data(db)
        await seed_source_data(db, user)
        await seed_model_gateway_data(db, user)


if __name__ == "__main__":
    asyncio.run(seed())
