"""
Restores the 5 PolicyEngine-US sources deleted in the 2026-07-21 purge,
reusing scripts/reingest_policyengine_fixed.py's delete_existing()/re_ingest()
but skipping its re_extract() step: that step shells out to
scripts/extract_policyengine_params.py against a local policyengine-us repo
clone (REPO = "/Users/kailanaresh/Downloads/policyengine-us-main/...") that
doesn't exist in this environment. Not needed anyway — the already-extracted
.md files under data/sources/us/ were regenerated with the bracket-schedule
fix before the purge (confirmed: they contain real bracket data, not the
"(no values provided)" bug the original script exists to fix), so re_ingest()
can read them as-is.

This also means every one of these 5 documents gets ingested through
ingestion_service.py's now-markdown-header-aware chunker (fixed 2026-07-21),
so the SALT-cap/floor and itemizing-list conflation bugs found earlier
shouldn't recur here.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import scripts.reingest_policyengine_fixed as base


async def main() -> None:
    await base.delete_existing()
    await base.re_ingest()


if __name__ == "__main__":
    asyncio.run(main())
