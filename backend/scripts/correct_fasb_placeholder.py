"""Correct the metadata of the empty "FASB ASC" placeholder source.

    cd backend
    .venv/bin/python scripts/correct_fasb_placeholder.py                 # dry run: read and show, write nothing
    .venv/bin/python scripts/correct_fasb_placeholder.py --apply --confirm dcea5197-906c-4b62-b71b-8968d44571a7

The source was registered on 19 August 2026 with no URL, file, content hash
or publisher, has never had a passage, and is UNREVIEWED — yet it is marked
licence "permitted", version ACTIVE, "Citation + export allowed". FASB
Accounting Standards Codification content requires a licence from the
Financial Accounting Foundation to store or reproduce; none is recorded.

It is already excluded from answers (no rights row → RIGHT_UNKNOWN), so this
corrects what the record claims rather than what Kriton retrieves:
  * sources.licence_state      permitted → unknown
  * source_versions.status     ACTIVE    → PROPOSED   (reversible; refused by can_use)
  * source_versions.note       "Citation + export allowed" → why it is unverified
and records a `source_metadata_corrected` audit event in the same transaction.
It refuses to run if the record no longer looks like the placeholder.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select  # noqa: E402

SOURCE_ID = "dcea5197-906c-4b62-b71b-8968d44571a7"
NOTE = ("Placeholder: no content ingested. Licence unverified — FASB ASC content requires a Financial "
        "Accounting Foundation licence to store or reproduce. Do not approve until one is recorded.")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--apply", action="store_true", help="write the correction (default: dry run)")
    parser.add_argument("--confirm", default="", help=f"must equal the source id ({SOURCE_ID})")
    args = parser.parse_args()

    from app.core.database import AsyncSessionLocal
    from app.domains.audit_ledger.event_envelope import record_event_async
    from app.domains.source_library.licensing import SourceUseContext, can_use
    from app.domains.source_library.models import Source, SourcePassage, SourceVersion

    async with AsyncSessionLocal() as db:
        source = (await db.execute(select(Source).where(Source.id == SOURCE_ID))).scalar_one_or_none()
        versions = (await db.execute(select(SourceVersion).where(SourceVersion.source_id == SOURCE_ID))).scalars().all()
        if source is None or len(versions) != 1:
            sys.exit("Source not found, or it no longer has exactly one version — not the placeholder; nothing done.")
        version = versions[0]
        passages = (await db.execute(select(func.count()).select_from(SourcePassage)
                                     .where(SourcePassage.source_version_id == version.id))).scalar_one()
        if source.title != "FASB ASC" or passages or version.content_hash or version.source_url:
            sys.exit(f"Record changed since this correction was written (title={source.title!r}, passages={passages}, "
                     "content or URL present) — review it again; nothing done.")

        print("BEFORE  sources.licence_state      :", source.licence_state)
        print("        source_versions.status     :", version.status)
        print("        source_versions.note       :", version.note)
        print("        passages                   :", passages)
        print("AFTER   sources.licence_state      : unknown")
        print("        source_versions.status     : PROPOSED")
        print("        source_versions.note       :", NOTE)
        if not args.apply:
            print("\nDry run — nothing written. Re-run with --apply --confirm", SOURCE_ID)
            return
        if args.confirm != SOURCE_ID:
            sys.exit("--confirm must equal the source id; nothing done.")

        before = {"licence_state": source.licence_state, "status": version.status, "note": version.note}
        source.licence_state = "unknown"
        version.status = "PROPOSED"
        version.note = NOTE
        await record_event_async(
            db, event_name="source_metadata_corrected", emitting_service="source_library",
            subject_type="source", subject_id=SOURCE_ID, actor_id=None, correlation_id=SOURCE_ID,
            tenant_id=source.tenant_id, classification="INTERNAL", replay_relevance="REQUIRED",
            payload={"version_id": version.id, "before": before,
                     "after": {"licence_state": "unknown", "status": "PROPOSED"},
                     "reason": "Empty placeholder marked permitted/ACTIVE without content or a recorded licence"},
        )
        await db.commit()
        decision = await can_use(db, version.id, SourceUseContext(tenant_id=source.tenant_id), "model_transmission")
        print(f"\nApplied. can_use(model_transmission) → allowed={decision.allowed} ({decision.reason_code})")


if __name__ == "__main__":
    asyncio.run(main())
