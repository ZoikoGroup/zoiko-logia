"""
Batch-register the remaining IRS Direct File Fact Dictionary topics
(already extracted to data/sources/us/direct_file_raw/*.md by
scripts/extract_direct_file_facts.py) as governed Sources — same pattern as
scripts/ingest_reference_sources.py's MANIFEST, and the same
create_source / approve_source_version / ingest_document_content flow as
scripts/ingest_direct_file_eitc.py, generalized to a list instead of one
script per source.

Deliberately excludes the thin/technical files (copy, flow, mefTypes,
validations, schedule2, dependentsRelationship, imported, refundPrefs,
paymentMethod, spouseSection, signing, form1099Misc, dependentsBenefitSplit,
educatorAdjustment, estimatedPayments, filingStatus, constants,
schedule3, taxCalculations — mostly UI/plumbing or thin coverage; see
conversation) — only registers topics that are genuinely likely to answer a
real user question. EITC was already registered separately.

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

RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "sources" / "us" / "direct_file_raw"

# (raw md filename, title, category)
MANIFEST = [
    ("US_DirectFile_ctcOdc.md",
     "IRS Direct File Fact Dictionary — Child Tax Credit / Credit for Other Dependents (CTC/ODC)", "tax"),
    ("US_DirectFile_cdcc.md",
     "IRS Direct File Fact Dictionary — Child and Dependent Care Credit (CDCC)", "tax"),
    ("US_DirectFile_saversCredits.md",
     "IRS Direct File Fact Dictionary — Saver's Credit", "tax"),
    ("US_DirectFile_elderlyAndDisabled.md",
     "IRS Direct File Fact Dictionary — Credit for the Elderly or the Disabled", "tax"),
    ("US_DirectFile_ptc.md",
     "IRS Direct File Fact Dictionary — Premium Tax Credit (PTC / Form 8962)", "tax"),
    ("US_DirectFile_socialSecurity.md",
     "IRS Direct File Fact Dictionary — Social Security Income Taxation", "tax"),
    ("US_DirectFile_unemployment.md",
     "IRS Direct File Fact Dictionary — Unemployment Compensation", "tax"),
    ("US_DirectFile_hsa.md",
     "IRS Direct File Fact Dictionary — Health Savings Accounts (HSA / Form 8889)", "tax"),
    ("US_DirectFile_studentLoanAdjustment.md",
     "IRS Direct File Fact Dictionary — Student Loan Interest Deduction", "tax"),
    ("US_DirectFile_standardDeduction.md",
     "IRS Direct File Fact Dictionary — Standard Deduction", "tax"),
    ("US_DirectFile_income.md",
     "IRS Direct File Fact Dictionary — Income Sources and Classification", "tax"),
    ("US_DirectFile_interest.md",
     "IRS Direct File Fact Dictionary — Interest Income", "tax"),
    ("US_DirectFile_form1099Rs.md",
     "IRS Direct File Fact Dictionary — Form 1099-R (Retirement Distributions)", "tax"),
    ("US_DirectFile_formW2s.md",
     "IRS Direct File Fact Dictionary — Form W-2 Wage Reporting", "payroll-compliance"),
    ("US_DirectFile_filers.md",
     "IRS Direct File Fact Dictionary — Filer Identity and Status", "tax"),
    ("US_DirectFile_familyAndHousehold.md",
     "IRS Direct File Fact Dictionary — Family, Household, and Dependent Status", "tax"),
    ("US_DirectFile_constants.md",
     "IRS Direct File Fact Dictionary — Tax Year Constants and Key Dates", "tax"),
    ("US_DirectFile_filingStatus.md",
     "IRS Direct File Fact Dictionary — Filing Status Determination", "tax"),
    ("US_DirectFile_taxCalculations.md",
     "IRS Direct File Fact Dictionary — Tax Calculation and Exemptions", "tax"),
]

JURISDICTION = "US"
SOURCE_CLASS = "Tax authority (extracted from IRS open-source Direct File)"


async def ingest() -> None:
    async with AsyncSessionLocal() as db:
        submitter = (await db.execute(select(User).where(User.email == SUBMITTER_EMAIL))).scalar_one()
        approver = (await db.execute(select(User).where(User.email == APPROVER_EMAIL))).scalar_one()

        created = skipped = embedded = embed_failed = 0
        for filename, title, category in MANIFEST:
            existing = (await db.execute(select(Source).where(Source.title == title))).scalar_one_or_none()
            if existing is not None:
                print(f"Already ingested, skipping: {title}")
                skipped += 1
                continue

            raw_path = RAW_DIR / filename
            if not raw_path.exists():
                print(f"MISSING extracted file, skipping: {raw_path}")
                continue

            markdown_content = raw_path.read_text()
            rel_path = f"data/sources/us/direct_file_raw/{filename}"

            source = await create_source(
                db,
                submitter.id,
                SourceCreateRequest(
                    category=category,
                    title=title,
                    source_class=SOURCE_CLASS,
                    jurisdiction_scope=JURISDICTION,
                    note=(
                        "Extracted from IRS Direct File's open-source Fact Dictionary "
                        "(github.com/IRS-Public/direct-file) via scripts/extract_direct_file_facts.py."
                    ),
                    file_path=rel_path,
                ),
                tenant_id=submitter.tenant_id,
            )
            created += 1
            print(f"Created ({category}/{JURISDICTION}): {title}")

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
                        "jurisdiction_scope": JURISDICTION,
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
