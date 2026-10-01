"""Fail-soft grounding from the official, keyless legislation.gov.uk API."""
from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit
from xml.etree import ElementTree

import httpx

from app.core.config import get_settings
from app.orchestration.websearch import WebSource

_HINT = re.compile(r"\b(legislation|statute|statutory|law|legal|acts?|regulations?|section\s+\d+[A-Za-z]?|schedule\s+\d+)\b", re.I)
_TITLE = re.compile(r"\b((?:[A-Z][A-Za-z'&.-]*\s+){0,7}(?:Act|Regulations))\s+(18|19|20)\d{2}\b", re.I)
_SECTION = re.compile(r"\bsection\s+(\d+[A-Za-z]?)\b", re.I)
_URL = re.compile(r"https?://(?:www\.)?legislation\.gov\.uk/[^\s<>)\]]+", re.I)
_KNOWN = {
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
    return get_settings().LEGISLATION_API_BASE_URL.rstrip("/")


def _clean_url(value: str) -> str:
    parts = urlsplit(value.rstrip(".,;:"))
    path = re.sub(r"/(?:data\.(?:xml|akn|html)|contents)$", "", parts.path.rstrip("/"), flags=re.I)
    return urlunsplit((parts.scheme or "https", parts.netloc, path, "", ""))


def _query_target(query: str) -> tuple[str, str, str] | None:
    url = _URL.search(query)
    if url:
        return "UK legislation", "", _clean_url(url.group(0))
    if not _HINT.search(query):
        return None
    match = _TITLE.search(query)
    if not match:
        return None
    full = match.group(0)
    year_match = re.search(r"(?:18|19|20)\d{2}", full)
    if not year_match:
        return None
    title = full[:year_match.start()].strip()
    wrappers = re.compile(r"^(?:(?:what\s+does|what\s+is|explain|describe|summari[sz]e|tell\s+me\s+about|under|according\s+to|of)\s+)?(?:the\s+)?", re.I)
    previous = None
    while title != previous:
        previous, title = title, wrappers.sub("", title).strip()
    year = year_match.group(0)
    return title, year, _KNOWN.get((title.lower(), year), "")


def _name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _entry_url(xml: str, title: str, year: str) -> str:
    root = ElementTree.fromstring(xml)
    wanted, fallback = f"{title} {year}".lower(), ""
    for entry in (node for node in root.iter() if _name(node.tag) == "entry"):
        entry_title = next((" ".join(node.itertext()).strip() for node in entry if _name(node.tag) == "title"), "")
        links = [node.attrib.get("href", "") for node in entry if _name(node.tag) == "link"]
        url = next((link for link in links if "legislation.gov.uk/" in link and "/data." not in link), "")
        fallback = fallback or url
        if entry_title.lower() == wanted and url:
            return url
    return fallback


def _document_text(xml: str) -> tuple[str, str]:
    root = ElementTree.fromstring(xml)
    title = next((" ".join(node.itertext()).strip() for node in root.iter() if _name(node.tag) in {"Title", "title"}), "UK legislation")
    bodies = [node for node in root.iter() if _name(node.tag) in {"Body", "Schedules"}]
    text = " ".join(" ".join(node.itertext()) for node in (bodies or [root]))
    return title, re.sub(r"\s+", " ", text).strip()


async def fetch_legislation(query: str, *, client: httpx.AsyncClient | None = None) -> list[WebSource]:
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
        clipped = body[:12000] + (" …" if len(body) > 12000 else "")
        return [WebSource(
            title=f"legislation.gov.uk — {official_title}"[:200], url=page_url,
            snippet=f"Official UK legislation, latest revised text available from legislation.gov.uk. {clipped}",
            provider="legislation.gov.uk", freshness="legislation",
        )]
    except (httpx.HTTPError, ElementTree.ParseError, ValueError):
        return []
    finally:
        if owns_client:
            await http.aclose()
