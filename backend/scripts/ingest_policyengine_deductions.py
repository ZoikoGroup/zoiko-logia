"""
Register the extracted PolicyEngine-US deductions parameters
(data/sources/us/US_PolicyEngine_Deductions.md, produced by
scripts/extract_policyengine_params.py against gov/irs/deductions/) as a
real governed Source — same create_source / approve_source_version /
ingest_document_content pattern as scripts/ingest_direct_file_eitc.py.

Idempotent: skips if a Source with this title already exists.
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

TITLE = "PolicyEngine-US Parameters — IRS Deductions (Standard, Itemized, QBI, Auto Loan Interest)"
CATEGORY = "tax"
SOURCE_CLASS = "Open-source tax-benefit microsimulation model (PolicyEngine-US)"
JURISDICTION = "US"
FILE_PATH = "data/sources/us/US_PolicyEngine_Deductions.md"


async def ingest() -> None:
    async with AsyncSessionLocal() as db:
        submitter = (await db.execute(select(User).where(User.email == SUBMITTER_EMAIL))).scalar_one()
        approver = (await db.execute(select(User).where(User.email == APPROVER_EMAIL))).scalar_one()

        existing = (await db.execute(select(Source).where(Source.title == TITLE))).scalar_one_or_none()
        if existing is not None:
            print(f"Already ingested, skipping: {TITLE}")
            return

        full_path = Path(__file__).resolve().parents[1] / FILE_PATH
        markdown_content = full_path.read_text()

        source = await create_source(
            db,
            submitter.id,
            SourceCreateRequest(
                category=CATEGORY,
                title=TITLE,
                source_class=SOURCE_CLASS,
                jurisdiction_scope=JURISDICTION,
                note=(
                    "Extracted from PolicyEngine-US's open-source parameter tree "
                    "(github.com/PolicyEngine/policyengine-us, "
                    "policyengine_us/parameters/gov/irs/deductions/) via "
                    "scripts/extract_policyengine_params.py — description, dated "
                    "values, and legal references only; PolicyEngine's Python "
                    "calculation logic (variables/) intentionally excluded."
                ),
                file_path=FILE_PATH,
            ),
            tenant_id=submitter.tenant_id,
        )
        print(f"Created ({CATEGORY}/{JURISDICTION}): {TITLE}")

        await approve_source_version(
            db, approver.id, source["id"], source["latest_version"].id, tenant_id=submitter.tenant_id,
        )
        print("  Approved.")

        try:
            await ingest_document_content(
                FILE_PATH,
                markdown_content,
                {
                    "title": TITLE,
                    "category": CATEGORY,
                    "jurisdiction_scope": JURISDICTION,
                    "version_label": source["latest_version"].version_label,
                    "tenant_id": submitter.tenant_id,
                    "source_id": source["id"],
                },
                db,
            )
            print("  Embedded into vector store.")
        except Exception as e:
            print(f"  WARNING: embedding failed: {e}")


if __name__ == "__main__":
    asyncio.run(ingest())
