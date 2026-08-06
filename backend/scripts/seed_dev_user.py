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
from app.domains.reference_data.service import (
    TREASURY_GOVERNED_SOURCE_ID,
    PAYROLL_TAX_GOVERNED_SOURCE_ID,
    CENSUS_GOVERNED_SOURCE_ID,
    BLS_CPI_GOVERNED_SOURCE_ID,
    BEA_GDP_GOVERNED_SOURCE_ID,
    FRED_INTEREST_RATES_GOVERNED_SOURCE_ID,
    CFR_TITLE26_GOVERNED_SOURCE_ID,
    FEDERAL_REGISTER_GOVERNED_SOURCE_ID,
    ECFR_TITLE26_GOVERNED_SOURCE_ID,
    CONGRESS_GOVERNED_SOURCE_ID,
    TAVILY_GOVERNED_SOURCE_ID,
    SERPAPI_GOVERNED_SOURCE_ID,
    SEC_GOVERNED_SOURCE_ID,
    REGULATIONS_GOV_GOVERNED_SOURCE_ID,
    ONS_INFLATION_GOVERNED_SOURCE_ID,
    ONS_GDP_GOVERNED_SOURCE_ID,
    BANK_OF_ENGLAND_GOVERNED_SOURCE_ID,
    VIES_GOVERNED_SOURCE_ID,
    SANCTIONS_GOVERNED_SOURCE_ID,
)
from app.domains.reference_data.bank_reconciliation import (
    BANK_RECONCILIATION_GOVERNED_SOURCE_ID,
)
from app.domains.reference_data.month_end_close import MONTH_END_CLOSE_GOVERNED_SOURCE_ID
from app.domains.reference_data.accounting_fundamentals import ACCOUNTING_FUNDAMENTALS_GOVERNED_SOURCE_ID
from app.domains.reference_data.user_provided_data import USER_PROVIDED_DATA_GOVERNED_SOURCE_ID
from app.domains.calculation.service import (
    POLICYENGINE_GOVERNED_SOURCE_ID,
    EXPRESSION_EVALUATOR_GOVERNED_SOURCE_ID,
    FORMULA_REGISTRY_GOVERNED_SOURCE_ID,
)
from app.domains.source_library.models import Source, SourceVersion
from app.domains.support_incident.models import SecurityIncident, SupportTicket

DEMO_EMAIL = "dashboard@zoikologia.com"
DEMO_PASSWORD = "Password234@"
DEMO_TENANT_NAME = "ZoikoLogia Demo Tenant"

