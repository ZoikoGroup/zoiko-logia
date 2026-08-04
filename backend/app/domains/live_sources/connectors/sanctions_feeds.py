"""Official OFAC, UN, UK, and EU sanctions snapshot parsers."""
from __future__ import annotations

import csv
import hashlib
from datetime import datetime, timezone
from io import StringIO
from xml.etree import ElementTree

import httpx

from app.core.config import get_settings
from app.domains.live_sources.connectors.feed_base import SanctionsFeedConnector
from app.domains.live_sources.feed_schemas import SanctionsEntry, SanctionsSnapshot


def _feed_headers() -> dict[str, str]:
    # Built per call rather than as a module constant so an operator can
    # change the contact address in SANCTIONS_FEED_USER_AGENT without a
    # redeploy of anything that imported this module at a different value.
    return {
        "Accept": "application/xml,text/csv;q=0.9,*/*;q=0.1",
        "User-Agent": get_settings().SANCTIONS_FEED_USER_AGENT,
    }


def _candidate_urls(primary: str, fallbacks: str) -> tuple[str, ...]:
    """Primary first, then any configured alternates, de-duplicated and
    order-preserving. Both OFAC and the EU FSF publish the same list at more
    than one official address, and which one a given deployment's egress can
    reach is a network fact, not a code fact."""
    ordered = [primary, *(item.strip() for item in fallbacks.split(",") if item.strip())]
    return tuple(dict.fromkeys(url for url in ordered if url))


async def _get(url: str, *, timeout: float, client: httpx.AsyncClient | None) -> httpx.Response:
    # The headers are identical on both branches on purpose. They used to
    # differ — the shared-client path sent a User-Agent and the
    # construct-a-client path sent none — so a feed that a host rejects for
    # an unidentified client behaved differently in a script than in the
    # worker, which is the worst possible way to debug a 403.
    if client is not None:
        return await client.get(url, headers=_feed_headers())
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as c:
        return await c.get(url, headers=_feed_headers())


async def _download(
    url: str, *, timeout: float, max_bytes: int, client: httpx.AsyncClient | None,
    fallback_urls: str = "",
) -> bytes:
    candidates = _candidate_urls(url, fallback_urls)
    if not candidates:
        raise ValueError("sanctions feed URL is not configured")

    failures: list[str] = []
    for candidate in candidates:
        try:
            response = await _get(candidate, timeout=timeout, client=client)
            response.raise_for_status()
            declared = int(response.headers.get("Content-Length", "0") or 0)
            if declared > max_bytes or len(response.content) > max_bytes:
                # A size breach is a property of the feed, not of the
                # address — trying another mirror of the same oversized list
                # would just download it again.
                raise ValueError(f"sanctions feed exceeds configured {max_bytes}-byte limit")
            if not response.content:
                raise ValueError("sanctions feed returned an empty body")
            return response.content
        except ValueError:
            raise
        except Exception as exc:
            failures.append(f"{candidate} -> {type(exc).__name__}: {str(exc)[:160]}")

    raise ValueError("every configured sanctions feed distribution failed: " + "; ".join(failures))


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child_text(node: ElementTree.Element, name: str) -> str:
    child = next((item for item in node.iter() if _local(item.tag) == name), None)
    return (child.text or "").strip() if child is not None else ""


def _nodes(node: ElementTree.Element, name: str):
    return (item for item in node.iter() if _local(item.tag) == name)


def _texts(node: ElementTree.Element, name: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(
        (item.text or "").strip() for item in _nodes(node, name) if (item.text or "").strip()
    ))


def _scoped_texts(node: ElementTree.Element, parent: str, child: str) -> tuple[str, ...]:
    """Text of `child` only where it sits under `parent`. Necessary because
    these schemas reuse element names across unrelated branches — OFAC has a
    <country> inside a nationality, inside an identity document, and inside
    an address, and collecting all of them would attribute a document's
    issuing country to the person as a nationality."""
    values: list[str] = []
    for parent_node in _nodes(node, parent):
        values.extend(_texts(parent_node, child))
    return tuple(dict.fromkeys(value for value in values if value))


def _labelled_identifier(kind: str, number: str, qualifier: str = "") -> str:
    label = kind or "ID"
    return f"{label}: {number}" + (f" ({qualifier})" if qualifier else "")


