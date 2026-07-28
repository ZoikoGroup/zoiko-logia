"""
eCFR (Electronic Code of Federal Regulations) API adapter — read-only
wrapper for fetching the current, as-amended text of a specific 26 CFR
(Internal Revenue) section. Fully public, no API key required.

Does the same conceptual job as govinfo_adapter.py's CFR lookup, kept
alongside it rather than replacing it — eCFR reflects the current amended
text (continuously updated) rather than GovInfo's static annual edition,
so the two are complementary, not redundant, evidence.

Two real HTTP calls per lookup:
  1. GET /titles.json — eCFR rejects any date past a title's own
     "most recent issue date" (verified empirically), so the current date
     to query with must come from here, not just today's calendar date.
  2. GET /full/{date}/title-26.xml?part={part}&section={section} — the
     actual regulation text for that section as of that date.

Nothing outside app/domains/reference_data/ should import this module
directly — everything goes through service.py, which gives every external
call the audit trail and caching the reference-data doctrine requires.
"""
from __future__ import annotations

from xml.etree import ElementTree

import httpx

from app.core.config import get_settings

_REQUEST_TIMEOUT_SECONDS = 15.0
_TITLE_26 = 26


class ECFRAPIError(Exception):
    """Raised for any non-200 response, unexpected shape, or transport
    failure — callers never see a raw httpx exception."""


async def _get_title26_current_date(client: httpx.AsyncClient) -> str:
    try:
        response = await client.get("/titles.json")
    except httpx.TimeoutException as exc:
        raise ECFRAPIError(f"eCFR API timed out after {_REQUEST_TIMEOUT_SECONDS}s") from exc
    except httpx.HTTPError as exc:
        raise ECFRAPIError(f"eCFR API request failed: {exc}") from exc

    if response.status_code != 200:
        raise ECFRAPIError(f"eCFR API returned {response.status_code}: {response.text[:200]}")

    try:
        titles = response.json().get("titles", [])
    except ValueError as exc:
        raise ECFRAPIError(f"Unexpected eCFR API response shape: {exc}") from exc

    title26 = next((t for t in titles if t.get("number") == _TITLE_26), None)
    if title26 is None or not title26.get("up_to_date_as_of"):
        raise ECFRAPIError("eCFR API did not return Title 26 metadata")

    return title26["up_to_date_as_of"]


def _extract_section_text(xml_bytes: bytes) -> tuple[str, str]:
    """Parses an eCFR section's XML (a <DIV8 TYPE="SECTION"> element) into
    (heading, body_text). Trusted-source XML from a US government API, not
    user-uploaded content — a plain stdlib ElementTree parse is
    proportionate here, same reasoning as govinfo_adapter.py."""
    root = ElementTree.fromstring(xml_bytes)
    section = root if root.tag == "DIV8" else root.find(".//DIV8")
    if section is None:
        raise ECFRAPIError("Unexpected eCFR section XML shape: no <DIV8> element")

    heading = (section.findtext("HEAD") or "").strip()
    paragraphs = []
    for p in section.findall("P"):
        text = " ".join("".join(p.itertext()).split())
        if text:
            paragraphs.append(text)

    return heading, "\n\n".join(paragraphs)


async def get_cfr_section(section_number: str) -> dict:
    """Looks up a specific 26 CFR section's current text. Raises
    ECFRAPIError if the section doesn't exist or the API can't serve it —
    callers must treat that as "skip this source" (GovInfo may still
    succeed independently), not fall back to a guessed section."""
    part = section_number.split(".")[0]
    settings = get_settings()

    async with httpx.AsyncClient(
        base_url=settings.ECFR_API_BASE_URL, timeout=_REQUEST_TIMEOUT_SECONDS
    ) as client:
        date = await _get_title26_current_date(client)

        try:
            response = await client.get(
                f"/full/{date}/title-26.xml", params={"part": part, "section": section_number}
            )
        except httpx.TimeoutException as exc:
            raise ECFRAPIError(f"eCFR API timed out after {_REQUEST_TIMEOUT_SECONDS}s") from exc
        except httpx.HTTPError as exc:
            raise ECFRAPIError(f"eCFR API request failed: {exc}") from exc

    if response.status_code != 200:
        raise ECFRAPIError(f"eCFR API returned {response.status_code}: {response.text[:200]}")

    try:
        heading, text = _extract_section_text(response.content)
    except ElementTree.ParseError as exc:
        raise ECFRAPIError(f"Unexpected eCFR section XML shape: {exc}") from exc

    if not text:
        raise ECFRAPIError(f"eCFR API returned no section text for {section_number}")

    return {
        "section_number": section_number,
        "heading": heading,
        "text": text,
        "date": date,
        "details_url": f"https://www.ecfr.gov/current/title-26/section-{section_number}",
    }
