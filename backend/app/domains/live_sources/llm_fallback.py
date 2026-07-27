"""
Tier 2 structured-extraction fallback for live-data intent detection.

Tier 1 (classifier.py's keyword + exemplar-similarity checks) handles the
large majority of queries at near-zero latency and cost. This module is
only reached when Tier 1's regex name-extraction fails but
company_lookup_needs_llm_fallback() has already confirmed the query is
worth the extra round-trip (semantically company-lookup-shaped, and the
jurisdiction resolves to a real provider) — see classifier.py's docstring
for that split of responsibility.

Never raises to its caller — same discipline as live_sources/service.py's
fetch_live_data(): an LLM outage or malformed response degrades to "no
company name found," never an exception that could break the surrounding
request.
"""
from __future__ import annotations

import json
import os

_SYSTEM_PROMPT = (
    "Extract only the company name being asked about in the user's query. "
    "Respond with ONLY a compact JSON object, no prose, no markdown fences: "
    '{"company_name": string or null}. '
    "Use null if no specific company is named."
)


async def extract_company_name_via_llm(query: str, timeout_seconds: float = 3.0) -> str | None:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return None

    try:
        import asyncio
        from groq import AsyncGroq

        client = AsyncGroq(api_key=api_key)
        response = await asyncio.wait_for(
            client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": query},
                ],
                temperature=0.0,
            ),
            timeout=timeout_seconds,
        )
        raw = response.choices[0].message.content or ""
        parsed = json.loads(raw.strip().strip("`"))
        name = parsed.get("company_name")
        return name.strip() if isinstance(name, str) and name.strip() else None
    except Exception:
        # Network error, timeout, malformed JSON, missing field — all
        # degrade to "no name found," matching Tier 1's own None-on-no-match
        # convention rather than raising into fetch_live_data().
        return None


# Tier 2 for country+indicator resolution — the same fallback shape as
# extract_company_name_via_llm() above, generalized to the rest of
# classifier.py's detect_live_data_intent(). Reached in two distinct cases
# (see classifier.py's live_data_needs_llm_fallback()):
#   1. Tier 0/1 found nothing at all (e.g. "How is India's economy doing
#      lately?" — no keyword, and this exact phrasing doesn't clear the
#      semantic exemplar threshold either).
#   2. Tier 0/1 found a real indicator but the country silently defaulted
#      to "World" (e.g. "How many people are out of work in Britain right
#      now?" — "unemployment" matched, but "Britain" wasn't a known alias,
#      confirmed live as a real, reported case).
#
# The model's raw output is NEVER routed to directly — classifier.py's
# resolve_live_data_intent_from_llm_guess() re-validates both fields
# against the exact same closed alias/indicator tables Tier 0/1 already
# uses, so an invented country or an indicator concept Kriton has no
# connector for can never produce a fabricated live source; it just
# correctly falls through to "no live match" instead.
_LIVE_DATA_SYSTEM_PROMPT = (
    "You determine what live economic/financial data a user's question is "
    "asking for, if any. Respond with ONLY a compact JSON object, no prose, "
    'no markdown fences: {"country": string or null, "indicator": string or null}. '
    '"country": the country the question is about, in plain English '
    '(e.g. "United Kingdom", "India"), or null if none is implied. '
    '"indicator": EXACTLY one of these codes, or null if none apply:\n'
    "  gdp - overall GDP / size of the economy\n"
    "  gdp_growth - GDP growth rate / whether the economy is growing or shrinking\n"
    "  inflation - inflation / consumer prices / cost of living\n"
    "  unemployment - unemployment rate / joblessness\n"
    "  bank_rate - UK Bank of England policy interest rate\n"
    "  fed_funds_rate - US Federal Reserve funds rate\n"
    "  treasury_yield - US Treasury bond yield\n"
    "  corporate_tax_rate - corporate income tax rate\n"
    "Use null for indicator if the question isn't about one of these specific things — "
    "never invent a code that isn't in this list."
)


async def extract_live_data_intent_via_llm(query: str, timeout_seconds: float = 3.0) -> dict | None:
    """Returns {"country": str|None, "indicator": str|None}, or None if the
    call couldn't be made/parsed at all (missing key, network error,
    timeout, malformed JSON) — same fail-open discipline as
    extract_company_name_via_llm(); the caller treats None exactly like
    Tier 0/1 finding nothing."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return None

    try:
        import asyncio
        from groq import AsyncGroq

        client = AsyncGroq(api_key=api_key)
        response = await asyncio.wait_for(
            client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[
                    {"role": "system", "content": _LIVE_DATA_SYSTEM_PROMPT},
                    {"role": "user", "content": query},
                ],
                temperature=0.0,
            ),
            timeout=timeout_seconds,
        )
        raw = response.choices[0].message.content or ""
        parsed = json.loads(raw.strip().strip("`"))
        country = parsed.get("country")
        indicator = parsed.get("indicator")
        return {
            "country": country.strip() if isinstance(country, str) and country.strip() else None,
            "indicator": indicator.strip().lower() if isinstance(indicator, str) and indicator.strip() else None,
        }
    except Exception:
        return None