def _snapshot(provider: str, url: str, content: bytes, entries: list[SanctionsEntry]) -> SanctionsSnapshot:
    return SanctionsSnapshot(provider_key=provider, entries=entries,
                             fetched_at=datetime.now(timezone.utc).isoformat(), source_url=url,
                             content_sha256=hashlib.sha256(content).hexdigest())


class OFACFeedConnector(SanctionsFeedConnector):
    provider_key = "ofac"

    def __init__(self, url: str, fallback_urls: str = "") -> None:
        self.url = url
        self.fallback_urls = fallback_urls

    async def fetch_snapshot(self, *, timeout: float, max_bytes: int, client=None) -> SanctionsSnapshot:
        content = await _download(self.url, timeout=timeout, max_bytes=max_bytes, client=client,
                                  fallback_urls=self.fallback_urls)
        root = ElementTree.fromstring(content)
        entries = []
        for node in (item for item in root.iter() if _local(item.tag) == "sdnEntry"):
            uid = _child_text(node, "uid")
            name = " ".join(filter(None, (_child_text(node, "firstName"), _child_text(node, "lastName")))).strip()
            aliases = []
            for aka in (item for item in node.iter() if _local(item.tag) == "aka"):
                alias = " ".join(filter(None, (_child_text(aka, "firstName"), _child_text(aka, "lastName")))).strip()
                if alias and alias != name:
                    aliases.append(alias)
            programs = _texts(node, "program")
            identifiers = tuple(
                _labelled_identifier(_child_text(id_node, "idType"), _child_text(id_node, "idNumber"),
                                     _child_text(id_node, "idCountry"))
                for id_node in _nodes(node, "id")
                if _child_text(id_node, "idNumber")
            )
            if uid and name:
                entries.append(SanctionsEntry(provider_key=self.provider_key, record_id=uid,
                                               entity_type=_child_text(node, "sdnType") or "unknown",
                                               primary_name=name, aliases=tuple(dict.fromkeys(aliases)), programs=programs,
                                               identifiers=tuple(dict.fromkeys(identifiers)),
                                               nationalities=_scoped_texts(node, "nationality", "country"),
                                               dates_of_birth=_texts(node, "dateOfBirth"),
                                               source_url="https://ofac.treasury.gov/sanctions-list-service"))
        if not entries:
            raise ValueError("OFAC XML contained no SDN entries")
        return _snapshot(self.provider_key, self.url, content, entries)


class UNSanctionsFeedConnector(SanctionsFeedConnector):
    provider_key = "un_sanctions"

    def __init__(self, url: str, fallback_urls: str = "") -> None:
        self.url = url
        self.fallback_urls = fallback_urls

    async def fetch_snapshot(self, *, timeout: float, max_bytes: int, client=None) -> SanctionsSnapshot:
        content = await _download(self.url, timeout=timeout, max_bytes=max_bytes, client=client,
                                  fallback_urls=self.fallback_urls)
        root = ElementTree.fromstring(content)
        entries = []
        for node in (item for item in root.iter() if _local(item.tag) in {"INDIVIDUAL", "ENTITY"}):
            entity_type = _local(node.tag).lower()
            uid = _child_text(node, "DATAID") or _child_text(node, "REFERENCE_NUMBER")
            fields = ("FIRST_NAME", "SECOND_NAME", "THIRD_NAME", "FOURTH_NAME") if entity_type == "individual" else ("FIRST_NAME",)
            name = " ".join(filter(None, (_child_text(node, field) for field in fields))).strip()
            aliases = _texts(node, "ALIAS_NAME")
            identifiers = tuple(
                _labelled_identifier(_child_text(doc, "TYPE_OF_DOCUMENT") or "Document",
                                     _child_text(doc, "NUMBER"),
                                     _child_text(doc, "ISSUING_COUNTRY"))
                for doc in _nodes(node, "INDIVIDUAL_DOCUMENT")
                if _child_text(doc, "NUMBER")
            )
            dates_of_birth = _scoped_texts(node, "INDIVIDUAL_DATE_OF_BIRTH", "DATE") or _scoped_texts(
                node, "INDIVIDUAL_DATE_OF_BIRTH", "YEAR"
            )
            if uid and name:
                entries.append(SanctionsEntry(provider_key=self.provider_key, record_id=uid, entity_type=entity_type,
                                               primary_name=name, aliases=aliases,
                                               programs=tuple(filter(None, (_child_text(node, "UN_LIST_TYPE"),))),
                                               listed_on=_child_text(node, "LISTED_ON") or None,
                                               identifiers=tuple(dict.fromkeys(identifiers)),
                                               nationalities=_scoped_texts(node, "NATIONALITY", "VALUE"),
                                               dates_of_birth=dates_of_birth,
                                               source_url="https://main.un.org/securitycouncil/en/content/un-sc-consolidated-list"))
        if not entries:
            raise ValueError("UN XML contained no consolidated-list entries")
        return _snapshot(self.provider_key, self.url, content, entries)


