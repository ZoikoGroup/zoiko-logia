"""
US Government Publishing Office GovInfo API adapter — read-only wrapper
for looking up a specific 26 CFR (Internal Revenue) regulation section by
its section number (e.g. "1.401(k)-1") and returning its actual text.

Unlike the other reference_data adapters (which fetch a numeric series),
this one does two real HTTP calls per lookup:
  1. POST /search — find the CFR granule (a single section) whose number
     matches, scoped to collection:CFR and confirmed to be under Title 26.
  2. GET the granule's XML — the actual regulation text, parsed into plain
     text.

GovInfo's free-text search does NOT reliably support a `title:26` field
filter combined with a quoted section-number phrase (verified empirically:
`collection:CFR AND title:26 AND "1.61-1"` returns 0 hits, while dropping
the title filter and post-filtering results by packageId returns the
correct granule as the top hit). So Title 26 scoping is done in this
adapter's own code, not left to the query string.

Nothing outside app/domains/reference_data/ should import this module
directly — everything goes through service.py, which gives every external
call the audit trail and caching the reference-data doctrine requires.
"""
from __future__ import annotations

import re
from xml.etree import ElementTree

import httpx

from app.core.config import get_settings

_SEARCH_PATH = "/search"
_REQUEST_TIMEOUT_SECONDS = 15.0


class GovInfoAPIError(Exception):
    """Raised for any non-200 response, no-confident-match result, or
    transport failure — callers never see a raw httpx exception."""


def _normalize_section_suffix(section_number: str) -> str:
    """Converts a section number like "1.401(k)-1" into the suffix GovInfo
    uses in its granule ids ("1-401k-1") — dots become hyphens, parens are
    dropped. Used to confirm a search hit is actually the requested
    section, not just a document that happens to mention it."""
    return section_number.lower().replace(".", "-").replace("(", "").replace(")", "")


async def _search_cfr_granule(section_number: str) -> dict:
    settings = get_settings()
    body = {
        "query": f'collection:CFR AND "{section_number}"',
        "pageSize": 10,
        "offsetMark": "*",
        "sorts": [{"field": "relevancy", "sortOrder": "DESC"}],
        "historical": False,
        "resultLevel": "default",
    }

    try:
        async with httpx.AsyncClient(
            base_url=settings.GOVINFO_API_BASE_URL, timeout=_REQUEST_TIMEOUT_SECONDS
        ) as client:
            response = await client.post(
                _SEARCH_PATH, params={"api_key": settings.GOVINFO_API_KEY}, json=body
            )
    except httpx.TimeoutException as exc:
        raise GovInfoAPIError(f"GovInfo API timed out after {_REQUEST_TIMEOUT_SECONDS}s") from exc
    except httpx.HTTPError as exc:
        raise GovInfoAPIError(f"GovInfo API request failed: {exc}") from exc

    if response.status_code != 200:
        raise GovInfoAPIError(f"GovInfo API returned {response.status_code}: {response.text[:200]}")

    try:
        results = response.json().get("results", [])
    except ValueError as exc:
        raise GovInfoAPIError(f"Unexpected GovInfo API response shape: {exc}") from exc

    suffix = _normalize_section_suffix(section_number)
    matches = [
        r for r in results
        if "title26" in r.get("packageId", "") and r.get("granuleId", "").endswith(f"sec{suffix}")
    ]
    if not matches:
        raise GovInfoAPIError(f"No confirmed 26 CFR granule found for section {section_number}")

    # Prefer the most recently issued annual edition if more than one matched.
    matches.sort(key=lambda r: r.get("dateIssued", ""), reverse=True)
    return matches[0]


def _extract_section_text(xml_bytes: bytes) -> tuple[str, str]:
    """Parses a CFR granule's XML into (subject, body_text). Trusted-source
    XML from a US government API, not user-uploaded content — a plain
    stdlib ElementTree parse is proportionate here; nothing else in this
    codebase parses XML, so no new dependency is introduced for it."""
    root = ElementTree.fromstring(xml_bytes)
    section = root.find(".//SECTION")
    if section is None:
        raise GovInfoAPIError("Unexpected CFR granule XML shape: no <SECTION> element")

    subject = (section.findtext("SUBJECT") or "").strip()
    paragraphs = []
    for p in section.findall("P"):
        text = " ".join("".join(p.itertext()).split())
        if text:
            paragraphs.append(text)

    return subject, "\n\n".join(paragraphs)


async def get_cfr_section(section_number: str) -> dict:
    """Looks up a specific 26 CFR section and returns its real text.
    Raises GovInfoAPIError if no section under Title 26 confidently matches
    — callers must treat that as "skip the live fetch", not fall back to a
    guessed/adjacent section."""
    granule = await _search_cfr_granule(section_number)
    settings = get_settings()
    xml_url = granule["download"]["xmlLink"]

    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.get(xml_url, params={"api_key": settings.GOVINFO_API_KEY})
    except httpx.TimeoutException as exc:
        raise GovInfoAPIError(f"GovInfo API timed out after {_REQUEST_TIMEOUT_SECONDS}s") from exc
    except httpx.HTTPError as exc:
        raise GovInfoAPIError(f"GovInfo API request failed: {exc}") from exc

    if response.status_code != 200:
        raise GovInfoAPIError(f"GovInfo API returned {response.status_code}: {response.text[:200]}")

    try:
        subject, text = _extract_section_text(response.content)
    except ElementTree.ParseError as exc:
        raise GovInfoAPIError(f"Unexpected CFR granule XML shape: {exc}") from exc

    return {
        "section_number": section_number,
        "subject": subject,
        "text": text,
        "package_id": granule["packageId"],
        "granule_id": granule["granuleId"],
        "date_issued": granule.get("dateIssued", ""),
        "details_url": f"https://www.govinfo.gov/app/details/{granule['packageId']}/{granule['granuleId']}",
    }
