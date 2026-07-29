"""
One-off correction: the first pass of scripts/extract_policyengine_params.py
didn't handle PolicyEngine's `brackets:` schema (used by every graduated/
marginal-rate parameter — income tax brackets, etc.), so every bracket-based
fact in the 5 PolicyEngine sources already registered was extracted as
"(no values provided)". A live Kriton test showed the model then answered a
New York bracket question with specific numbers anyway, including a wrong
digit ($1,075,550 vs the real $1,077,550) — i.e. it wasn't grounded in the
actual (empty) retrieved content.

extract_policyengine_params.py now handles `brackets:` correctly (verified
against the real NY schedule). This script:
  1. Deletes the 5 existing Source/SourceVersion rows (by title) and their
     vector store rows (data_kriton_vector_nodes, matched by source_id).
  2. Re-extracts all 5 folders with the fixed extractor.
  3. Re-runs the normal create_source / approve_source_version /
     ingest_document_content flow, exactly as before.
"""
import asyncio
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, select, text

from app.core.database import AsyncSessionLocal
from app.domains.identity.models import User
from app.domains.source_library.models import Source, SourceVersion
from app.domains.source_library.schemas import SourceCreateRequest
from app.domains.source_library.service import approve_source_version, create_source
from app.domains.source_library.ingestion_service import ingest_document_content

SUBMITTER_EMAIL = "dashboard@zoikologia.com"
APPROVER_EMAIL = "source.reviewer@zoikologia.com"
BACKEND_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BACKEND_DIR / "data" / "sources" / "us"
SOURCE_CLASS = "Open-source tax-benefit microsimulation model (PolicyEngine-US)"
REPO = "/Users/kailanaresh/Downloads/policyengine-us-main/policyengine_us/parameters"

# (source folder, extracted filename, title, category, jurisdiction_scope)
MANIFEST = [
    (f"{REPO}/gov/irs/deductions", "US_PolicyEngine_Deductions.md",
     "PolicyEngine-US Parameters — IRS Deductions (Standard, Itemized, QBI, Auto Loan Interest)",
     "tax", "US"),
    (f"{REPO}/gov/irs/credits", "US_PolicyEngine_Credits.md",
     "PolicyEngine-US Parameters — Federal Tax Credits (CTC, CDCC, PTC, EITC, Elderly/Disabled, Education, Energy, Clean Vehicle)",
     "tax", "US"),
    (f"{REPO}/gov/ssa", "US_PolicyEngine_SocialSecurity.md",
     "PolicyEngine-US Parameters — Social Security (PIA, AIME, Retirement Age, SSI, Earnings Test)",
     "tax", "US"),
    (f"{REPO}/gov/states/ca/tax/income", "US_PolicyEngine_CA_IncomeTax.md",
     "PolicyEngine-US Parameters — California State Income Tax (Rates, AGI, AMT, Deductions, Credits)",
     "tax", "CA"),
    (f"{REPO}/gov/states/ny/tax/income", "US_PolicyEngine_NY_IncomeTax.md",
     "PolicyEngine-US Parameters — New York State Income Tax (Rates, AGI, Deductions, Credits, Payroll)",
     "tax", "NY"),
]


async def delete_existing() -> None:
    async with AsyncSessionLocal() as db:
        for _, _, title, _, _ in MANIFEST:
            existing = (await db.execute(select(Source).where(Source.title == title))).scalar_one_or_none()
            if existing is None:
                continue
            await db.execute(
                text("DELETE FROM data_kriton_vector_nodes WHERE metadata_->>'source_id' = :sid"),
                {"sid": existing.id},
            )
            await db.execute(delete(SourceVersion).where(SourceVersion.source_id == existing.id))
            await db.execute(delete(Source).where(Source.id == existing.id))
            await db.commit()
            print(f"Deleted stale source + vectors: {title}")


def re_extract() -> None:
    for folder, filename, *_ in MANIFEST:
        out_path = DATA_DIR / filename
        with open(out_path, "w") as out:
            subprocess.run(
                [sys.executable, str(BACKEND_DIR / "scripts" / "extract_policyengine_params.py"), folder],
                stdout=out, stderr=subprocess.PIPE, check=True,
            )
        print(f"Re-extracted: {filename}")


async def re_ingest() -> None:
    async with AsyncSessionLocal() as db:
        submitter = (await db.execute(select(User).where(User.email == SUBMITTER_EMAIL))).scalar_one()
        approver = (await db.execute(select(User).where(User.email == APPROVER_EMAIL))).scalar_one()

        for _, filename, title, category, jurisdiction in MANIFEST:
            full_path = DATA_DIR / filename
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
                        "Extracted from PolicyEngine-US's open-source parameter tree via "
                        "scripts/extract_policyengine_params.py (bracket-schedule extraction fix applied)."
                    ),
                    file_path=rel_path,
                ),
                tenant_id=submitter.tenant_id,
            )
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
                print("  Embedded into vector store.")
            except Exception as e:
                print(f"  WARNING: embedding failed: {e}")


async def main() -> None:
    await delete_existing()
    re_extract()
    await re_ingest()


if __name__ == "__main__":
    asyncio.run(main())
