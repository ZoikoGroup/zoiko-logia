"""Official OFAC, UN, UK, and EU sanctions snapshot parsers."""
from __future__ import annotations

import csv
import hashlib
from datetime import datetime, timezone
from io import StringIO
from xml.etree import ElementTree

import httpx

from app.domains.live_sources.connectors.feed_base import SanctionsFeedConnector
from app.domains.live_sources.feed_schemas import SanctionsEntry, SanctionsSnapshot


async def _download(url: str, *, timeout: float, max_bytes: int, client: httpx.AsyncClient | None) -> bytes:
    if not url:
        raise ValueError("sanctions feed URL is not configured")
    if client is not None:
        response = await client.get(url, headers={"Accept": "application/xml,text/csv;q=0.9,*/*;q=0.1", "User-Agent": "Kriton/1.0 authoritative-source-monitor"})
    else:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as c:
            response = await c.get(url, headers={"Accept": "application/xml,text/csv;q=0.9,*/*;q=0.1"})
    response.raise_for_status()
    declared = int(response.headers.get("Content-Length", "0") or 0)
    if declared > max_bytes or len(response.content) > max_bytes:
        raise ValueError(f"sanctions feed exceeds configured {max_bytes}-byte limit")
    if not response.content:
        raise ValueError("sanctions feed returned an empty body")
    return response.content


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child_text(node: ElementTree.Element, name: str) -> str:
    child = next((item for item in node.iter() if _local(item.tag) == name), None)
    return (child.text or "").strip() if child is not None else ""


def _snapshot(provider: str, url: str, content: bytes, entries: list[SanctionsEntry]) -> SanctionsSnapshot:
    return SanctionsSnapshot(provider_key=provider, entries=entries,
                             fetched_at=datetime.now(timezone.utc).isoformat(), source_url=url,
                             content_sha256=hashlib.sha256(content).hexdigest())


class OFACFeedConnector(SanctionsFeedConnector):
    provider_key = "ofac"

    def __init__(self, url: str) -> None:
        self.url = url

    async def fetch_snapshot(self, *, timeout: float, max_bytes: int, client=None) -> SanctionsSnapshot:
        content = await _download(self.url, timeout=timeout, max_bytes=max_bytes, client=client)
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
            programs = tuple(dict.fromkeys((item.text or "").strip() for item in node.iter()
                                            if _local(item.tag) == "program" and (item.text or "").strip()))
            if uid and name:
                entries.append(SanctionsEntry(provider_key=self.provider_key, record_id=uid,
                                               entity_type=_child_text(node, "sdnType") or "unknown",
                                               primary_name=name, aliases=tuple(dict.fromkeys(aliases)), programs=programs,
                                               source_url="https://ofac.treasury.gov/sanctions-list-service"))
        if not entries:
            raise ValueError("OFAC XML contained no SDN entries")
        return _snapshot(self.provider_key, self.url, content, entries)


class UNSanctionsFeedConnector(SanctionsFeedConnector):
    provider_key = "un_sanctions"

    def __init__(self, url: str) -> None:
        self.url = url

    async def fetch_snapshot(self, *, timeout: float, max_bytes: int, client=None) -> SanctionsSnapshot:
        content = await _download(self.url, timeout=timeout, max_bytes=max_bytes, client=client)
        root = ElementTree.fromstring(content)
        entries = []
        for node in (item for item in root.iter() if _local(item.tag) in {"INDIVIDUAL", "ENTITY"}):
            entity_type = _local(node.tag).lower()
            uid = _child_text(node, "DATAID") or _child_text(node, "REFERENCE_NUMBER")
            fields = ("FIRST_NAME", "SECOND_NAME", "THIRD_NAME", "FOURTH_NAME") if entity_type == "individual" else ("FIRST_NAME",)
            name = " ".join(filter(None, (_child_text(node, field) for field in fields))).strip()
            aliases = tuple(dict.fromkeys((item.text or "").strip() for item in node.iter()
                                          if _local(item.tag) == "ALIAS_NAME" and (item.text or "").strip()))
            if uid and name:
                entries.append(SanctionsEntry(provider_key=self.provider_key, record_id=uid, entity_type=entity_type,
                                               primary_name=name, aliases=aliases,
                                               programs=tuple(filter(None, (_child_text(node, "UN_LIST_TYPE"),))),
                                               listed_on=_child_text(node, "LISTED_ON") or None,
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


class CSVSanctionsFeedConnector(SanctionsFeedConnector):
    def __init__(self, provider_key: str, url: str, landing_url: str, jurisdiction: str) -> None:
        self.provider_key, self.url, self.landing_url, self.jurisdiction = provider_key, url, landing_url, jurisdiction

    async def fetch_snapshot(self, *, timeout: float, max_bytes: int, client=None) -> SanctionsSnapshot:
        content = await _download(self.url, timeout=timeout, max_bytes=max_bytes, client=client)
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
                source_url=self.landing_url,
            )
        entries = list(entries_by_id.values())
        if not entries:
            raise ValueError(f"{self.provider_key} CSV contained no sanctions entries")
        return _snapshot(self.provider_key, self.url, content, entries)
