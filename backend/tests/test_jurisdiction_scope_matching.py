"""
Regression tests for a reported bug: selecting jurisdiction="US-CA" in the
UI excluded EVERY governed source, including both the federal US tax
content and the California-specific PolicyEngine source it was meant to
surface. Root cause: retrieve.py/rag.retrieval both compared a document's
jurisdiction_scope against the requested jurisdiction with an exact string
match — no source is ever tagged with the literal scope "US-CA" (state
content is tagged "CA", federal content "US"), so nothing could ever match.

Fixed via app.domains.jurisdiction_locale.service.acceptable_jurisdiction_scopes(),
which expands a state-qualified jurisdiction into every scope value that
should be considered in-scope for it, used by both call sites.

Run inside the backend container (needs a live DB for the integration test):
    docker compose exec backend python3 tests/test_jurisdiction_scope_matching.py
"""
import asyncio
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.database import AsyncSessionLocal
from app.domains.jurisdiction_locale.service import acceptable_jurisdiction_scopes
from app.orchestration.retrieve import _jurisdiction_ok, build_source_bundle


def test_acceptable_jurisdiction_scopes_expands_state_qualified_jurisdictions():
    assert acceptable_jurisdiction_scopes("US-CA") == ["US-CA", "US", "CA"]
    assert acceptable_jurisdiction_scopes("US-NY") == ["US-NY", "US", "NY"]
    # Every other jurisdiction value is unaffected — matches only itself.
    assert acceptable_jurisdiction_scopes("UK") == ["UK"]
    assert acceptable_jurisdiction_scopes("US") == ["US"]
    assert acceptable_jurisdiction_scopes("India") == ["India"]
    print("test_acceptable_jurisdiction_scopes_expands_state_qualified_jurisdictions: PASSED")


def test_jurisdiction_ok_accepts_federal_and_state_scope_for_state_jurisdiction():
    """The two real cases that were silently broken: a federal ("US")
    source and the state's own ("CA") source must both be in-scope for a
    "US-CA" request — neither is the literal string "US-CA"."""
    assert _jurisdiction_ok("US", "US-CA") is True
    assert _jurisdiction_ok("CA", "US-CA") is True
    assert _jurisdiction_ok("Global", "US-CA") is True
    # A different state must still be excluded — this isn't "match anything".
    assert _jurisdiction_ok("NY", "US-CA") is False
    # Unaffected jurisdictions keep their original exact-match behavior.
    assert _jurisdiction_ok("UK", "US") is False
    assert _jurisdiction_ok("US", "US") is True
    assert _jurisdiction_ok("anything", "") is True
    print("test_jurisdiction_ok_accepts_federal_and_state_scope_for_state_jurisdiction: PASSED")


async def test_california_tax_query_finds_federal_and_state_sources_live():
    """Live integration test against the real Supabase-seeded source
    registry — confirmed this session: before the fix, this returned 0
    eligible / 27 excluded. After the fix, both the federal ("US") tax
    sources and the CA-specific PolicyEngine source are eligible; only
    the NY-specific source (a different state) is correctly excluded."""
    async with AsyncSessionLocal() as db:
        bundle = await build_source_bundle(
            db,
            query="What are California state income tax brackets and AMT rules?",
            jurisdiction="US-CA",
            tenant_id="GLOBAL_CONTROL",
            raw_chunks=[],  # isolate the keyword_mvp path from vector search
        )
        assert bundle.eligible_source_count > 0
        titles = {s.title for s in bundle.sources}
        assert any("California" in t for t in titles), "CA-specific source should be eligible"
        assert any(t.startswith("IRS ") or t.startswith("26 U.S. Code") for t in titles), \
            "federal US sources should still be eligible for a state-qualified jurisdiction"
        assert not any("New York" in t for t in titles), "a different state's source must stay excluded"
    print("test_california_tax_query_finds_federal_and_state_sources_live: PASSED")


async def main():
    test_acceptable_jurisdiction_scopes_expands_state_qualified_jurisdictions()
    test_jurisdiction_ok_accepts_federal_and_state_scope_for_state_jurisdiction()
    await test_california_tax_query_finds_federal_and_state_sources_live()
    print("All tests passed successfully!")


if __name__ == "__main__":
    asyncio.run(main())
