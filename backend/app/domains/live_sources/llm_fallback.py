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
