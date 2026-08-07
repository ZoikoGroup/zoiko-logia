"""Regression tests: the live_sources domain is actually reachable from the
Ask pipeline.

Reported bug — "what is India's latest GDP?" returned "Kriton could not find
sufficient sources", despite a working World Bank connector that answers it
in under a second. Traced to the domain never being called:
detect_live_data_intent / fetch_live_data appeared nowhere in
orchestration/service.py. Only the curated US-agency bundles (BEA, BLS, FRED,
Census, Treasury, CFR, Congress) and DBnomics were wired in, and DBnomics'
free-text dataset search returns nothing usable for "india gdp" (its top
three hits were CEPII trade indicators, OECD education expenditure and IMF
government finance statistics — no GDP dataset at all), so every candidate
was correctly rejected and the answer degraded to a clarification.

These tests pin the wiring itself, not the connectors, which have their own
suites.
"""
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
import pytest_asyncio

from app.core.database import AsyncSessionLocal, async_engine
from app.domains.live_sources.classifier import detect_live_data_intent
from app.domains.live_sources.service import (
    LIVE_SOURCE_NODE_PREFIX,
    fetch_live_data,
    make_live_source_id,
    to_source_summary,
    to_synthetic_chunk,
)
from app.orchestration.service import (
    _LIVE_DATA_NODE_PREFIXES,
    _is_mandatory_context_chunk,
)


@pytest_asyncio.fixture(autouse=True)
async def _fresh_connection_pool():
    """pytest-asyncio runs each async test on its own event loop, but
    async_engine's connection pool is module-level and every asyncpg
    connection in it is bound to the loop that opened it. The second async
    test in this module would otherwise check out a connection created on the
    first test's (now closed) loop and die with "got Future attached to a
    different loop" — an artefact of the shared pool, not of the code under
    test. Disposing either side of each test guarantees a pool belonging to
    the current loop.
    """
    await async_engine.dispose()
    yield
    await async_engine.dispose()


class _FakeNormalized:
    """Minimal stand-in for NormalizedResponse — only the fields the id and
    chunk builders read."""
    provider_key = "world_bank"
    indicator_code = "NY.GDP.MKTP.CD"
    indicator_label = "GDP (current US$)"
    country_code = "IN"
    country_label = "India"
    observation_period = "2025"
    value = 3_956_067_115_771.63
    unit = ""
    citation_title = "World Bank — India, GDP (current US$), 2025"
    source_url = "https://api.worldbank.org/v2/country/IN/indicator/NY.GDP.MKTP.CD"
    as_of = "2025-01-01T00:00:00Z"
    company_query = None


def test_the_orchestrator_can_recognise_a_live_source_chunk_by_node_id():
    """The prefix constant must actually match what make_live_source_id()
    produces — orchestration recognises live chunks by node_id alone, so a
    drift here silently un-protects every live figure."""
    assert make_live_source_id(_FakeNormalized()).startswith(LIVE_SOURCE_NODE_PREFIX)


def test_live_chunks_survive_reranking_and_count_as_mandatory_context():
    """A live figure is a deterministic country+indicator match, not a
    prose-similarity guess. If the prefix is not registered, the cross-encoder
    reranker can drop the only chunk carrying the actual number in favour of a
    document that merely discusses the topic — which is precisely how the
    answer ends up ungrounded."""
    assert LIVE_SOURCE_NODE_PREFIX in _LIVE_DATA_NODE_PREFIXES

    normalized = _FakeNormalized()
    chunk = to_synthetic_chunk(normalized, to_source_summary(normalized))
    assert _is_mandatory_context_chunk(chunk), "a live figure must not be droppable from context"


def test_the_chunk_carries_the_figure_and_its_provenance():
    """Grounding needs the number in chunk['text']; citation needs the title
    and URL in metadata. A chunk missing either produces the empty-composition
    clarification this bug was reported as."""
    normalized = _FakeNormalized()
    chunk = to_synthetic_chunk(normalized, to_source_summary(normalized))
    assert "India" in chunk["text"]
    assert "3.96 trillion" in chunk["text"]
    assert chunk["metadata"]["source_type"] == "live_api"
    assert chunk["metadata"]["file_path"] == normalized.source_url
    assert chunk["metadata"]["title"] == normalized.citation_title


def test_us_queries_stay_with_the_curated_bundles():
    """The orchestrator gates this path on country_code != "US" so BEA/BLS/
    FRED remain authoritative for US questions and no indicator ends up with
    two competing live figures."""
    us_intent = detect_live_data_intent("what is the US GDP?", jurisdiction="")
    assert us_intent is not None and us_intent.country_code == "US"

    india_intent = detect_live_data_intent("india's latest GDP?", jurisdiction="")
    assert india_intent is not None and india_intent.country_code == "IN"