def _normalized_row(row: dict[str, str]) -> dict[str, str]:
    normalized = {}
    for key, value in row.items():
        if key is None:
            continue
        if isinstance(value, list):
            value = " ".join(str(item) for item in value if item)
        normalized["".join(ch for ch in key.lower() if ch.isalnum())] = str(value or "").strip()
    return normalized


def _pick(row: dict[str, str], *keys: str) -> str:
    return next((row.get(key, "") for key in keys if row.get(key, "")), "")


# Column names differ between the UK and EU distributions and have changed
# before, so each identifier kind lists every header this parser has seen.
# An identifier that is simply absent stays absent — a screening record must
# never imply an identifier check that did not happen.
_CSV_IDENTIFIER_COLUMNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Passport", ("passportnumber", "passportdetails", "identificationpassportno")),
    ("National ID", ("nationalidentificationnumber", "nationalidnumber", "nationalidentificationdetails",
                     "identificationnationalidno")),
    ("Registration", ("registrationnumber", "companynumber", "businessregistrationnumber",
                      "identificationregistrationno")),
)


def _csv_identifiers(row: dict[str, str]) -> tuple[str, ...]:
    found = (
        _labelled_identifier(kind, _pick(row, *columns))
        for kind, columns in _CSV_IDENTIFIER_COLUMNS
        if _pick(row, *columns)
    )
    return tuple(dict.fromkeys(found))


class CSVSanctionsFeedConnector(SanctionsFeedConnector):
    def __init__(self, provider_key: str, url: str, landing_url: str, jurisdiction: str,
                 fallback_urls: str = "") -> None:
        self.provider_key, self.url, self.landing_url, self.jurisdiction = provider_key, url, landing_url, jurisdiction
        self.fallback_urls = fallback_urls

    async def fetch_snapshot(self, *, timeout: float, max_bytes: int, client=None) -> SanctionsSnapshot:
        content = await _download(self.url, timeout=timeout, max_bytes=max_bytes, client=client,
                                  fallback_urls=self.fallback_urls)
        text = content.decode("utf-8-sig", errors="replace")
        entries_by_id: dict[str, SanctionsEntry] = {}
        for raw in csv.DictReader(StringIO(text)):
            row = _normalized_row(raw)
            uid = _pick(row, "uniqueid", "entitylogicalid", "logicalid", "id")
            name_parts = [_pick(row, f"name{i}") for i in range(1, 7)]
            name = " ".join(part for part in name_parts if part) or _pick(row, "namealiaswholename", "fullname", "name")
            if not uid or not name:
                continue
            existing = entries_by_id.get(uid)
            if existing is not None:
                if name != existing.primary_name and name not in existing.aliases:
                    existing.aliases = (*existing.aliases, name)
                continue
            programs = tuple(filter(None, (_pick(row, "regimename", "programme", "program"),)))
            entries_by_id[uid] = SanctionsEntry(
                provider_key=self.provider_key, record_id=uid,
                entity_type=_pick(row, "individualentityship", "entitysubjecttype", "type") or "unknown",
                primary_name=name, programs=programs,
                listed_on=_pick(row, "datesdesignated", "listingdate", "listedon") or None,
                identifiers=_csv_identifiers(row),
                nationalities=tuple(filter(None, (_pick(row, "nationality", "countryofcitizenship"),))),
                dates_of_birth=tuple(filter(None, (_pick(row, "dob", "dateofbirth"),))),
                source_url=self.landing_url,
            )
        entries = list(entries_by_id.values())
        if not entries:
            raise ValueError(f"{self.provider_key} CSV contained no sanctions entries")
        return _snapshot(self.provider_key, self.url, content, entries)
