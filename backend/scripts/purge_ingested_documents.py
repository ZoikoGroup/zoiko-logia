"""
Remove every document-ingested Source from the DB (and its vector-store
chunks), leaving only the live-API-backed governed sources registered.

After this runs, Kriton can only ever answer from: Treasury exchange rates,
GovInfo/eCFR (26 CFR), Federal Register documents, PayrollTax-by-state,
Census (income/poverty), BLS (CPI), BEA (GDP), FRED (interest rates), and
the PolicyEngine household tax-calculation engine (computed results only,
not raw parameter lookups). Everything ingested from a local document
(FRS 102/105, IRS Direct File Fact Dictionary, PolicyEngine-US parameter
markdown, and any future document-based source) becomes unanswerable —
matching queries will resolve to NO_ELIGIBLE_SOURCE -> clarification
instead of an answer, not a wrong answer.

Safety: dry-run by default. Prints exactly what would be deleted and does
nothing else. Pass --confirm to actually execute the deletes. This does not
touch the local files under data/sources/ — only the DB Source/SourceVersion
rows and their vector-store chunks. Re-running scripts/ingest_*.py later
would re-create the same Source rows (their titles are checked for
"already exists" idempotently), so this is reversible via re-ingestion,
just not instantaneously.

Usage:
    python scripts/purge_ingested_documents.py            # dry run
    python scripts/purge_ingested_documents.py --confirm   # actually delete
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select, delete

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal, to_async_url, to_sync_url
from app.domains.source_library.models import Source, SourceVersion

settings = get_settings()

# Every Source row a live-API injection block in orchestration/service.py
# checks membership against (e.g. "TREASURY_GOVERNED_SOURCE_ID in
# allowed_source_ids") — these must never be deleted, or the live-fetch
# blocks silently stop firing even though the adapter itself still works,
# because license_gate.py would no longer find a governed Source to attach
# eligibility to.
_LIVE_API_SOURCE_IDS = {
    "src-treasury-fiscal-data-exchange-rates",
    "src-payroll-tax-api-rate-lookup",
    "src-census-acs-income-poverty",
    "src-bls-cpi-inflation",
    "src-bea-nipa-gdp",
    "src-fred-interest-rates",
    "src-govinfo-cfr-title26",
    "src-federal-register-lookup",
    "src-ecfr-title26",
    "src-policyengine-us-calculation-engine",
}


async def _purge_vector_nodes(source_ids: list[str]) -> None:
    if settings.is_sqlite:
        print(
            "SQLite mode: ingestion uses a local persisted index at "
            "./vector_store, not pgvector. Delete that directory manually "
            "(or leave it — a source with no matching DB row will still "
            "fail license_gate's eligibility check and won't be served)."
        )
        return

    from llama_index.vector_stores.postgres import PGVectorStore
    from llama_index.core.vector_stores.types import MetadataFilter, MetadataFilters
    from app.domains.rag.embeddings import EMBED_DIM

    vector_store = PGVectorStore.from_params(
        connection_string=to_sync_url(settings.DATABASE_URL),
        async_connection_string=to_async_url(settings.DATABASE_URL),
        table_name="kriton_vector_nodes",
        embed_dim=EMBED_DIM,
        hybrid_search=True,
    )
    for source_id in source_ids:
        await vector_store.adelete_nodes(
            filters=MetadataFilters(filters=[MetadataFilter(key="source_id", value=source_id)])
        )


async def main(confirm: bool) -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Source))
        all_sources = result.scalars().all()

    to_delete = [s for s in all_sources if s.id not in _LIVE_API_SOURCE_IDS]
    to_keep = [s for s in all_sources if s.id in _LIVE_API_SOURCE_IDS]

    print(f"Sources found: {len(all_sources)} total")
    print(f"\n--- WILL DELETE ({len(to_delete)}) ---")
    for s in to_delete:
        print(f"  [{s.id}] {s.title}")

    print(f"\n--- WILL KEEP — live-API-backed ({len(to_keep)}) ---")
    for s in to_keep:
        print(f"  [{s.id}] {s.title}")

    missing_live_ids = _LIVE_API_SOURCE_IDS - {s.id for s in to_keep}
    if missing_live_ids:
        print(f"\nNote: these expected live-API source IDs weren't found in the DB "
              f"(nothing to keep for them, not an error): {sorted(missing_live_ids)}")

    if not confirm:
        print("\nDry run only — no changes made. Re-run with --confirm to execute.")
        return

    print("\nDeleting vector-store chunks...")
    await _purge_vector_nodes([s.id for s in to_delete])

    async with AsyncSessionLocal() as db:
        source_ids = [s.id for s in to_delete]
        if source_ids:
            await db.execute(delete(SourceVersion).where(SourceVersion.source_id.in_(source_ids)))
            await db.execute(delete(Source).where(Source.id.in_(source_ids)))
            await db.commit()

    print(f"Deleted {len(to_delete)} source(s), their versions, and their vector-store chunks.")
    print(f"Kept {len(to_keep)} live-API-backed source(s) untouched.")


if __name__ == "__main__":
    asyncio.run(main(confirm="--confirm" in sys.argv))
