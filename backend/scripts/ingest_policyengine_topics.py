"""
Batch-register the extracted PolicyEngine-US parameter sets
(data/sources/us/US_PolicyEngine_*.md, produced by
scripts/extract_policyengine_params.py) as governed Sources — same
create_source / approve_source_version / ingest_document_content pattern as
scripts/ingest_direct_file_topics.py.

Idempotent: skips any title that already exists.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.domains.identity.models import User
from app.domains.source_library.models import Source
from app.domains.source_library.schemas import SourceCreateRequest
from app.domains.source_library.service import approve_source_version, create_source
from app.domains.source_library.ingestion_service import ingest_document_content

SUBMITTER_EMAIL = "dashboard@zoikologia.com"
APPROVER_EMAIL = "source.reviewer@zoikologia.com"

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "sources" / "us"
SOURCE_CLASS = "Open-source tax-benefit microsimulation model (PolicyEngine-US)"

# (filename, title, category, jurisdiction_scope)
MANIFEST = [
    ("US_PolicyEngine_Credits.md",
     "PolicyEngine-US Parameters — Federal Tax Credits (CTC, CDCC, PTC, EITC, Elderly/Disabled, Education, Energy, Clean Vehicle)",
     "tax", "US"),
    ("US_PolicyEngine_SocialSecurity.md",
     "PolicyEngine-US Parameters — Social Security (PIA, AIME, Retirement Age, SSI, Earnings Test)",
     "tax", "US"),
    ("US_PolicyEngine_CA_IncomeTax.md",
     "PolicyEngine-US Parameters — California State Income Tax (Rates, AGI, AMT, Deductions, Credits)",
     "tax", "CA"),
    ("US_PolicyEngine_NY_IncomeTax.md",
     "PolicyEngine-US Parameters — New York State Income Tax (Rates, AGI, Deductions, Credits, Payroll)",
     "tax", "NY"),
]


async def ingest() -> None:
    async with AsyncSessionLocal() as db:
        submitter = (await db.execute(select(User).where(User.email == SUBMITTER_EMAIL))).scalar_one()
        approver = (await db.execute(select(User).where(User.email == APPROVER_EMAIL))).scalar_one()

        created = skipped = embedded = embed_failed = 0
        for filename, title, category, jurisdiction in MANIFEST:
            existing = (await db.execute(select(Source).where(Source.title == title))).scalar_one_or_none()
            if existing is not None:
                print(f"Already ingested, skipping: {title}")
                skipped += 1
                continue

            full_path = DATA_DIR / filename
            if not full_path.exists():
                print(f"MISSING extracted file, skipping: {full_path}")
                continue

            markdown_content = full_path.read_text()
            rel_path = f"data/sources/us/{filename}"

            source = await create_source(
                db,
                submitter.id,
                SourceCreateRequest(
                    category=category,
                    title=title,
                    source_class=SOURCE_CLASS,
                    jurisdiction_scope=jurisdiction,
                    note=(
                        "Extracted from PolicyEngine-US's open-source parameter tree "
                        "(github.com/PolicyEngine/policyengine-us) via "
                        "scripts/extract_policyengine_params.py — description, dated "
                        "values, and legal references only; calculation logic excluded."
                    ),
                    file_path=rel_path,
                ),
                tenant_id=submitter.tenant_id,
            )
            created += 1
            print(f"Created ({category}/{jurisdiction}): {title}")

            await approve_source_version(
                db, approver.id, source["id"], source["latest_version"].id, tenant_id=submitter.tenant_id,
            )

            try:
                await ingest_document_content(
                    rel_path,
                    markdown_content,
                    {
                        "title": title,
                        "category": category,
                        "jurisdiction_scope": jurisdiction,
                        "version_label": source["latest_version"].version_label,
                        "tenant_id": submitter.tenant_id,
                        "source_id": source["id"],
                    },
                    db,
                )
                embedded += 1
                print("  Embedded into vector store.")
            except Exception as e:
                embed_failed += 1
                print(f"  WARNING: embedding failed: {e}")

        print(f"\nDone. created={created} skipped={skipped} embedded={embedded} embed_failed={embed_failed}")


if __name__ == "__main__":
    asyncio.run(ingest())
