"""
US-only wrapper around scripts/ingest_reference_sources.py's MANIFEST/ingest()
— filters to jurisdiction == "us" so the UK FRS content stays out (it doesn't
serve US questions and was deliberately left out of the 2026-07-21 restore).
Reuses ingest_reference_sources.ingest() unchanged rather than duplicating
its create_source/approve_source_version/ingest_document_content logic.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import scripts.ingest_reference_sources as base

base.MANIFEST = [row for row in base.MANIFEST if row[1] == "us"]

if __name__ == "__main__":
    asyncio.run(base.ingest())
