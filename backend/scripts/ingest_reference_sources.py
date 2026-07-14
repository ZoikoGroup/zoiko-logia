"""
Ingest the reference PDFs under data/sources/{uk,us}/ into the source_library
domain as real, governed Source/SourceVersion records — closing the gap
where those files sat on disk unconnected to anything — AND into the
kriton_vector_nodes vector store so they're actually retrievable by Ask
Kriton. Previously this script only did the former: it created governance
metadata rows via create_source/approve_source_version but never called the
embedding pipeline, so nothing it "ingested" was ever findable by real
retrieval — the only path that populated real vectors was uploading files
one-by-one through POST /kriton/upload.

Titles/categories below were derived from each PDF's actual first-page text
(extracted with pypdf), not guessed from filenames. Runs through the same
create_source / approve_source_version service functions the API uses, so
every ingested source gets a real source_ingestion_event /
source_version_approved audit trail and goes through real maker-checker
(a second account, "source.reviewer@zoikologia.com", approves — the
submitting admin cannot approve its own submission).

One file (UK_legislation1.pdf — the Mental Capacity Act 2005) doesn't fit any
accounting/tax/audit category; it's intentionally left PROPOSED rather than
auto-approved, exactly like a human reviewer would flag it in the real
Source Licensing workflow. Embedding only runs for auto_approve=True sources
— the vector retrieval path (app/domains/rag/retrieval.py) has no
governance-status filter of its own, unlike the keyword_mvp path, so
embedding a still-PROPOSED document would make it retrievable before human
review, defeating the point of leaving it PROPOSED.

Idempotent: re-running skips any title that already exists. Embedding
failures are logged and counted but don't abort the run — a parse failure
on one PDF shouldn't block governance ingestion of the rest.
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
from app.domains.source_library.parser_service import get_parser
from app.domains.source_library.ingestion_service import ingest_document_content

SUBMITTER_EMAIL = "dashboard@zoikologia.com"
APPROVER_EMAIL = "source.reviewer@zoikologia.com"

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "sources"

# (filename, folder, title, category, source_class, jurisdiction_scope, auto_approve)
MANIFEST = [
    ("UK_DATA_FRS_102.pdf", "uk",
     "FRS 102 — The Financial Reporting Standard applicable in the UK and Republic of Ireland",
     "standards", "Professional standard-setter", "UK", True),
    ("UK_DATA9_FRS_101_September_2024_lyJ0Tow.pdf", "uk",
     "FRS 101 — Reduced Disclosure Framework (September 2024)",
     "standards", "Professional standard-setter", "UK", True),
    ("UK_DATA10_FRS_100_September_2024.pdf", "uk",
     "FRS 100 — Application of Financial Reporting Requirements (September 2024)",
     "standards", "Professional standard-setter", "UK", True),
    ("UK_DATA12_FRS_103_September_2024_rSi5poe.pdf", "uk",
     "FRS 103 — Insurance Contracts (September 2024)",
     "standards", "Professional standard-setter", "UK", True),
    ("UK_DATA4_FRS_105_September_2024_Redacted_edition_zZFkzvN.pdf", "uk",
     "FRS 105 — The Financial Reporting Standard applicable to the Micro-entities Regime (September 2024, redacted edition)",
     "standards", "Professional standard-setter", "UK", True),
    ("UK_2Amendments_to_FRS_102_and_FRS_105.pdf", "uk",
     "Amendments to FRS 102 and FRS 105 (Financial Reporting Council)",
     "standards", "Professional standard-setter", "UK", True),
    ("UK_DATA2Amendments_to_FRS_102.pdf", "uk",
     "Amendments to FRS 102 (February 2026)",
     "standards", "Professional standard-setter", "UK", True),
    ("UK_DATA3_Amendments_to_FRS_102_and_FRS_105_thresholds.pdf", "uk",
     "Amendments to FRS 102 and FRS 105 — UK Company Size Thresholds (March 2025)",
     "standards", "Professional standard-setter", "UK", True),
    ("UK_DATA5_REDACTED_-_Amendments_to_FRS_102_The_Financial_Reporting_Standard_applicable_in_the_UK_and_Republic_of_Ireland_and_FRS_105.pdf", "uk",
     "Amendments to FRS 102 and FRS 105 (Redacted Edition, February 2026)",
     "standards", "Professional standard-setter", "UK", True),
    ("UK_DATA6_Amendments_to_FRS_102_and_FRS_105_UK_company_size_thresholds.pdf", "uk",
     "Amendments to FRS 102 and FRS 105 — UK Company Size Thresholds, Edition 2 (March 2025)",
     "standards", "Professional standard-setter", "UK", True),
    ("UK_DATA7_Amendments_to_FRS_101_2025-26_cycle_sPu7Ef9b.pdf", "uk",
     "Amendments to FRS 101 — 2025/26 Annual Improvements Cycle (May 2026)",
     "standards", "Professional standard-setter", "UK", True),
    ("UK_DATA8_Amendments_to_FRS_101__2024-25_cycle.pdf", "uk",
     "Amendments to FRS 101 — 2024/25 Annual Improvements Cycle (May 2025)",
     "standards", "Professional standard-setter", "UK", True),
    ("UK_legislation1.pdf", "uk",
     "Mental Capacity Act 2005 (as amended) — UK Legislation",
     "internal-policies", "Government legislation", "UK", False),

    ("US_FASBdata.pdf", "us",
     "ASC 606 — Revenue from Contracts with Customers (FASB)",
     "standards", "Professional standard-setter", "US", True),
    ("US_5Pcob2201.pdf", "us",
     "PCAOB AS 2201 — An Audit of Internal Control Over Financial Reporting",
     "audit", "Auditing standard-setter", "US", True),
    ("US_auditing_standards_audits4.pdf", "us",
     "US Generally Accepted Auditing Standards (GAAS)",
     "audit", "Auditing standard-setter", "US", True),
    ("US_IRS_IRC3.pdf", "us",
     "26 U.S. Code § 6413 — Internal Revenue Code",
     "tax", "Tax authority", "US", True),
    ("US_p15_Employetaxguide2.pdf", "us",
     "IRS Publication 15 — Employer's Tax Guide",
     "payroll-compliance", "Tax authority", "US", True),
    ("US_p946_Depriciation1.pdf", "us",
     "IRS Publication 946 — How to Depreciate Property",
     "tax", "Tax authority", "US", True),
    ("US_SEC_425.pdf", "us",
     "SEC Form 425 Filing",
     "standards", "Securities regulator", "US", True),
    ("US_SEC_8-A12B.pdf", "us",
     "SEC Form 8-A12B Filing",
     "standards", "Securities regulator", "US", True),
    ("US_SEC_S-4A.pdf", "us",
     "SEC Form S-4/A Filing",
     "standards", "Securities regulator", "US", True),
]


async def ingest() -> None:
    async with AsyncSessionLocal() as db:
        submitter = (await db.execute(select(User).where(User.email == SUBMITTER_EMAIL))).scalar_one()
        approver = (await db.execute(select(User).where(User.email == APPROVER_EMAIL))).scalar_one()

        parser = get_parser(prefer_cloud=False)
        created, approved, skipped, missing, embedded, embed_failed = 0, 0, 0, 0, 0, 0
        for filename, folder, title, category, source_class, jurisdiction, auto_approve in MANIFEST:
            file_path = DATA_DIR / folder / filename
            if not file_path.exists():
                print(f"MISSING on disk, skipping: {file_path}")
                missing += 1
                continue

            existing = (await db.execute(select(Source).where(Source.title == title))).scalar_one_or_none()
            if existing is not None:
                print(f"Already ingested, skipping: {title}")
                skipped += 1
                continue

            source = await create_source(
                db,
                submitter.id,
                SourceCreateRequest(
                    category=category,
                    title=title,
                    source_class=source_class,
                    jurisdiction_scope=jurisdiction,
                    note=f"Ingested from data/sources/{folder}/{filename}",
                    file_path=f"data/sources/{folder}/{filename}",
                ),
                tenant_id=submitter.tenant_id,
            )
            created += 1
            print(f"Created ({category}/{jurisdiction}): {title}")

            if auto_approve:
                await approve_source_version(
                    db,
                    approver.id,
                    source["id"],
                    source["latest_version"].id,
                    tenant_id=submitter.tenant_id,
                )
                approved += 1

                try:
                    markdown_content = await parser.parse_file(str(file_path))
                    await ingest_document_content(
                        str(file_path),
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
                    print(f"  Embedded into vector store: {title}")
                except Exception as e:
                    embed_failed += 1
                    print(f"  WARNING: embedding failed for {title}: {e}")

        print(
            f"\nDone. created={created} approved={approved} skipped={skipped} "
            f"missing={missing} embedded={embedded} embed_failed={embed_failed}"
        )


if __name__ == "__main__":
    asyncio.run(ingest())