# Real external URLs for the live reference-data sources' governed rows —
# lets the admin Source Library/Source Licensing pages show a "View source"
# link for these the same way Ask Kriton's chat citations already do
# dynamically per query (see reference_data/service.py's to_*_rag_chunk
# functions, which set metadata["file_path"] = bundle.source_url). These
# static URLs are the general dataset/API endpoint rather than a
# query-specific one (e.g. eCFR's URL points at Title 26 generally, not one
# section) — the seeded governance row isn't tied to any single query.
_LIVE_SOURCE_URLS: dict[str, str] = {
    TREASURY_GOVERNED_SOURCE_ID: "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/od/rates_of_exchange",
    PAYROLL_TAX_GOVERNED_SOURCE_ID: "https://payrolltaxapi.com/v1/rates/lookup",
    CENSUS_GOVERNED_SOURCE_ID: "https://api.census.gov/data/2024/acs/acs1",
    BLS_CPI_GOVERNED_SOURCE_ID: "https://api.bls.gov/publicAPI/v2/timeseries/data/CUUR0000SA0",
    BEA_GDP_GOVERNED_SOURCE_ID: "https://apps.bea.gov/api/data",
    FRED_INTEREST_RATES_GOVERNED_SOURCE_ID: "https://api.stlouisfed.org/fred/series/observations",
    CFR_TITLE26_GOVERNED_SOURCE_ID: "https://www.govinfo.gov/app/collection/cfr/2026/title26",
    ECFR_TITLE26_GOVERNED_SOURCE_ID: "https://www.ecfr.gov/current/title-26",
    FEDERAL_REGISTER_GOVERNED_SOURCE_ID: "https://www.federalregister.gov",
}

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
# Groq is role="Primary reasoning model" / status="Active" because it's the
# provider actually used in production today (app/domains/model_gateway/
# service.py's _select_model_and_adapter ranks providers groq > openai > ...
# — without this row, the registry's own data would disagree with real
# behavior and the new per-model routing logic would silently prefer
# GPT-4 Turbo instead the moment it shipped). GPT-4 Turbo is relabeled from
# "Primary" to "Secondary / fallback model" so the registry has exactly one
# canonical Primary row rather than two identically-labeled ones whose real
# precedence is only resolvable by reading the Python ranking constant.
# Claude's status stays "Active" despite its adapter (anthropic_adapter.py)
# being an unimplemented stub — status models governance/approval lifecycle,
# not engineering completeness; _select_model_and_adapter's "provider
# adapter not implemented" skip is the correct place to encode that fact.
MODELS = [
    ("Groq Llama 3.1 8B Instant", "Primary reasoning model", "Production", "llama-3.1-8b-instant", "Active", "groq"),
    ("GPT-4 Turbo", "Secondary / fallback model", "Production", "v2026.06", "Active", "openai"),
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
        auth_user = supabase_admin.get_user_by_email(DEMO_EMAIL)
        if auth_user is None:
            auth_user = supabase_admin.create_user(
                DEMO_EMAIL,
                DEMO_PASSWORD,
                email_confirm=True,
                user_id=user.id,
            )
        if auth_user["id"] != user.id:
            raise RuntimeError(f"Supabase/local identity mismatch for {DEMO_EMAIL}")
        supabase_admin.update_app_metadata(auth_user["id"], user.tenant_id, user.role)
        print(f"User {DEMO_EMAIL} already exists; authentication synchronized.")
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


# (id, title, source_class, authority_level, status, note) — two real,
# distinct governed entries under category="exchange-rate" so
# eligible_source_count lands on 2 (CONF_SUFFICIENT), not 1 (CONF_LIMITED,
# which risks routing every currency answer to human review instead of
# answering it — see routing_matrix.py's (RISK_MEDIUM, CONF_LIMITED) rule).
# jurisdiction_scope is "Global", not "US" — FX rates aren't jurisdiction-
# specific, and a "US"-scoped row would be wrongly excluded from a request
# with jurisdiction="UK" set.
EXCHANGE_RATE_SOURCES = [
    (
        TREASURY_GOVERNED_SOURCE_ID,
        "US Treasury Fiscal Data — Rates of Exchange",
        "Official government data source",
        "primary",
        "ACTIVE",
        "Live-queried at answer time via app.domains.reference_data.service.get_exchange_rate_bundle — "
        "content is not a static document, it's fetched fresh (subject to a 6h cache) per query.",
    ),
    (
        "src-treasury-fiscal-data-exchange-rates-docs",
        "US Treasury Fiscal Data — Rates of Exchange (Dataset Documentation)",
        "Official government documentation",
        "secondary",
        "ACTIVE",
        "Dataset/licence documentation for the Rates of Exchange dataset "
        "(https://fiscaldata.treasury.gov/datasets/treasury-reporting-rates-exchange/).",
    ),
]


async def seed_exchange_rate_sources(db, user: User) -> None:
    existing = await db.execute(select(Source).where(Source.category == "exchange-rate"))
    if existing.scalars().first() is not None:
        print("Exchange-rate source data already seeded, skipping.")
        return

    for source_id, title, source_class, authority_level, status, note in EXCHANGE_RATE_SOURCES:
        source = Source(
            id=source_id,
            category="exchange-rate",
            title=title,
            source_class=source_class,
            jurisdiction_scope="Global",
            authority_level=authority_level,
            licence_state="permitted",
        )
        db.add(source)
        await db.flush()
        db.add(
            SourceVersion(
                source_id=source.id,
                status=status,
                note=note,
                submitted_by=user.id,
                approved_by=user.id if status == "ACTIVE" else None,
                file_path=_LIVE_SOURCE_URLS.get(source_id),
            )
        )
    await db.commit()
    print(f"Seeded {len(EXCHANGE_RATE_SOURCES)} exchange-rate sources.")


async def seed_bank_reconciliation_sources(db, user: User) -> None:
    existing = await db.execute(
        select(Source).where(Source.id == BANK_RECONCILIATION_GOVERNED_SOURCE_ID)
    )
    if existing.scalars().first() is not None:
        print("Bank-reconciliation procedure already seeded, skipping.")
        return

    source = Source(
        id=BANK_RECONCILIATION_GOVERNED_SOURCE_ID,
        category="bank-reconciliation",
        title="Kriton Bank Reconciliation Educational Procedure",
        source_class="Reviewed internal educational procedure",
        jurisdiction_scope="Global",
        authority_level="secondary",
        licence_state="permitted",
    )
    db.add(source)
    await db.flush()
    db.add(SourceVersion(
        source_id=source.id,
        status="ACTIVE",
        note="Reviewed operational procedure for general bank-account reconciliation questions.",
        submitted_by=user.id,
        approved_by=user.id,
    ))
    await db.commit()
    print("Seeded bank-reconciliation educational procedure.")


async def seed_month_end_close_sources(db, user: User) -> None:
    existing = await db.execute(
        select(Source).where(Source.id == MONTH_END_CLOSE_GOVERNED_SOURCE_ID)
    )
    if existing.scalars().first() is not None:
        print("Month-end close procedure already seeded, skipping.")
        return
    source = Source(
        id=MONTH_END_CLOSE_GOVERNED_SOURCE_ID,
        category="month-end-close",
        title="Kriton Month-End Financial Close Educational Procedure",
        source_class="Reviewed internal educational procedure",
        jurisdiction_scope="Global",
        authority_level="secondary",
        licence_state="permitted",
    )
    db.add(source)
    await db.flush()
    db.add(SourceVersion(
        source_id=source.id,
        status="ACTIVE",
        note="Reviewed operational sequence for general month-end financial close questions.",
        submitted_by=user.id,
        approved_by=user.id,
    ))
    await db.commit()
    print("Seeded month-end close educational procedure.")


async def seed_accounting_fundamentals_sources(db, user: User) -> None:
    existing = await db.execute(select(Source).where(Source.id == ACCOUNTING_FUNDAMENTALS_GOVERNED_SOURCE_ID))
    if existing.scalars().first() is not None:
        print("Accounting-fundamentals source already seeded, skipping.")
        return
    source = Source(
        id=ACCOUNTING_FUNDAMENTALS_GOVERNED_SOURCE_ID,
        category="accounting-fundamentals",
        title="Kriton Accounting Fundamentals — Cash and Accrual Basis",
        source_class="Reviewed internal educational procedure",
        jurisdiction_scope="Global",
        authority_level="secondary",
        licence_state="permitted",
    )
    db.add(source)
    await db.flush()
    db.add(SourceVersion(
        source_id=source.id, status="ACTIVE",
        note="Reviewed educational grounding for cash-basis and accrual-basis explanations.",
        submitted_by=user.id, approved_by=user.id,
    ))
    await db.commit()
    print("Seeded accounting-fundamentals educational source.")


async def seed_user_provided_data_source(db, user: User) -> None:
    existing = await db.execute(select(Source).where(Source.id == USER_PROVIDED_DATA_GOVERNED_SOURCE_ID))
    if existing.scalars().first() is not None:
        print("User-provided-data source already seeded, skipping.")
        return
    source = Source(
        id=USER_PROVIDED_DATA_GOVERNED_SOURCE_ID,
        category="user-provided-data",
        title="Data supplied by the user in the current request",
        source_class="First-party request data",
        jurisdiction_scope="Global",
        authority_level="primary",
        licence_state="permitted",
    )
    db.add(source)
    await db.flush()
    db.add(SourceVersion(
        source_id=source.id, status="ACTIVE",
        note="Governance record for transient values explicitly supplied by the requesting user.",
        submitted_by=user.id, approved_by=user.id,
    ))
    await db.commit()
    print("Seeded user-provided-data governance source.")


# (id, title, source_class, authority_level, status, note) — two real,
# distinct governed entries under category="payroll-compliance", same
# eligible_source_count=2 reasoning as EXCHANGE_RATE_SOURCES above.
# jurisdiction_scope="US" (not "Global" like exchange-rate) — payroll tax
# data genuinely is US-specific, and confirmed against retrieve.py's actual
# jurisdiction check that this doesn't exclude the realistic request shapes
# this app sends (jurisdiction="" default, or "US"), only correctly excludes
# e.g. "UK".
PAYROLL_TAX_SOURCES = [
    (
        PAYROLL_TAX_GOVERNED_SOURCE_ID,
        "PayrollTax API — Rate Lookup",
        "Commercial data provider",
        "primary",
        "ACTIVE",
        "Live-queried at answer time via app.domains.reference_data.service.get_payroll_tax_bundle — "
        "content is not a static document, it's fetched fresh (subject to a 24h cache) per query.",
    ),
    (
        "src-payroll-tax-api-docs",
        "PayrollTax API — Documentation",
        "Commercial data provider documentation",
        "secondary",
        "ACTIVE",
        "API/licence documentation for https://payrolltaxapi.com/.",
    ),
]


async def seed_payroll_tax_sources(db, user: User) -> None:
    existing = await db.execute(select(Source).where(Source.category == "payroll-compliance"))
    if existing.scalars().first() is not None:
        print("Payroll-compliance source data already seeded, skipping.")
        return

    for source_id, title, source_class, authority_level, status, note in PAYROLL_TAX_SOURCES:
        source = Source(
            id=source_id,
            category="payroll-compliance",
            title=title,
            source_class=source_class,
            jurisdiction_scope="US",
            authority_level=authority_level,
            licence_state="permitted",
        )
        db.add(source)
        await db.flush()
        db.add(
            SourceVersion(
                source_id=source.id,
                status=status,
                note=note,
                submitted_by=user.id,
                approved_by=user.id if status == "ACTIVE" else None,
                file_path=_LIVE_SOURCE_URLS.get(source_id),
            )
        )
    await db.commit()
    print(f"Seeded {len(PAYROLL_TAX_SOURCES)} payroll-compliance sources.")


# Same 2-source / eligible_source_count=2 reasoning as PAYROLL_TAX_SOURCES
# above. jurisdiction_scope="Global" — ACS income/poverty data isn't
# jurisdiction-restricted in the way payroll withholding rules are; it's
# published federal statistics about every state, not a US-only tax rule.
ECONOMIC_DATA_SOURCES = [
    (
        CENSUS_GOVERNED_SOURCE_ID,
        "US Census Bureau — Income & Poverty by State (ACS)",
        "Government statistical agency",
        "primary",
        "ACTIVE",
        "Live-queried at answer time via app.domains.reference_data.service.get_census_income_poverty_bundle "
        "(American Community Survey 1-year estimates) — content is not a static document, it's fetched fresh "
        "(subject to a 24h cache) per query.",
    ),
    (
        "src-census-acs-docs",
        "US Census Bureau — American Community Survey Documentation",
        "Government statistical agency documentation",
        "secondary",
        "ACTIVE",
        "ACS methodology/variable documentation for https://www.census.gov/programs-surveys/acs.",
    ),
    (
        BLS_CPI_GOVERNED_SOURCE_ID,
        "US Bureau of Labor Statistics — CPI-U (Inflation)",
        "Government statistical agency",
        "primary",
        "ACTIVE",
        "Live-queried at answer time via app.domains.reference_data.service.get_cpi_bundle "
        "(Consumer Price Index for All Urban Consumers, series CUUR0000SA0) — content is not a static "
        "document, it's fetched fresh (subject to a 24h cache) per query.",
    ),
    (
        "src-bls-cpi-docs",
        "US Bureau of Labor Statistics — CPI Methodology Documentation",
        "Government statistical agency documentation",
        "secondary",
        "ACTIVE",
        "CPI methodology/series documentation for https://www.bls.gov/cpi/.",
    ),
    (
        BEA_GDP_GOVERNED_SOURCE_ID,
        "US Bureau of Economic Analysis — NIPA GDP (Table 1.1.5)",
        "Government statistical agency",
        "primary",
        "ACTIVE",
        "Live-queried at answer time via app.domains.reference_data.service.get_gdp_bundle "
        "(NIPA Table 1.1.5, Gross Domestic Product, current dollars) — content is not a static "
        "document, it's fetched fresh (subject to a 24h cache) per query.",
    ),
    (
        "src-bea-nipa-docs",
        "US Bureau of Economic Analysis — NIPA Methodology Documentation",
        "Government statistical agency documentation",
        "secondary",
        "ACTIVE",
        "NIPA handbook/methodology documentation for https://www.bea.gov/resources/methodologies/nipa-handbook.",
    ),
]


async def seed_economic_data_sources(db, user: User) -> None:
    # Per-source idempotency (not the blanket per-category check used by the
    # other seed_*_sources functions) — this category now has two unrelated
    # source pairs (Census, added first; BLS, added later), and a blanket
    # "any row in this category exists -> skip everything" check would have
    # silently skipped BLS forever once Census was already seeded.
    created = 0
    for source_id, title, source_class, authority_level, status, note in ECONOMIC_DATA_SOURCES:
        existing = await db.execute(select(Source).where(Source.id == source_id))
        if existing.scalar_one_or_none() is not None:
            print(f"Already seeded, skipping: {title}")
            continue
        created += 1

        source = Source(
            id=source_id,
            category="economic-data",
            title=title,
            source_class=source_class,
            jurisdiction_scope="Global",
            authority_level=authority_level,
            licence_state="permitted",
        )
        db.add(source)
        await db.flush()
        db.add(
            SourceVersion(
                source_id=source.id,
                status=status,
                note=note,
                submitted_by=user.id,
                approved_by=user.id if status == "ACTIVE" else None,
                file_path=_LIVE_SOURCE_URLS.get(source_id),
            )
        )
    await db.commit()
    print(f"Seeded {created} economic-data sources.")


# Same 2-source / eligible_source_count=2 reasoning as EXCHANGE_RATE_SOURCES
# above. jurisdiction_scope="Global" — FRED's rate series aren't a US-only
# statutory rule, they're published national market data. Blanket
# per-category idempotency (not per-source-id) is safe here since, unlike
# economic-data, "interest-rates" is a brand-new category owned solely by
# this one integration.
INTEREST_RATE_SOURCES = [
    (
        FRED_INTEREST_RATES_GOVERNED_SOURCE_ID,
        "Federal Reserve Economic Data (FRED) — Interest Rates",
        "Government statistical agency",
        "primary",
        "ACTIVE",
        "Live-queried at answer time via app.domains.reference_data.service.get_interest_rates_bundle "
        "(Fed funds rate, prime rate, 10/30-year Treasury yields, 30-year mortgage average) — content is "
        "not a static document, it's fetched fresh (subject to a 24h cache) per query.",
    ),
    (
        "src-fred-docs",
        "Federal Reserve Economic Data (FRED) — Documentation",
        "Government statistical agency documentation",
        "secondary",
        "ACTIVE",
        "FRED API/series documentation for https://fred.stlouisfed.org/docs/api/fred/.",
    ),
]


async def seed_interest_rate_sources(db, user: User) -> None:
    existing = await db.execute(select(Source).where(Source.category == "interest-rates"))
    if existing.scalars().first() is not None:
        print("Interest-rates source data already seeded, skipping.")
        return

    for source_id, title, source_class, authority_level, status, note in INTEREST_RATE_SOURCES:
        source = Source(
            id=source_id,
            category="interest-rates",
            title=title,
            source_class=source_class,
            jurisdiction_scope="Global",
            authority_level=authority_level,
            licence_state="permitted",
        )
        db.add(source)
        await db.flush()
        db.add(
            SourceVersion(
                source_id=source.id,
                status=status,
                note=note,
                submitted_by=user.id,
                approved_by=user.id if status == "ACTIVE" else None,
                file_path=_LIVE_SOURCE_URLS.get(source_id),
            )
        )
    await db.commit()
    print(f"Seeded {len(INTEREST_RATE_SOURCES)} interest-rates sources.")


# jurisdiction_scope="US" — 26 CFR is US federal tax regulation, not
# jurisdiction-agnostic global data. GovInfo (annual edition) and eCFR
# (current amended text) are both kept as separate primary sources here —
# comprehensive collection is the explicit goal, not picking one.
TAX_REGULATION_SOURCES = [
    (
        CFR_TITLE26_GOVERNED_SOURCE_ID,
        "GovInfo — 26 CFR (Internal Revenue Regulations)",
        "Official government regulatory text",
        "primary",
        "ACTIVE",
        "Live-queried at answer time via app.domains.reference_data.service.get_cfr_section_bundle "
        "(GovInfo API, Code of Federal Regulations Title 26) when a query names a specific section "
        "number — content is not a static document, it's fetched fresh (subject to a 7-day cache) per query.",
    ),
    (
        "src-govinfo-docs",
        "GovInfo — API Documentation",
        "Official government documentation",
        "secondary",
        "ACTIVE",
        "GovInfo API documentation for https://api.govinfo.gov/docs/.",
    ),
    (
        ECFR_TITLE26_GOVERNED_SOURCE_ID,
        "eCFR — Title 26 (Internal Revenue, Current)",
        "Official government regulatory text",
        "primary",
        "ACTIVE",
        "Live-queried at answer time via app.domains.reference_data.service.get_ecfr_section_bundle "
        "(eCFR API, current amended text of Title 26) when a query names a specific section number — "
        "content is not a static document, it's fetched fresh (subject to a 24h cache) per query.",
    ),
    (
        "src-ecfr-docs",
        "eCFR — API Documentation",
        "Official government documentation",
        "secondary",
        "ACTIVE",
        "eCFR API documentation for https://www.ecfr.gov/developers/documentation/api/v1.",
    ),
]


async def seed_tax_regulation_sources(db, user: User) -> None:
    # Per-source idempotency (not the blanket per-category check used
    # elsewhere) — this category now has two unrelated source pairs
    # (GovInfo, added first; eCFR, added later), and a blanket "any row in
    # this category exists -> skip everything" check would have silently
    # skipped eCFR forever once GovInfo was already seeded. Same fix
    # already applied once to seed_economic_data_sources for the same
    # reason.
    created = 0
    for source_id, title, source_class, authority_level, status, note in TAX_REGULATION_SOURCES:
        existing = await db.execute(select(Source).where(Source.id == source_id))
        if existing.scalar_one_or_none() is not None:
            print(f"Already seeded, skipping: {title}")
            continue
        created += 1

        source = Source(
            id=source_id,
            category="tax-regulations",
            title=title,
            source_class=source_class,
            jurisdiction_scope="US",
            authority_level=authority_level,
            licence_state="permitted",
        )
        db.add(source)
        await db.flush()
        db.add(
            SourceVersion(
                source_id=source.id,
                status=status,
                note=note,
                submitted_by=user.id,
                file_path=_LIVE_SOURCE_URLS.get(source_id),
                approved_by=user.id if status == "ACTIVE" else None,
            )
        )
    await db.commit()
    print(f"Seeded {created} tax-regulations sources.")


# Same 2-source / eligible_source_count=2 reasoning as the other seed lists
# above. jurisdiction_scope="Global" — the Federal Register isn't a US-tax-
# specific concept the way CFR/payroll are; it's the publication system for
# all federal agencies, including plenty of non-tax content.
FEDERAL_REGISTER_SOURCES = [
    (
        FEDERAL_REGISTER_GOVERNED_SOURCE_ID,
        "Federal Register — Document Lookup",
        "Official government publication",
        "primary",
        "ACTIVE",
        "Live-queried at answer time via app.domains.reference_data.service.get_federal_register_document_bundle "
        "(Federal Register API) when a query names a specific document number — content is not a static "
        "document, it's fetched fresh (subject to a 7-day cache) per query.",
    ),
    (
        "src-federal-register-docs",
        "Federal Register — API Documentation",
        "Official government documentation",
        "secondary",
        "ACTIVE",
        "Federal Register API documentation for https://www.federalregister.gov/developers/documentation/api/v1.",
    ),
]


# Seeded into category="tax" (not a new category) since that's where the
# ingested PolicyEngine parameter markdown and IRS Direct File content
# already live, and where orchestration/retrieve.py's infer_category
# already routes tax questions with authority_level="primary". Per-source
# idempotency (not blanket per-category) — "tax" already has other rows
# from ingest_policyengine_topics.py, so a blanket "any row in this
# category exists -> skip" check would silently skip this source forever.
POLICYENGINE_CALCULATION_SOURCES = [
    (
        POLICYENGINE_GOVERNED_SOURCE_ID,
        "PolicyEngine-US — Live Household Tax Calculation Engine",
        "Open-source tax-benefit microsimulation model (PolicyEngine-US), executed in-process",
        "primary",
        "ACTIVE",
        "Live-computed at answer time via app.domains.calculation.service.get_calculation_bundle "
        "(PolicyEngine-US Simulation, run in-process — no external API call, no cache: each "
        "calculation is specific to one household) when a query names an income figure and filing "
        "status. Computes real EITC/CTC/standard deduction/federal income tax, plus CA/NY state "
        "income tax when named — see app/domains/calculation/policyengine_engine.py for scope.",
    ),
]


# Governed calculation architecture, Phase 1 (docs/calculation_architecture.md)
# — the sandboxed arithmetic expression evaluator. Same "tax" category
# placement rationale as POLICYENGINE_CALCULATION_SOURCES above: the chunk
# is injected directly by orchestration/service.py rather than retrieved by
# category search, so this mainly registers eligibility, not routing.
EXPRESSION_EVALUATOR_CALCULATION_SOURCES = [
    (
        EXPRESSION_EVALUATOR_GOVERNED_SOURCE_ID,
        "Sandboxed Expression Evaluator — Live Arithmetic Calculation Engine",
        "Deterministic AST-based arithmetic evaluator (Python ast module, decimal.Decimal), executed in-process",
        "primary",
        "ACTIVE",
        "Live-computed at answer time via app.domains.calculation.router / expression_evaluator.py when a "
        "query names a plain two-figure arithmetic question (see arithmetic_extraction.py for the recognized "
        "shapes). Never calls eval()/exec(); only +, -, *, / and parentheses over numeric literals are permitted.",
    ),
]

# Governed calculation architecture, Phase 3 (docs/calculation_architecture.md)
# — the named formula registry (gross margin, depreciation, ratios, etc.).
FORMULA_REGISTRY_CALCULATION_SOURCES = [
    (
        FORMULA_REGISTRY_GOVERNED_SOURCE_ID,
        "Named Formula Registry — Governed Accounting/Finance/Tax/Audit Calculation Engine",
        "Versioned, pure-function formula registry (15 named accounting/finance/tax/audit formulas), executed in-process",
        "primary",
        "ACTIVE",
        "Live-computed at answer time via app.domains.calculation.formula_registry / router.py when a query "
        "names a supported formula (straight-line depreciation, gross margin, current ratio, etc. — see "
        "formula_registry.py for the full list). Every input is required explicitly; no assumption is ever "
        "silently defaulted.",
    ),
]


async def seed_policyengine_calculation_sources(db, user: User) -> None:
    created = 0
    for source_id, title, source_class, authority_level, status, note in POLICYENGINE_CALCULATION_SOURCES:
        existing = await db.execute(select(Source).where(Source.id == source_id))
        if existing.scalar_one_or_none() is not None:
            print(f"Already seeded, skipping: {title}")
            continue
        created += 1

        source = Source(
            id=source_id,
            category="tax",
            title=title,
            source_class=source_class,
            jurisdiction_scope="US",
            authority_level=authority_level,
            licence_state="permitted",
        )
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
    print(f"Seeded {created} tax-calculation sources.")


async def seed_expression_evaluator_calculation_sources(db, user: User) -> None:
    created = 0
    for source_id, title, source_class, authority_level, status, note in EXPRESSION_EVALUATOR_CALCULATION_SOURCES:
        existing = await db.execute(select(Source).where(Source.id == source_id))
        if existing.scalar_one_or_none() is not None:
            print(f"Already seeded, skipping: {title}")
            continue
        created += 1

        source = Source(
            id=source_id,
            category="tax",
            title=title,
            source_class=source_class,
            jurisdiction_scope="US",
            authority_level=authority_level,
            licence_state="permitted",
        )
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
    print(f"Seeded {created} expression-evaluator calculation sources.")


async def seed_formula_registry_calculation_sources(db, user: User) -> None:
    created = 0
    for source_id, title, source_class, authority_level, status, note in FORMULA_REGISTRY_CALCULATION_SOURCES:
        existing = await db.execute(select(Source).where(Source.id == source_id))
        if existing.scalar_one_or_none() is not None:
            print(f"Already seeded, skipping: {title}")
            continue
        created += 1

        source = Source(
            id=source_id,
            category="tax",
            title=title,
            source_class=source_class,
            jurisdiction_scope="US",
            authority_level=authority_level,
            licence_state="permitted",
        )
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
    print(f"Seeded {created} formula-registry calculation sources.")


async def seed_federal_register_sources(db, user: User) -> None:
    existing = await db.execute(select(Source).where(Source.category == "federal-register"))
    if existing.scalars().first() is not None:
        print("Federal-register source data already seeded, skipping.")
        return

    for source_id, title, source_class, authority_level, status, note in FEDERAL_REGISTER_SOURCES:
        source = Source(
            id=source_id,
            category="federal-register",
            title=title,
            source_class=source_class,
            jurisdiction_scope="Global",
            authority_level=authority_level,
            licence_state="permitted",
        )
        db.add(source)
        await db.flush()
        db.add(
            SourceVersion(
                source_id=source.id,
                status=status,
                note=note,
                submitted_by=user.id,
                file_path=_LIVE_SOURCE_URLS.get(source_id),
                approved_by=user.id if status == "ACTIVE" else None,
            )
        )
    await db.commit()
    print(f"Seeded {len(FEDERAL_REGISTER_SOURCES)} federal-register sources.")


CONGRESS_SOURCES = [
    (
        CONGRESS_GOVERNED_SOURCE_ID,
        "Congress.gov — Bill Lookup",
        "Official legislative information",
        "primary",
        "ACTIVE",
        "Live-queried from the official Congress.gov API when a question names both a bill "
        "identifier and its Congress number. Includes official metadata and the latest available CRS summary.",
    ),
]


async def seed_congress_sources(db, user: User) -> None:
    created = 0
    for source_id, title, source_class, authority_level, status, note in CONGRESS_SOURCES:
        existing = await db.execute(select(Source).where(Source.id == source_id))
        if existing.scalar_one_or_none() is not None:
            continue
        source = Source(
            id=source_id, category="us-legislation", title=title,
            source_class=source_class, jurisdiction_scope="US",
            authority_level=authority_level, licence_state="permitted",
        )
        db.add(source)
        await db.flush()
        db.add(SourceVersion(
            source_id=source.id, status=status, note=note,
            submitted_by=user.id, approved_by=user.id,
        ))
        created += 1
    await db.commit()
    print(f"Seeded {created} Congress.gov source(s).")


SEC_SOURCES = [
    (
        SEC_GOVERNED_SOURCE_ID,
        "SEC EDGAR — Company Facts",
        "Securities regulator",
        "primary",
        "ACTIVE",
        "Live-queried from the official SEC EDGAR company-facts XBRL API when a question "
        "names a real stock ticker (e.g. \"$AAPL\") and a known financial concept "
        "(revenue, net income, total assets, total liabilities, EPS). Returns the most "
        "recent annual (10-K) reported value.",
    ),
]


async def seed_sec_sources(db, user: User) -> None:
    created = 0
    for source_id, title, source_class, authority_level, status, note in SEC_SOURCES:
        existing = await db.execute(select(Source).where(Source.id == source_id))
        if existing.scalar_one_or_none() is not None:
            continue
        source = Source(
            id=source_id, category="sec-filings", title=title,
            source_class=source_class, jurisdiction_scope="US",
            authority_level=authority_level, licence_state="permitted",
        )
        db.add(source)
        await db.flush()
        db.add(SourceVersion(
            source_id=source.id, status=status, note=note,
            submitted_by=user.id, approved_by=user.id,
        ))
        created += 1
    await db.commit()
    print(f"Seeded {created} SEC EDGAR source(s).")


REGULATIONS_GOV_SOURCES = [
    (
        REGULATIONS_GOV_GOVERNED_SOURCE_ID,
        "Regulations.gov — Docket Lookup",
        "Federal regulatory docket system",
        "primary",
        "ACTIVE",
        "Live-queried from the official Regulations.gov API when a question names a "
        "complete, correctly-formatted federal rulemaking docket ID (e.g. "
        "\"IRS-2014-0019\"). Includes the docket's title, type, RIN, and abstract.",
    ),
]


async def seed_regulations_gov_sources(db, user: User) -> None:
    created = 0
    for source_id, title, source_class, authority_level, status, note in REGULATIONS_GOV_SOURCES:
        existing = await db.execute(select(Source).where(Source.id == source_id))
        if existing.scalar_one_or_none() is not None:
            continue
        source = Source(
            id=source_id, category="federal-register", title=title,
            source_class=source_class, jurisdiction_scope="US",
            authority_level=authority_level, licence_state="permitted",
        )
        db.add(source)
        await db.flush()
        db.add(SourceVersion(
            source_id=source.id, status=status, note=note,
            submitted_by=user.id, approved_by=user.id,
        ))
        created += 1
    await db.commit()
    print(f"Seeded {created} Regulations.gov source(s).")


UK_INTERNATIONAL_SOURCES = [
    (
        ONS_INFLATION_GOVERNED_SOURCE_ID, "ONS — CPIH (UK Inflation)", "economic-data",
        "UK national statistics authority", "primary", "ACTIVE",
        "Live-queried from the UK Office for National Statistics CPIH dataset when a question "
        "names the UK and asks about inflation. Returns the 12-month percentage change between "
        "the latest and same-month-prior-year published index values.",
    ),
    (
        ONS_GDP_GOVERNED_SOURCE_ID, "ONS — Monthly GDP Index (UK)", "economic-data",
        "UK national statistics authority", "primary", "ACTIVE",
        "Live-queried from the UK Office for National Statistics monthly GDP index dataset when "
        "a question names the UK and asks about GDP. Returns the 12-month percentage change "
        "between the latest and same-month-prior-year published index values.",
    ),
    (
        BANK_OF_ENGLAND_GOVERNED_SOURCE_ID, "Bank of England — Bank Rate", "interest-rates",
        "UK central bank", "primary", "ACTIVE",
        "Live-queried from the Bank of England's Interactive Statistical Database (IADB) when a "
        "question names the UK and asks about interest rates. Returns the current Bank Rate.",
    ),
    (
        VIES_GOVERNED_SOURCE_ID, "EU VIES — VAT Validation", "vat-validation",
        "EU tax authority system", "primary", "ACTIVE",
        "Live-queried from the European Commission's VIES system when a question names a "
        "complete EU VAT registration number (country code + number) alongside the phrase "
        "\"VAT number\"/\"VAT registration\". Returns validity and (if valid) the registered "
        "trader's name and address.",
    ),
    (
        SANCTIONS_GOVERNED_SOURCE_ID, "UN + UK Consolidated Sanctions Screening", "sanctions-screening",
        "UN Security Council + UK FCDO", "primary", "ACTIVE",
        "Live-screened against the UN Security Council Consolidated List and the UK Sanctions "
        "List (FCDO) when a question explicitly asks to screen/check a named individual or "
        "entity against the sanctions list. Name-based matching only — never a confirmed "
        "identity match on its own.",
    ),
]


_UK_INTERNATIONAL_JURISDICTIONS = {
    ONS_INFLATION_GOVERNED_SOURCE_ID: "UK",
    ONS_GDP_GOVERNED_SOURCE_ID: "UK",
    BANK_OF_ENGLAND_GOVERNED_SOURCE_ID: "UK",
    VIES_GOVERNED_SOURCE_ID: "EU",
    SANCTIONS_GOVERNED_SOURCE_ID: "Global",
}


async def seed_uk_international_sources(db, user: User) -> None:
    created = 0
    for source_id, title, category, source_class, authority_level, status, note in UK_INTERNATIONAL_SOURCES:
        existing = await db.execute(select(Source).where(Source.id == source_id))
        if existing.scalar_one_or_none() is not None:
            continue
        source = Source(
            id=source_id, category=category, title=title,
            source_class=source_class, jurisdiction_scope=_UK_INTERNATIONAL_JURISDICTIONS[source_id],
            authority_level=authority_level, licence_state="permitted",
        )
        db.add(source)
        await db.flush()
        db.add(SourceVersion(
            source_id=source.id, status=status, note=note,
            submitted_by=user.id, approved_by=user.id,
        ))
        created += 1
    await db.commit()
    print(f"Seeded {created} UK/international source(s).")


PROFESSIONAL_SEARCH_SOURCES = [
    (TAVILY_GOVERNED_SOURCE_ID, "Tavily — Approved Professional Authority Search"),
    (SERPAPI_GOVERNED_SOURCE_ID, "SerpAPI — Approved Professional Authority Search"),
]


async def seed_professional_search_sources(db, user: User) -> None:
    created = 0
    for source_id, title in PROFESSIONAL_SEARCH_SOURCES:
        existing = await db.execute(select(Source).where(Source.id == source_id))
        if existing.scalar_one_or_none() is not None:
            continue
        source = Source(
            id=source_id, category="standards", title=title,
            source_class="Restricted authoritative-domain web discovery",
            jurisdiction_scope="US", authority_level="secondary",
            licence_state="permitted",
        )
        db.add(source)
        await db.flush()
        db.add(SourceVersion(
            source_id=source.id, status="ACTIVE",
            note="Search is restricted to the configured professional-authority domain allowlist; fetched pages remain subject to answer validation.",
            submitted_by=user.id, approved_by=user.id,
        ))
        created += 1
    await db.commit()
    print(f"Seeded {created} professional web-search source(s).")


async def _backfill_groq_model_row(db) -> None:
    """Environments already seeded before per-model routing shipped have
    zero provider='groq' rows at all — _select_model_and_adapter would
    silently rank straight past Groq to the next candidate (GPT-4 Turbo),
    a real behavior regression for any environment except a freshly
    created one. Idempotent by provider (not by "any row exists," unlike
    seed_model_gateway_data's own guard below), so this is safe to run
    every time the seed service runs (docker-compose.yml's `seed` service
    re-runs this whole script on every `docker-compose up`)."""
    existing = await db.execute(select(ModelDefinition).where(ModelDefinition.provider == "groq"))
    if existing.scalars().first() is not None:
        return
    db.add(
        ModelDefinition(
            name="Groq Llama 3.1 8B Instant",
            role="Primary reasoning model",
            environment="Production",
            version="llama-3.1-8b-instant",
            status="Active",
            provider="groq",
        )
    )
    await db.commit()
    print("Backfilled missing Groq ModelDefinition row.")


async def _backfill_gpt4_turbo_role_relabel(db) -> None:
    """Cosmetic-only backfill, not a correctness fix (provider-preference
    ranking already puts groq ahead of openai even when both rows are
    role="Primary reasoning model" — see test_model_gateway_routing.py's
    test_provider_preference_order_within_same_role). This just makes an
    already-seeded registry's data match what MODELS documents: exactly one
    canonical Primary row (Groq) rather than two identically-labeled ones."""
    result = await db.execute(
        select(ModelDefinition).where(
            ModelDefinition.provider == "openai", ModelDefinition.role == "Primary reasoning model"
        )
    )
    row = result.scalars().first()
    if row is None:
        return
    row.role = "Secondary / fallback model"
    await db.commit()
    print("Relabeled pre-existing GPT-4 Turbo row from Primary to Secondary / fallback model.")


async def seed_model_gateway_data(db, user: User) -> None:
    await _backfill_groq_model_row(db)
    await _backfill_gpt4_turbo_role_relabel(db)

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
        await seed_bank_reconciliation_sources(db, user)
        await seed_month_end_close_sources(db, user)
        await seed_accounting_fundamentals_sources(db, user)
        await seed_user_provided_data_source(db, user)
        await seed_exchange_rate_sources(db, user)
        await seed_payroll_tax_sources(db, user)
        await seed_economic_data_sources(db, user)
        await seed_interest_rate_sources(db, user)
        await seed_tax_regulation_sources(db, user)
        await seed_federal_register_sources(db, user)
        await seed_congress_sources(db, user)
        await seed_sec_sources(db, user)
        await seed_regulations_gov_sources(db, user)
        await seed_uk_international_sources(db, user)
        await seed_professional_search_sources(db, user)
        await seed_policyengine_calculation_sources(db, user)
        await seed_expression_evaluator_calculation_sources(db, user)
        await seed_formula_registry_calculation_sources(db, user)
        await seed_model_gateway_data(db, user)


if __name__ == "__main__":
    asyncio.run(seed())
