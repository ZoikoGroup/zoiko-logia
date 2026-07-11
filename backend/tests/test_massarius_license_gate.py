"""
ZL-ENG-03 Acceptance Criterion 4 — Licence Checkpoints A and B are
implemented and independently testable, including a test that an ineligible
source cannot reach the final bundle even if retrieval returns it.

Requires a live DB (creates real Source rows) — run inside the backend
container:
    docker compose exec backend python3 tests/test_massarius_license_gate.py
"""
import asyncio
import os
import sys
import uuid

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.database import AsyncSessionLocal
from app.domains.massarius.bundle_builder import build_bundle
from app.domains.massarius.errors import LicenceDenied
from app.domains.massarius.license_gate import check_eligibility, raise_if_denied
from app.domains.source_library.models import Source
from app.orchestration.schemas import SourceBundle, SourceSummary


async def _make_source(db, *, tenant_id: str, licence_state: str, is_tenant_private: bool = False) -> Source:
    source = Source(
        tenant_id=tenant_id,
        category="tax",
        title=f"Test Source {uuid.uuid4().hex[:8]}",
        source_class="internal",
        licence_state=licence_state,
        is_tenant_private=is_tenant_private,
    )
    db.add(source)
    await db.flush()
    return source


def _summary_for(source: Source) -> SourceSummary:
    return SourceSummary(
        id=source.id, title=source.title, category=source.category,
        jurisdiction_scope="Global", version_label="v1", status="ACTIVE",
    )


async def test_restricted_licence_source_excluded_from_final_bundle():
    """Checkpoint A: a source with licence_state='restricted' must never
    reach the final bundle, even though retrieve.py's preliminary bundle
    included it (simulating retrieval having "returned" it)."""
    tenant_id = f"tenant-{uuid.uuid4().hex[:8]}"
    async with AsyncSessionLocal() as db:
        eligible_source = await _make_source(db, tenant_id=tenant_id, licence_state="permitted")
        restricted_source = await _make_source(db, tenant_id=tenant_id, licence_state="restricted")
        await db.commit()

        preliminary = SourceBundle(
            source_bundle_id="sb-test",
            confidence_state="sufficient",
            sources=[_summary_for(eligible_source), _summary_for(restricted_source)],
        )

        licence_result = await check_eligibility(db, preliminary.sources, tenant_id=tenant_id)
        final_bundle = build_bundle(preliminary, licence_result)

        final_ids = {s.id for s in final_bundle.sources}
        assert eligible_source.id in final_ids, "the permitted source should survive Checkpoint A"
        assert restricted_source.id not in final_ids, "the restricted source must NOT reach the final bundle"
        assert final_bundle.excluded_source_count == 1

        await db.execute(Source.__table__.delete().where(Source.id.in_([eligible_source.id, restricted_source.id])))
        await db.commit()
    print("test_restricted_licence_source_excluded_from_final_bundle: PASSED")


async def test_tenant_private_source_excluded_for_other_tenant():
    """Checkpoint A: a tenant-private source belonging to tenant A must be
    excluded when the requesting tenant is B, even if retrieval somehow
    returned it (private-source boundary)."""
    tenant_a = f"tenant-a-{uuid.uuid4().hex[:8]}"
    tenant_b = f"tenant-b-{uuid.uuid4().hex[:8]}"
    async with AsyncSessionLocal() as db:
        private_source = await _make_source(db, tenant_id=tenant_a, licence_state="permitted", is_tenant_private=True)
        await db.commit()

        preliminary = SourceBundle(source_bundle_id="sb-test-2", sources=[_summary_for(private_source)])
        licence_result = await check_eligibility(db, preliminary.sources, tenant_id=tenant_b)
        final_bundle = build_bundle(preliminary, licence_result)

        assert final_bundle.eligible_source_count == 0
        assert private_source.id not in {s.id for s in final_bundle.sources}

        await db.execute(Source.__table__.delete().where(Source.id == private_source.id))
        await db.commit()
    print("test_tenant_private_source_excluded_for_other_tenant: PASSED")


async def test_raise_if_denied_hard_stops_when_everything_excluded():
    tenant_id = f"tenant-{uuid.uuid4().hex[:8]}"
    async with AsyncSessionLocal() as db:
        restricted_source = await _make_source(db, tenant_id=tenant_id, licence_state="restricted")
        await db.commit()

        sources = [_summary_for(restricted_source)]
        licence_result = await check_eligibility(db, sources, tenant_id=tenant_id)
        try:
            raise_if_denied(licence_result)
            raise AssertionError("raise_if_denied should have raised LicenceDenied")
        except LicenceDenied as e:
            assert e.source_ids == [restricted_source.id]

        await db.execute(Source.__table__.delete().where(Source.id == restricted_source.id))
        await db.commit()
    print("test_raise_if_denied_hard_stops_when_everything_excluded: PASSED")


async def main():
    await test_restricted_licence_source_excluded_from_final_bundle()
    await test_tenant_private_source_excluded_for_other_tenant()
    await test_raise_if_denied_hard_stops_when_everything_excluded()
    print("All tests passed successfully!")


if __name__ == "__main__":
    asyncio.run(main())
