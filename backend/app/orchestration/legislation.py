"""Structured UK legislation grounding from legislation.gov.uk.

The service is public and keyless.  This connector resolves an Act (and, when
present, a section) from the user's question, downloads the official CLML XML,
and converts the useful text into the same ``WebSource`` used by every other
Ask Kriton live source.

It deliberately self-gates and fails soft.  A general accounting question
must not acquire an unrelated Act, and an unavailable government endpoint must
not break the answer pipeline.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit
from xml.etree import ElementTree

import httpx

from app.core.config import get_settings
from app.orchestration.websearch import WebSource


_LEGISLATION_HINT = re.compile(
    r"\b(legislation|statute|statutory|law|legal|act(?:s)?|regulation(?:s)?|"
    r"section\s+\d+[A-Za-z]?|schedule\s+\d+)\b",
    re.I,
)
_TITLE = re.compile(
    r"\b((?:[A-Z][A-Za-z'&.-]*\s+){0,7}(?:Act|Regulations))\s+(18|19|20)\d{2}\b",
    re.I,
)
_SECTION = re.compile(r"\bsection\s+(\d+[A-Za-z]?)\b", re.I)
_OFFICIAL_URL = re.compile(r"https?://(?:www\.)?legislation\.gov\.uk/[^\s<>)\]]+", re.I)

# Stable identifiers for the UK business/accounting statutes Kriton is most
# likely to be asked about. Unknown titles still use the official Atom search.
_KNOWN: dict[tuple[str, str], str] = {
    ("companies act", "2006"): "/ukpga/2006/46",
    ("insolvency act", "1986"): "/ukpga/1986/45",
    ("value added tax act", "1994"): "/ukpga/1994/23",
    ("employment rights act", "1996"): "/ukpga/1996/18",
    ("equality act", "2010"): "/ukpga/2010/15",
    ("limited liability partnerships act", "2000"): "/ukpga/2000/12",
    ("corporation tax act", "2009"): "/ukpga/2009/4",
    ("corporation tax act", "2010"): "/ukpga/2010/4",
}


def _base_url() -> str:
    # pydantic-settings reads backend/.env locally and process environment in
    # deployed containers. Keeping this in the central Settings model also
    # makes the connector's runtime configuration explicit and validated.
    return get_settings().LEGISLATION_API_BASE_URL.rstrip("/")


def _clean_official_url(value: str) -> str:
    """Keep only a legislation path, removing presentation/data suffixes."""
    parts = urlsplit(value.rstrip(".,;:"))
    path = re.sub(r"/(?:data\.(?:xml|akn|html)|contents)$", "", parts.path.rstrip("/"), flags=re.I)
    return urlunsplit((parts.scheme or "https", parts.netloc, path, "", ""))


def _query_target(query: str) -> tuple[str, str, str] | None:
    """Return (title, year, direct URL/path), or None for non-legislation."""
    url_match = _OFFICIAL_URL.search(query)
    if url_match:
        return "UK legislation", "", _clean_official_url(url_match.group(0))
    if not _LEGISLATION_HINT.search(query):
        return None
    title_match = _TITLE.search(query)
    if not title_match:
        return None
    full = title_match.group(0)
    year = re.search(r"(?:18|19|20)\d{2}", full)
    if not year:
        return None
    title = full[: year.start()].strip()
    # The permissive title matcher necessarily sees leading question prose.
    # Remove only common grammatical wrappers; retain the statute's words.
    wrappers = re.compile(
        r"^(?:(?:what\s+does|what\s+is|explain|describe|summari[sz]e|"
        r"tell\s+me\s+about|under|according\s+to|of)\s+)?(?:the\s+)?",
        re.I,
    )
    previous = None
    while title != previous:
        previous = title
        title = wrappers.sub("", title).strip()
    key = (title.lower(), year.group(0))
    return title, year.group(0), _KNOWN.get(key, "")


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _entry_url(feed_xml: str, title: str, year: str) -> str:
    """Choose the closest matching legislation entry from an Atom feed."""
    root = ElementTree.fromstring(feed_xml)
    wanted = f"{title} {year}".lower()
    fallback = ""
    for entry in (node for node in root.iter() if _local_name(node.tag) == "entry"):
        entry_title = next((" ".join(n.itertext()).strip() for n in entry if _local_name(n.tag) == "title"), "")
        links = [n.attrib.get("href", "") for n in entry if _local_name(n.tag) == "link"]
        url = next((link for link in links if "legislation.gov.uk/" in link and "/data." not in link), "")
        fallback = fallback or url
        if entry_title.lower() == wanted and url:
            return url
    return fallback


def _document_text(xml: str) -> tuple[str, str]:
    root = ElementTree.fromstring(xml)
    title = next(
        (" ".join(node.itertext()).strip() for node in root.iter() if _local_name(node.tag) in {"Title", "title"}),
        "UK legislation",
    )
    bodies = [node for node in root.iter() if _local_name(node.tag) in {"Body", "Schedules"}]
    selected = bodies or [root]
    text = " ".join(" ".join(node.itertext()) for node in selected)
    return title, re.sub(r"\s+", " ", text).strip()


async def fetch_legislation(query: str, *, client: httpx.AsyncClient | None = None) -> list[WebSource]:
    """Return official structured text for a named UK Act/provision."""
    target = _query_target(query)
    if target is None:
        return []
    title, year, resolved = target
    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=10.0, follow_redirects=True)
    try:
        if resolved.startswith("http"):
            page_url = resolved
        elif resolved:
            page_url = f"{_base_url()}{resolved}"
        else:
            response = await http.get(f"{_base_url()}/all/data.feed", params={"title": title, "year": year})
            response.raise_for_status()
            page_url = _entry_url(response.text, title, year)
            if not page_url:
                return []

        section = _SECTION.search(query)
        if section and "/section/" not in page_url:
            page_url = f"{page_url.rstrip('/')}/section/{section.group(1)}"

        response = await http.get(f"{page_url.rstrip('/')}/data.xml")
        response.raise_for_status()
        official_title, body = _document_text(response.text)
        if not body:
            return []
        # Keep enough primary text for grounding while bounding LLM context.
        clipped = body[:12000]
        if len(body) > len(clipped):
            clipped += " …"
        return [WebSource(
            title=f"legislation.gov.uk — {official_title}"[:200],
            url=page_url,
            snippet=(
                f"Official UK legislation, latest revised text available from legislation.gov.uk. "
                f"{clipped}"
            ),
            provider="legislation.gov.uk",
            freshness="legislation",
        )]
    except (httpx.HTTPError, ElementTree.ParseError, ValueError):
        return []
    finally:
        if owns_client:
            await http.aclose()
