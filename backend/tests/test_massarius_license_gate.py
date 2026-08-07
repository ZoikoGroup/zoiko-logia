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


async def test_bundle_authority_level_reflects_real_source_data_not_category_guess():
    """Regression test (enterprise-grade consistency audit): retrieve.py's
    preliminary bundle guesses authority_level from query category
    ("primary" if category in ("audit", "tax") else "secondary"), ignoring
    each source's real authority_level column. Before this fix,
    build_bundle() copied that guess straight through, so a query tagged
    category="tax" got authority_level="primary" on the final bundle even
    when every actual eligible source was DB-tagged "internal" — silently
    disabling answer_validator.py's Authority ceiling check for
    absolute-certainty language. The final bundle must instead reflect the
    weakest real authority_level among the sources that actually survived
    Checkpoint A."""
    tenant_id = f"tenant-{uuid.uuid4().hex[:8]}"
    async with AsyncSessionLocal() as db:
        internal_source = Source(
            tenant_id=tenant_id, category="tax", title=f"Internal Source {uuid.uuid4().hex[:8]}",
            source_class="internal", licence_state="permitted", authority_level="internal",
        )
        db.add(internal_source)
        await db.flush()
        await db.commit()

        # Simulates retrieve.py's preliminary bundle: category="tax" forces
        # its category-based heuristic to authority_level="primary",
        # regardless of the real source data.
        preliminary = SourceBundle(
            source_bundle_id="sb-test-authority",
            confidence_state="sufficient",
            authority_level="primary",
            sources=[_summary_for(internal_source)],
        )

        licence_result = await check_eligibility(db, preliminary.sources, tenant_id=tenant_id)
        final_bundle = build_bundle(preliminary, licence_result)

        assert final_bundle.authority_level == "internal", (
            f"expected the bundle to reflect the real source's authority_level "
            f"('internal'), got '{final_bundle.authority_level}' (the category guess)"
        )

        await db.execute(Source.__table__.delete().where(Source.id == internal_source.id))
        await db.commit()
    print("test_bundle_authority_level_reflects_real_source_data_not_category_guess: PASSED")


async def test_source_summary_carries_source_type_for_checkpoint_a_routing():
    """Regression test: check_eligibility() routes on SourceSummary.source_type
    to decide whether a source is licence-checked against source_library.Source
    or the LiveSourceProvider registry. The field was being passed by
    live_sources.service.to_source_summary() but was not declared on the model,
    so Pydantic silently dropped the keyword argument and the attribute never
    existed — Checkpoint A then raised
    'SourceSummary object has no attribute source_type' and returned a 500 on
    the first query that retrieved anything at all.

    Pure schema test on purpose: it guards the declaration itself, which is
    what actually broke, and so keeps failing even if the routing logic in
    license_gate.py is later rewritten."""
    default_summary = SourceSummary(
        id="src-1", title="Doc", category="tax",
        jurisdiction_scope="Global", version_label="v1", status="ACTIVE",
    )
    assert default_summary.source_type == "document", (
        "producers that omit source_type must keep their previous document behaviour"
    )

    live_summary = SourceSummary(
        id="live-fred-gdp", title="FRED GDP", category="economic_data",
        jurisdiction_scope="US", version_label="v1", status="ACTIVE",
        source_type="live_api",
    )
    assert live_summary.source_type == "live_api", (
        "source_type must be declared on the model or Pydantic drops the kwarg"
    )

    # The routing predicate Checkpoint A actually uses, exercised directly.
    sources = [default_summary, live_summary]
    assert [s.id for s in sources if s.source_type != "live_api"] == ["src-1"]
    assert [s.id for s in sources if s.source_type == "live_api"] == ["live-fred-gdp"]
    print("test_source_summary_carries_source_type_for_checkpoint_a_routing: PASSED")


async def test_check_eligibility_accepts_a_mixed_document_and_live_source_list():
    """The end-to-end shape of the crash: a bundle mixing a document source
    and a live-API source must pass through Checkpoint A without raising.
    The live source has no LiveSourceProvider registry row here, so it is
    expected to be excluded rather than admitted — the point is that the call
    completes instead of blowing up on attribute access."""
    tenant_id = f"tenant-{uuid.uuid4().hex[:8]}"
    async with AsyncSessionLocal() as db:
        doc_source = await _make_source(db, tenant_id=tenant_id, licence_state="permitted")
        await db.commit()

        live_summary = SourceSummary(
            id="live-unregistered-provider-1", title="Unregistered live feed",
            category="economic_data", jurisdiction_scope="US", version_label="v1",
            status="ACTIVE", source_type="live_api",
        )
        result = await check_eligibility(
            db, [_summary_for(doc_source), live_summary], tenant_id=tenant_id
        )

        assert doc_source.id in {s.id for s in result.eligible}
        assert live_summary.id not in {s.id for s in result.eligible}, (
            "a live source with no registry row must not be silently admitted"
        )

        await db.execute(Source.__table__.delete().where(Source.id == doc_source.id))
        await db.commit()
    print("test_check_eligibility_accepts_a_mixed_document_and_live_source_list: PASSED")


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
    await test_bundle_authority_level_reflects_real_source_data_not_category_guess()
    await test_source_summary_carries_source_type_for_checkpoint_a_routing()
    await test_check_eligibility_accepts_a_mixed_document_and_live_source_list()
    await test_raise_if_denied_hard_stops_when_everything_excluded()
    print("All tests passed successfully!")


if __name__ == "__main__":
    asyncio.run(main())