def test_a_non_live_question_triggers_no_fetch():
    """The gate is the classifier returning None — an ordinary conceptual
    question must not reach a connector at all."""
    assert detect_live_data_intent("what is materiality in auditing?", jurisdiction="") is None


@pytest.mark.network
async def test_a_live_source_reaches_the_final_bundle_live():
    """The second half of the same bug. Even once the chunk was injected, the
    figure still never reached the answer: build_source_bundle() re-checked
    every chunk's source_id against source_library, and a live-API source has
    no Source row by design, so it was excluded as "source_record_not_found"
    and the citation layer had nothing to attribute the number to.

    Eligibility must still be decided by the licence gate against the
    LiveSourceProvider registry — this asserts the source survives that gate,
    not that it bypasses it.

    Needs the seeded registry, so it runs against real Postgres
    (RUN_POSTGRES_TESTS=1); under the hermetic SQLite default the provider
    table is empty and exclusion is the *correct* outcome, not a regression.
    """
    from sqlalchemy import select

    from app.domains.live_sources.models import LiveSourceProvider
    from app.domains.massarius import bundle_builder, license_gate
    from app.orchestration.retrieve import build_source_bundle

    query = "what is india's current GDP?"
    async with AsyncSessionLocal() as db:
        registered = (await db.execute(
            select(LiveSourceProvider).where(LiveSourceProvider.provider_key == "world_bank")
        )).scalars().first()
        if registered is None:
            pytest.skip("LiveSourceProvider registry not seeded — run with RUN_POSTGRES_TESTS=1")

        outcome = await fetch_live_data(db, query=query, tenant_id="GLOBAL_CONTROL", jurisdiction="")
        assert outcome.succeeded, f"live fetch failed: {outcome.error}"
        chunk = to_synthetic_chunk(outcome.normalized, to_source_summary(outcome.normalized))

        preliminary = await build_source_bundle(
            db, query=query, jurisdiction="", tenant_id="GLOBAL_CONTROL", raw_chunks=[chunk],
        )
        live_ids = [s.id for s in preliminary.sources if s.id.startswith(LIVE_SOURCE_NODE_PREFIX)]
        assert live_ids, "the live source must not be dropped as source_record_not_found"
        assert preliminary.jurisdiction == "India"
        assert preliminary.confidence_state != "insufficient", (
            "a bundle holding the actual figure must not report insufficient evidence"
        )

        # Checkpoint A must still run for it, via the provider registry.
        result = await license_gate.check_eligibility(db, preliminary.sources, tenant_id="GLOBAL_CONTROL")
        final = bundle_builder.build_bundle(preliminary, result)
        assert any(s.id.startswith(LIVE_SOURCE_NODE_PREFIX) for s in final.sources), (
            "world_bank is an ACTIVE, permitted provider — it must survive Checkpoint A"
        )
    print("test_a_live_source_reaches_the_final_bundle_live: PASSED")


@pytest.mark.network
async def test_india_gdp_produces_a_grounded_chunk_live():
    """End-to-end against the real World Bank API: the exact reported query
    now yields a chunk carrying a real figure."""
    query = "india's latest GDP?"
    async with AsyncSessionLocal() as db:
        outcome = await fetch_live_data(db, query=query, tenant_id="GLOBAL_CONTROL", jurisdiction="")
        assert outcome.succeeded, f"live fetch failed: {outcome.error}"
        assert outcome.intent.provider_key == "world_bank"
        assert outcome.intent.country_code == "IN"

        chunk = to_synthetic_chunk(outcome.normalized, to_source_summary(outcome.normalized))
        assert chunk["node_id"].startswith(LIVE_SOURCE_NODE_PREFIX)
        assert "India" in chunk["text"]
        # A real GDP figure, not a placeholder or an empty string.
        assert any(ch.isdigit() for ch in chunk["text"])
    print("test_india_gdp_produces_a_grounded_chunk_live: PASSED")


if __name__ == "__main__":
    test_the_orchestrator_can_recognise_a_live_source_chunk_by_node_id()
    test_live_chunks_survive_reranking_and_count_as_mandatory_context()
    test_the_chunk_carries_the_figure_and_its_provenance()
    test_us_queries_stay_with_the_curated_bundles()
    test_a_non_live_question_triggers_no_fetch()
    print("All tests passed successfully!")
