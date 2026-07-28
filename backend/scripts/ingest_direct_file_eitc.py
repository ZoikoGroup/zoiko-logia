"""
Trial: register the extracted IRS Direct File EITC Fact Dictionary
(data/sources/us/US_DirectFile_EITC_FactDictionary.md, produced by
scripts/extract_direct_file_facts.py) as a real governed Source, following
the exact same create_source / approve_source_version / ingest_document_content
pattern as scripts/ingest_reference_sources.py — real maker-checker (two
accounts), real audit trail, real embedding into the vector store.

Unlike ingest_reference_sources.py, there's no PDF to parse here — the
content is already clean extracted text, so it's passed directly to
ingest_document_content() rather than through parser_service.py.

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

TITLE = "IRS Direct File Fact Dictionary — Earned Income Tax Credit (EITC)"
CATEGORY = "tax"
SOURCE_CLASS = "Tax authority (extracted from IRS open-source Direct File)"
JURISDICTION = "US"
FILE_PATH = "data/sources/us/US_DirectFile_EITC_FactDictionary.md"


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
                    "Extracted from IRS Direct File's open-source Fact Dictionary "
                    "(github.com/IRS-Public/direct-file, backend/src/main/resources/tax/eitc.xml) "
                    "via scripts/extract_direct_file_facts.py — Name+Description text only, "
                    "business-rule logic (Derived/Dependency nodes) intentionally excluded."
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
