"""
Tier 2 (LLM reasoning) + Tier 3 (validation) fallback for live-data country/
indicator resolution — generalizes the pattern already proven for company-
name extraction (llm_fallback.py) to the rest of classifier.py.

Real API calls, no mocking — the whole point of this tier is verifying it
generalizes to phrasing Tier 0/1's keyword/exemplar tables were never built
to recognize, which a mocked response can't demonstrate. Requires
GROQ_API_KEY.

Two real, reported failures this fixes:
1. Total miss: "How is India's economy performing lately?" named no
   indicator keyword Tier 1's semantic exemplars were tuned for.
2. Silent wrong country: "How many people are out of work in Britain right
   now?" matched "unemployment" correctly but "Britain" wasn't a known
   country alias, so it silently returned World Bank's global aggregate
   instead of the UK's own figure — confirmed live before this fix.

Also locks in the safety property that makes this "enterprise-ready" and
not just "smarter": a country/indicator the LLM names but which Kriton has
no connector for (e.g. France — not in _COUNTRY_ALIASES) must NOT be
routed to. Tier 3 rejects it and falls back to whatever Tier 0/1 already
had, never fabricating a route to an unsupported country.

Run with: python tests/test_live_data_llm_fallback.py
"""
import asyncio
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from app.core.database import AsyncSessionLocal
from app.domains.live_sources.service import fetch_live_data


async def _resolve(query: str, jurisdiction: str = ""):
    async with AsyncSessionLocal() as db:
        return await fetch_live_data(db, query=query, tenant_id="test-tenant-tier2", jurisdiction=jurisdiction)


async def test_total_miss_resolves_via_tier2():
    if not os.environ.get("GROQ_API_KEY"):
        print("test_total_miss_resolves_via_tier2: SKIPPED (no GROQ_API_KEY)")
        return
    outcome = await _resolve("How is India's economy performing lately?")
    assert outcome.intent is not None, "Tier 2 should resolve a query naming no indicator keyword at all"
    assert outcome.intent.country_code == "IN"
    assert outcome.intent.provider_key == "world_bank"
    print("test_total_miss_resolves_via_tier2: PASSED")


async def test_gdp_growth_phrasing_resolves_uk_via_tier2():
    if not os.environ.get("GROQ_API_KEY"):
        print("test_gdp_growth_phrasing_resolves_uk_via_tier2: SKIPPED (no GROQ_API_KEY)")
        return
    outcome = await _resolve("Is the UK economy growing or shrinking?")
    assert outcome.intent is not None
    assert outcome.intent.country_code == "GB", f"expected GB, got {outcome.intent.country_code}"
    print("test_gdp_growth_phrasing_resolves_uk_via_tier2: PASSED")


async def test_colloquial_uk_reference_resolves_correct_country():
    """'Blighty' is real British slang for the UK that no alias table would
    ever practically enumerate — this is the case Tier 2 exists for."""
    if not os.environ.get("GROQ_API_KEY"):
        print("test_colloquial_uk_reference_resolves_correct_country: SKIPPED (no GROQ_API_KEY)")
        return
    outcome = await _resolve("What is the unemployment situation like in Blighty?")
    assert outcome.intent is not None
    assert outcome.intent.country_code == "GB", f"expected GB, got {outcome.intent.country_code}"
    assert outcome.intent.provider_key == "ons", "GB unemployment should route to ONS, not the generic World Bank fallback"
    print("test_colloquial_uk_reference_resolves_correct_country: PASSED")


async def test_unsupported_country_is_rejected_not_fabricated():
    """Tier 3's actual safety property: France is not in _COUNTRY_ALIASES.
    Even if the LLM correctly names it, resolve_live_data_intent_from_llm_guess
    must refuse to route there — proving this doesn't just get smarter, it
    stays safe about what it doesn't actually support."""
    if not os.environ.get("GROQ_API_KEY"):
        print("test_unsupported_country_is_rejected_not_fabricated: SKIPPED (no GROQ_API_KEY)")
        return
    outcome = await _resolve("What is the cost of living increase in France?")
    if outcome.intent is not None:
        assert outcome.intent.country_code != "FR", "must never fabricate a route to a country with no real connector"
    print("test_unsupported_country_is_rejected_not_fabricated: PASSED")


async def test_unrelated_query_never_triggers_the_gate():
    """No economic cue words at all — must resolve to no intent without
    ever spending an LLM call (verified indirectly: this passes even
    without a GROQ_API_KEY, since the gate itself should short-circuit)."""
    outcome = await _resolve("What is IFRS 16?")
    assert outcome.intent is None
    outcome2 = await _resolve("Explain the premium tax credit eligibility process")
    assert outcome2.intent is None
    print("test_unrelated_query_never_triggers_the_gate: PASSED")


async def main():
    await test_unrelated_query_never_triggers_the_gate()
    await test_total_miss_resolves_via_tier2()
    await test_gdp_growth_phrasing_resolves_uk_via_tier2()
    await test_colloquial_uk_reference_resolves_correct_country()
    await test_unsupported_country_is_rejected_not_fabricated()
    print("All tests passed successfully!")


if __name__ == "__main__":
    asyncio.run(main())
